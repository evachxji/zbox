# 抖音视频下载：Playwright + 系统 Edge 签名捕获方案

> 日期：2026-10-10　状态：待实施
> 背景：2026-09 起抖音详情接口要求网页端实时签名（uifid + x-secsdk-web-signature），
> yt-dlp 上游未实现，视频解析 tab 下载抖音持续失败。曾评估引入 MediaCrawler 作为第三组件，
> 结论：许可证限制商用、形态为带扫码登录的整套爬虫工程（uv + Playwright + Chromium），
> 与 zbox「单文件 exe 组件 + 纯标准库」模型严重不匹配，弃用，仅借其签名思路。
> 参考脚本：D:\Document\桌面快捷方式\yt\douyin-dl.py（已实测可用）。

## Summary

新增 `douyin_dl.py` 模块，用 Playwright 以无头模式驱动系统自带 Edge（`channel="msedge"`，不下载浏览器、不弹窗）完成抖音网页签名，监听 response 捕获 CDN 视频流后自行流式下载。Playwright 作为第三个组件**按需在线安装**（whl 即 zip，urllib 下载解压即可，无需 pip），与 yt-dlp/ffmpeg 组件模型一致。

## Key Changes

**新增 `douyin_dl.py`**（对照 `video_dl.py` 分层：playwright 惰性导入、零 Qt、回调在后台线程）：

- `is_douyin_url(url)`：识别 douyin.com / iesdouyin.com 及 v.douyin.com 短链；`extract_url(text)` 从分享口令文本里抠链接
- `parse(url, timeout=90)` → 与 `video_dl.parse_video` 同形返回 `{title, duration, heights: [], split_heights: [], thumbnail, ...}`，另带私有键 `stream_url / stream_size / aweme_id / final_url`。实现照参考脚本：专用线程内 `asyncio.run` 起无头 Edge（临时隔离 profile，**不读写用户真实 Edge 的任何数据**）→ 注入 cookies.txt（复用 Netscape→playwright 转换）→ goto 落地页（短链跟跳转，aweme_id 取 `page.url`）→ 等 `video` 元素取 `duration` / `page.title()` / og:image → 抓 content-type 含 video 或 URL 含 .mp4 的 response，取 content-length 最大者。UA 按本机 Edge 实际版本动态生成（读 msedge.exe 版本号），不写死
- `class Download(stream_url, out_dir, title, aweme_id)`：与 `video_dl.Download` 完全相同的对外契约——`start(progress_cb, done_cb)` / `pause()` / `resume()` / `terminate()`。urllib 流式下载（带 Referer + UA），进度 0→100% 单趟直报（无合并阶段），自己算 size/speed/eta 三栏；暂停=断开保留半成品文件，继续=`Range: bytes=N-` 断点续传（CDN 回 200 拒绝 Range 时降级重新下载）；成品命名 `{title} [{aweme_id}].mp4`，撞名自动追加序号
- 报错文案约定：cookie 失效/风控验证类错误文案含 "cookies" 字样，让现有 `is_cookie_error` → CookieGuideDialog 引导链直接生效；Edge 缺失报「未找到 Edge 浏览器」（Win10/11 均有，LTSC 兜底）；未捕获到流报「需要人工验证或 cookies 已失效」

**Playwright 按需安装（`video_dl.py` 新增，对照 yt-dlp/ffmpeg 组件模式）**：

