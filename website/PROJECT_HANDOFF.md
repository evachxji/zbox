# Zbox 官网 — 项目交接文档

> 给下一个会话的 Agent：读完这份文档即可继续迭代页面，无需重新调研。
> 最后更新：2026-10-12（教程 / 截图 / 视频解析三个分镜改造为 pin 滚动演示舞台（用户要求与其他模块节奏一致）；同日新增教程分镜；拍摄目录已更名为 `photo_task`）

## 一、这个项目是什么

开源桌面整理软件 **Zbox**（https://github.com/evachxji/Zbox）的产品官网：
单页、沉浸式、**scroll-driven scrollytelling**（GSAP + ScrollTrigger scrub 驱动），
像一部产品宣传片：混乱桌面 → 格子出现 → 文件入格 → 自定义格子 → 快速上手教程 →
双击显隐 → **截图（v0.4）** → 日历待办 → **多端传输（高潮 · 三端）** → **视频解析（v0.4）** → 完整工作空间 → 下载。

- 无构建链：纯静态，`index.html` 双击即开；改完文件刷新浏览器即可。
- 文案：中文为主，短句克制（Apple 式），禁止营销词。
- 视觉：深空蓝黑底（`#0b0e14`）+ Zbox 品牌橙 `#f5a524` 唯一强调色 + 玻璃格子 + 大留白。

## 二、文件结构

```
index.html                  ← 唯一页面入口（所有分镜的 DOM 结构）
css/style.css               ← 全部样式（设计令牌在 :root）
js/app.js                   ← 全部滚动动画 + 下载链接配置 + 真实时钟/日历
js/vendor/                  ← gsap.min.js + ScrollTrigger.min.js（3.15.0，本地化，勿换 CDN）
harmony/privacy.html        ← 鸿蒙端隐私政策子页（AppGallery 上架配套）
assets/brand/icon.png       ← Zbox Logo（256×256）
assets/desktop/             ← 25 张真实软件截图（其中 theme-light-overview / settings-window 随「主题条」分镜删除暂不被页面引用，保留备用）
assets/mobile/              ← 4 张 Android 端真实截图（1080×2400；mobile-receive-dialog 为 v0.4 重拍）
assets/harmony/             ← 4 张鸿蒙端真实截图（1280×2832）
assets/video/               ← newbox-flow.mp4（10 秒 1920×1080 H.264 带指针，教程分镜用，静音循环播放）
```

素材全部来自真实运行的 Zbox v0.4（拍摄源目录：`C:\Users\yechen\Desktop\photo_task\zbox-v04-assets`
—— 原 `拍摄任务` 目录已更名，逐张登记见该目录 manifest.md；沿用的 7 张 v0.3 素材在 `photo_task\assets`）。
**用户改图后，把同名文件复制覆盖到本项目 assets/ 对应位置即可，文件名不变就不用改代码。**

## 三、页面分镜与 DOM 定位（自上而下）

| 顺序 | 分镜 | 位置 | 关键点 |
| ---- | ---- | ---- | ------ |
| 1 | Hero | `.hero#hero` | overview 截图做背景；H1「Zbox」+ 右侧框外 `span.hero-chip`「v0.4」；`.hero-cta` 品牌橙主按钮 + `.hero-meta`「Windows 10 / 11 · x64」 |
| 2 | 混乱→格子→整理→Make It Yours | `#pin-main > #stage-main` | 主舞台 pin（720% 滚动）；`#wall-messy` 真实混乱桌面照片淡出为 `#wall-clean` 壁纸；`#g1..g4` 四个格子；`.fly` 飞行芯片 |
| 3 | **快速上手教程**（pin 舞台） | `#sec-how > #stage-how` | `.film-how` 取景框五帧交叉淡入（menu-newbox → newbox-blank → menu-folderbox → pick-folder-dialog → grid-folder-mapping）；下方 `#how-strip` 录屏条：newbox-flow.mp4（静音循环，rm 下不自动播放）+ explorer-context-menu 侧注；无导航项，scrollspy 归属「功能」 |
| 4 | 双击显隐 | `#pin-clean > #stage-clean` | `.r1/.r2` 涟漪；格子+面板消失再归来；`#panel-clean` 内是**真实时钟与当月日历**（JS 生成）；DOM 面板 tab 条为 4 个（含视频解析）；结尾文案只留「格子、面板、文件，都在。」 |
| 5 | **截图**（pin 舞台） | `#sec-shot > #stage-shot` | `.film-shot` 16:9 取景框四帧交叉淡入：shot-overlay → shot-annotated → shot-pin → shot-long |
| 6 | 日历待办 | `#sec-cal` | kick 为「工作空间」；panel-calendar-todo / panel-todo（359×476，4 tab）真实截图 + `.facts` 功能点 |
| 7 | **多端传输（高潮 · 三端）** | `#pin-transfer > #stage-tr` | `#phone-tr` 手机框内四张**鸿蒙**真实截图交叉淡入（`.ps-1..4` = harmony-home / harmony-receive / harmony-history / harmony-send，1280×2832）；`#tpanel` DOM 传输面板（设备 Mate 90 Pro）；`#fly-vac2`/`#fly-img2` 双向飞行；`#recv` DOM 接收弹窗；`.corner-note` LocalSend 角标 |
| 8 | **视频解析**（pin 舞台） | `#sec-video > #stage-video` | `.film-video` 竖向取景框四帧交叉淡入：video-gate → video-parsed → video-downloading → video-done |
| 9 | 完整工作空间 | `#pin-space > #stage-space` | overview 大图（contain 不裁切）+ `.ws-phone`（保持 Android mobile-transfers，与传输幕的鸿蒙错开平台） |
| 10 | v0.4 标识 | `#sec-v03`（id 沿用未改） | 「Zbox 0.4」+ `.v03-mark` Windows↔Android↔HarmonyOS + `.v03-shots` 三张传输特写（359×476） |
| 11 | 下载 | `#download` | `.dl-grid` **三卡**（Windows / Android / HarmonyOS 免签名调试包）+ `.gh-row` GitHub 轻入口；`.dl-card .note` 带 `flex: 1 1 auto` 让三卡按钮底部对齐 |
| 12 | 页脚 | `.footer` | 品牌 + `.f-links` + `.fine` 声明（已改 v0.4）+ `.icp` 备案号 |

## 四、下载链接（改这里，一处生效）

`js/app.js` 顶部四个常量 + `data-dl` 接线（自动补 target/rel）：

```js
var WINDOWS_DOWNLOAD_URL = ".../releases/download/v0.4/zbox-Setup-v0.4-x64.exe";
var MOBILE_DOWNLOAD_URL  = ".../releases/download/v0.4/zbox-Android-v0.4.apk";             // APK 直链
var HARMONY_DOWNLOAD_URL = ".../releases/download/v0.4/zbox-HarmonyOS-v0.4-unsigned.hap";  // 免签名调试包
var GITHUB_URL           = "https://github.com/evachxji/Zbox";
```

HTML 里写 `data-dl="windows|android|harmony|github"` 即可被接线。注意：页脚「Releases」文字链是
**裸链接**指向 Releases 页面（不能用 data-dl="android"，否则会变成直接下载 APK）。
v0.4 release 三个资产名已在 GitHub 核实；改版本时先核对 release 实际资产名再改常量。

## 五、改代码时的关键约定（踩过的坑都在这）

1. **会被 GSAP 动画的元素不要写 CSS transform**（会被 GSAP 接管覆盖）。需要预置位移用
   `gsap.set(el,{xPercent/yPercent})`。历史教训：`#recv` 弹窗、`.map-win/.map-grid`、所有 `.cap`。
2. **`.cap` 文案**：CSS 默认隐藏；JS 里 `gsap.set(".cap",{yPercent:-50})` 负责居中，
   `capIn(tl,id,t)` / `capOut(tl,id,t)` 进出场；每个舞台的**最后一幕文案必须带 `.cap-final`**
   （reduced-motion / 无 JS 时只有它可见）。
3. **`.fly` 飞行芯片**：`style="left/top"` 写起点（舞台百分比），`data-x1/y1/x2/y2` 写终点，
   `data-target="#落点行id"`。位移是函数式计算的，随窗口刷新自动重算。
4. **字体继承坑**：大字标题里的 `letter-spacing`/`font-weight` 会继承给内部小元素——
   v0.3 标签被 H1 的负字距挤坏过一次，修复方式是显式覆盖（见 `.hero-core h1 .hero-chip`）。
5. **reduced-motion**：`body.rm` 时不创建任何 ScrollTrigger，页面退化为最终态静态长页——
   新增分镜时保证 DOM 默认态即"最终有序态"，JS 只负责"拨回起点"。静态 `.sec` 用 `.reveal`
   接入入场揭示（`html.js .reveal` 默认隐藏，`body.rm` / 无 JS 时强制可见）；教程分镜的
   `<video autoplay>` 在 rm 下由 JS 取消自动播放（`qa("video")` 置 pause）。
   叠放帧舞台（`.film`）：img 绝对叠放、DOM 顺序即叙事顺序，JS 只动 autoAlpha——rm / 无 JS 时
   最后一张帧 + cap-final 即最终态；新增舞台用 `filmTimeline()` 助手（app.js），每幕 `.cap` 进出、
   最后一幕带 `.cap-final`。