- 钉死版本常量 `PLAYWRIGHT_VER` 及依赖 pyee / greenlet 版本（升级 = 改常量，与 ffmpeg 版本目录同款玩法）；经 PyPI JSON API 解析 wheel 文件名，下载地址走镜像回退链：清华 tuna → 阿里 pypi 镜像 → files.pythonhosted.org（`/packages/...` 路径重写，与 GH_MIRRORS 同款模式）
- greenlet 是 C 扩展 wheel：按运行时 `sys.version_info` 算 ABI tag（如 cp312 win_amd64）选匹配文件，无匹配报错；playwright wheel 选 win_amd64 平台包（内含 node driver），pyee 纯 Python
- 安装 = zipfile 解压到 `tools\pylibs\`（沿用 tools_dir 回落逻辑），douyin_dl import 前 `sys.path.insert`；`import playwright` 探活即安装标记
- 触发时机两处：启用视频 tab 时随 `ensure_tools` 一起下载（门禁层进度区显示第三项组件进度，复用现有 UI）；存量用户已开启过视频的，首次解析抖音链接时补下载（任务卡 meta 行显示「正在下载解析组件…」）
- `uninstall_tools` 一并删除 `tools\pylibs\`

**`video_dl.py` 分流（精准修改）**：

- `parse_video(url)` 开头分流：`is_douyin_url` 命中即转 `douyin_dl.parse`（playwright 未装且补装失败时返回明确错误）
- 新增 `create_download(parsed, height, out_dir)` 工厂：抖音任务用 `parsed` 里的 `stream_url` 构造 `douyin_dl.Download`，否则走现有 `Download`

**`video_ui.py`（两处小改）**：

- `_start_download` 里 `video_dl.Download(...)` 改为 `video_dl.create_download(self._parsed, h, self.owner.save_dir)`
- 抖音解析中若触发组件补下载，meta 行提示进度（复用现有 `_show_meta_text`）

其余不动——`heights=[]` 时清晰度菜单天然退化为「自动」单档，进度/暂停/取消/打开文件全套交互零改动。底栏组件状态区仍只显示 yt-dlp + ffmpeg 两项。

**文档**：README 开发依赖加 `pip install playwright`（源码运行用）；AGENTS.md 同步项目结构（douyin_dl 职责）与架构细节（URL 分流、wheel 按需安装、Edge 依赖）。

## Test Plan

1. **PoC 先行** → 验证：开发环境直接对新模块跑真实抖音链接（带 cookies.txt）：短链跳转、标题/时长/封面解析、流捕获、完整下载出可播放 mp4
2. **组件安装路径** → 验证：删掉 `tools\pylibs\` 后启用视频 tab，门禁层显示 playwright 下载进度并安装成功；镜像逐个故障时回退链生效；frozen 形态（build.py 出包）下 ABI tag 匹配正确、安装后 douyin 解析可用
3. **交互验收**（手动）→ 验证：面板内解析抖音链接出任务卡（单档「自动」）；下载进度条/速度/剩余时间三栏正常；暂停后继续（比对字节数续传）；取消清理半成品；完成后「打开」可播放；同名撞车追加序号；**Edge 从未登录过抖音的干净机器上全流程验证一次**（登录态只来自 cookies.txt）
4. **失败路径** → 验证：无 cookies → 状态行浮出「查看解决办法」且 CookieGuideDialog 可开；cookies 过期/风控验证码 → failed 态文案正确；断网 → 明确报错
5. **回归** → 验证：`ZBOX_SHOT` 全量截图自检通过（抖音路径不参与截图注入，确认 playwright 惰性导入不破坏自检与启动）；B 站等 yt-dlp 站点解析下载不受影响

## Assumptions

- **单档位清晰度**（已确认）：抖音卡只显示「自动」，下载播放器实际起播的那一路流（通常即最高画质）；多档捕获需操控播放器逐档切换，不做
- **Playwright 按需在线安装**（已确认）：版本钉死在代码里，构建与运行时安装的是同一版本，消除版本漂移；镜像回退链抗单点故障
- **仅支持单条视频**：图文笔记、合集、直播不在范围内，识别到非视频页报「未捕获到视频流」
- **登录态只来自 cookies.txt**（已确认）：方案不依赖用户日常浏览器与 Edge 的登录状态，临时隔离 profile 每次全新启动；若日后冷启动指纹导致风控拦截率上升，加固后手是改 `launch_persistent_context` 把 profile 持久化到 `%APPDATA%\zbox\` 让指纹变「热」，当前版本不做
- **暂停续传走 HTTP Range**：抖音 CDN 实测支持 Range；个别节点拒绝时降级重新下载并在进度区提示