6. **图片**：必须本地化、`<img>` 带 width/height；内容截图用 contain/自然流（不裁切），
   只有装饰背景（.wall/.hero-media）允许 cover。
7. **断点**：1100px（下载区 3→2 卡）/ 860px（格子 2×2、手机框缩小、新分镜网格转单列）/ 480px；
   移动端无横向滚动。
8. **手机框**：`.phone .scr` 的 `aspect-ratio: 1080/2400`；鸿蒙截图 1280×2832 与 Android 1080×2400
   比例差 0.4%，`.phone .scr img` 用 `object-fit: contain` 完整呈现不裁切（v0.4 起，原为 cover）。
   换截图仍优先保持同比例。

## 六、事实边界（写文案时不要越界）

- 传输：只说「局域网互传 · 手动启用 · 接收需确认」；协议表述固定为
  「参照 LocalSend v2 · 私有实现（与官方 LocalSend 不互通）」（`#stage-tr` 右下角 `.corner-note`）。
- 视频解析：是「下载」不是在线播放；平台写「YouTube、Bilibili 等」，**不承诺抖音**
  （2026-09 起风控，导 cookie 也解析不了）；清晰度写「最高 4K，视源站实际档位」
  （B 站匿名解析实测封顶 1080P）。
- 鸿蒙端：仅「Zbox 传输」局域网互传配套 App（HarmonyOS NEXT 5.0+），不含格子/日历/待办/视频解析；
  分发为免签名调试包（需开发者设备），不写「扫码即装」。
- **禁止**声称：P2P、端到端加密、云同步、极速传输、零上传等仓库未确认的能力。
- 格子行为的真实事实：文件留在桌面原路径、右键系统菜单、双击桌面显隐、免疫 Win+D、
  文件夹映射实时联动、深/浅/跟随系统主题、图标/列表双视图（v0.4）。

## 七、用户已定版的决策（不要回退）

- Hero 芯片写当前版本号（现为「v0.4」），挂在 H1 右侧框外、不影响 Zbox 居中。
- 导航：功能 / 截图 / 多端互传 / 视频解析（顺序与页面分镜一致，用户指定）。「工作原理」（文件夹映射）与
  「主题条」分镜已按用户要求整段删除，**不要加回**——相关 DOM、JS 时间线、CSS
  （`.map-*`/`.win*`/`.new-file`/`.theme-grid`）均已移除；GitHub 圆形图标按钮（`.nav-gh`）+ 下载按钮不动；
  **没有**「开源」文字链（用户让删的）。
- 导航当前分镜的 tab 有选中态（品牌橙文字 + 下划线，`.on` class）：app.js 内置 scrollspy 驱动
  （scroll 监听 + rAF 节流，判定线 = 视口 35% 高度；不依赖 GSAP，reduced-motion 下照常工作）。
- 双击显隐幕结尾文案只留「格子、面板、文件，都在。」——「Win+D 也吹不散」已按用户要求删掉
  （产品仍免疫 Win+D，只是不上文案）。
- 教程 / 截图 / 视频解析三个分镜均为 pin 滚动演示舞台（`.film` 叠放帧交叉淡入，2026-10-12
  用户要求与其他模块节奏一致）；`shot-toolbar-light.png` 不再上页（文件留 assets）；
  文件夹映射作为产品事实仍然存在（见第六节），页面经教程舞台的「新建文件夹格子」一幕呈现。
- 页脚备案号「浙ICP备2024095561号-2」（`.icp`，链接 beian.miit.gov.cn）。
- `grid-context-menu.png` 区块与素材已按用户要求删除，**不要加回**。
- `transfer-pc-received.png`（359×476，v0.4 独立置顶弹窗）在 `#sec-v03` 第三张卡片位。
- Android 下载走 APK 直链；鸿蒙走 hap 直链并标注「免签名调试包 · 需开发者设备」（上方常量）。
- 页脚保留「界面截图为真实运行画面；整理与传输过程为界面演示」的诚实声明。
- 传输幕手机框展示鸿蒙端（Mate 90 Pro 四张实拍）；工作空间幕 `.ws-phone` 保持 Android 图，两幕平台错开。
- v0.4 P1 格子特写（grid-list-view / grid-collapsed / grid-renaming /
  grid-folder-mapping / explorer-context-menu）中，grid-folder-mapping 与 explorer-context-menu
  已随教程分镜上页；其余三张未上页，存于 `C:\Users\yechen\Desktop\photo_task\zbox-v04-assets`。
- 鸿蒙四张系 DevEco 模拟器拍摄：harmony-home / harmony-history 设备卡副标题带模拟器网关 IP 小字
  （如实登记于素材 manifest；官网展示尺寸下不可辨）。
