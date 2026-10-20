# zbox 性能优化最终报告

> 审计与优化日期：2026-10-20　　对应建议书：`docs/performance-optimization-plan.md`
> 测量环境：Windows 11 Pro 10.0.26200 / Intel Core i9-14900HX（24 核）/ 32GB / Python 3.12.8 / PySide6 6.8.3
> 测量工具：全部在 `perf-audit/`（零侵入，不改业务代码）；原始数据见 `perf-audit/results/`
> 回归测试基线：优化前 **211 用例全绿（14.44s）**；优化后 **248 用例全绿**（新增 12 例回归测试）

---

## 一、总体结果

| 指标 | 优化前 | 优化后 | 变化 |
|---|---|---|---|
| **冷启动 → 可交互**（中位，5 次） | **6348 ms** | **≈1013 ms** | **−84%** |
| 冷启动 → 可交互（首轮，含磁盘缓存冷） | — | 1965 ms | — |
| 启动期工作集 | 202.9 MB | **≈161 MB** | **−21%** |
| 启动期私有内存 | 133.5 MB | **≈84 MB** | **−37%** |
| `BoxManager()` 构造 | 3999 ms | **≈180 ms** | **−96%** |
| `_baked_icon` 累计 | 4014 ms / 48 次 | **≈180 ms / 45 次** | **−96%** |
| 传输服务占首帧前时间 | 1269 ms | **0 ms**（后台） | **−100%** |
| 调试日志写盘 | 2.00 行/秒、126 B/秒 | **0 行/秒、0 B/秒** | **−100%** |
| 截图遮罩每帧全桌面合成 | 3 次 | **1 次** | **−67%** |
| 跑马灯渲染 | 0.604 ms/帧 | **0.270 ms/帧** | **−55%（2.24×）** |
| 长图帧匹配 | 122.4 ms / 18 组 | **60.4 ms** | **−51%（2.03×）** |
| 区域亮度采样 | 逐像素 `img.pixel()` | **字节批量读** | **7.4×** |
| 空闲 CPU（10 分钟长跑稳态，单核%） | 1.6~1.8% | **1.13~1.30%** | **−20~25%** |
| 10 分钟长跑工作集 | 210→219 MB | **154→145 MB** | **−30%** |
| 10 分钟长跑私有内存 | 137→149 MB | **80→81 MB** | **−46%** |
| 10 分钟长跑句柄 / GDI / USER 增长 | −35 / 0 / 0 | **−28 / 0 / 0** | 无泄漏 |

---

## 二、逐项优化明细

> 每项一个独立 commit，可单独回滚。commit 号见括号。

### 2.1 P0-1　壳图标提取移到后台线程（`2ff3e4f`）

**根因**：`BoxWindow._baked_icon` 每次都同步向 shell 要图标，无任何缓存。启动时恢复
3 个格子共 48 次提取，**累计 4014 ms（占启动 65%）**。

**归因实测**（`perf-audit/icon_bench.py`）：

| 类型 | 中位耗时 | 备注 |
|---|---|---|
| 普通文件 `.txt` | **0.006 ms** | 无感 |
| `.lnk`（真实目录） | 6.2 ms | 需经壳解析目标 |
| `.exe`（11.8 MB） | **3022 ms** | 从 PE 资源提取，要扫完整个文件 |
| 同批二次提取 | **2.2 ms** | shell 有缓存，但 zbox 每次启动都是「第一次」 |

**改法**：
* 图标提取**按类型分流**：`.lnk`/`.exe`/`.dll`/… 走后台线程（纯 ctypes：`IShellLinkW`
  解析 .lnk 目标 → `ExtractIconExW` → `DrawIconEx` 画成 `QImage`），主线程先给占位
  图标，取到后回填；普通文件 / 目录 / `.url` 仍走主线程同步取（0.006 ms，渲染路径
  与原先完全一致，像素不变）。
* 进程内图标缓存 `(path, is_dir, size, dpr) → QIcon`，同一文件不再重复问壳。

**踩过的两个坑（已写进 AGENTS.md）**：
1. **不能把 `QFileIconProvider` 放后台线程** —— 它的图标引擎挂在**全局 QPixmapCache**
   （带 mutex）上，后台取图标时主线程的 resize/paint 也要用同一把锁，实测把启动
   从 2.0 s 劣化到 **5.4 s**（首帧被拖到 5.6 s）。纯 ctypes 路线完全不碰 Qt 缓存。
2. **不能用 `SHGetFileInfoW`/`ExtractIconExW` 直接取 `.lnk`** —— 它们返回「快捷方式」
   默认图标，不解析目标（实测 LocalSend.lnk 取到白底蓝箭头，而正确答案是目标程序
   的青绿 logo）。必须先用 `IShellLinkW` 解析目标路径。

**验证**：新路线与原路线**逐像素一致**（`verify_icons.py`，30 个文件全部一致）；
端到端截图目检 42 个快捷方式全部显示各自的目标程序图标
（`perf-audit/results/box-0-入口.png`）。

### 2.2 P0-2　传输服务改后台启动（`bb4649f`）

**根因**：`TransferWidget.__init__` 末尾同步调 `enable_service()`，在 GUI 线程里
bind + listen TCP 53327 —— Windows 首次绑定新端口会触发防火墙规则创建，
**实测 `TransferServer.__init__` 一项就占 1263 ms**（占启动 21%）。

**改法**：整个 bind 过程放后台线程，结果经 `sig_service_started(bool, server, discovery)`
回主线程：成功才接管服务对象、隐藏门禁层、写配置；失败（端口被占）在**主线程**切
「不可用」形态并把 `transfer_enabled` 写回 false。

**竞态处理**：启动期间用户关掉传输 → 置 `_stop_requested`，`_on_service_started` 见到
就立刻把起来的服务停掉；`service_enabled()` 把「正在启动」也算已启用（否则设置窗
勾选与配置不一致）。

**验证**（`perf-audit/verify_transfer.py`，三场景全过）：端口 1.2 s 后真的在监听 /
退出后端口被释放 / 端口被占时配置正确写回 false。
（测试时发现 `TransferServer.allow_reuse_address = True`，普通 `SO_REUSEADDR` 的
占用挡不住它，要用 `SO_EXCLUSIVEADDRUSE` 才能真正触发「端口被占」。）

### 2.3 P0-4　组件下载加互斥与中断（`8d1035d`）

**根因（正确性缺陷）**：视频组件准备被快速开关时会起两条下载线程，两条线程写
**同一个**临时文件（`tools\.dl_partial` 与 `<目标>.new` 都是固定名）→ 互相覆盖 /
读到半截数据 → **可能装出损坏的 yt-dlp.exe / ffmpeg.exe**（功能全废）。

**改法**：
* 下载临时文件名唯一化（`_uniq_tmp`：进程 + 线程后缀），并发下载互不干扰；
  `uninstall_tools` 相应按前缀 glob 清理带后缀的残留。
* `set_enabled(True)` 时若已有下载在跑则不再起第二条线程（`_prep_running` 标志）。
* `set_enabled(False)` 置 `_prep_cancel`，正在下载的组件**中断**（用户确认的语义）：
  `_prep_progress` 抛 `_Cancelled`，该异常在 `_try_sources` / `download_ytdlp` /
  `ensure_tools` 里逐层穿透 —— 不被当成「这个源失败，换下一个源」。

**新增回归测试**：`tests/test_video_dl_concurrency.py`（5 例）。

### 2.4 P0-5　下载异常时杀掉子进程（`8805131`）

**根因**：`Download.start()` 的异常分支只把 `self._proc` 置 None 就返回，yt-dlp 子进程
于是**继续跑着下载并写文件** —— 孤儿进程：占 CPU 与带宽、输出目录留下半成品，
程序退出时也再也终止不了它。

**改法**：异常分支先 `_kill_tree()`（`taskkill /T /F` 杀整棵进程树，yt-dlp 是
PyInstaller 双进程结构，只杀父进程不够），再置空 `_proc`、清 `.part` 残留。

**新增回归测试**：`tests/test_video_dl_orphan.py`（2 例）。

### 2.5 P1-3　调试日志改内存缓冲（`3674372`）

`_dbg` 原先每次调用都在 UI 线程 append 写文件，而 `_desktop_mode_tick` 每 500 ms 调
一次 → 主线程 2 Hz 的文件打开/关闭；日志超 2 MB 时每次调用还要 read 1 MB + write
1 MB 做截断。

改为写内存环形缓冲（`deque(maxlen=2000)`），进程退出时一次性落盘。
**实测写盘 2.00 行/秒、126 字节/秒 → 0 行/秒、0 字节/秒。**

代价：崩溃时缓冲区内容会丢。崩溃现场的关键信息另有两路兜底且都是即时落盘 ——
`debug_due.log`（Python 未捕获异常）与 `crash_native.log`（Qt/C++ 原生崩溃）。

### 2.6 P1-4　`build_qss` 带缓存（`3cfe26e`）

`build_qss` 的输出完全由 `(key, cn_font, num_font, scale, icon_dir)` 决定，而这五个
参数在进程生命周期内基本不变；原实现每次调用都要对 ~19.7 KB 的 QSS 做 **244 处 px
正则替换**（逐个 Python lambda 回调），且函数体里的 `import re` 每次都执行一遍。

改为 `lru_cache` 缓存实际计算；两个正则都提到模块级。
**验证：两套主题 × 4 档缩放（1.0/1.25/1.5/2.0）与原实现逐字节比对，全部一致；
50 次调用降到 0.01 ms。**

### 2.7 P1-5　日历选中态定点刷新（`1c61eab`）

`unpolish+polish` 会丢弃控件的样式缓存并**重新解析整份 QSS**，是 Qt6 最贵的样式操作。
日历里两处把它放大了：`_select_day` 点日期时遍历全部 105 个格子（315 次 polish）、
`set_tab` 切页时 4 个按钮无条件全刷。

改为定点刷新：只对「原选中」与「新选中」两格重刷 → **QSS 重解析 315 次降到 6 次**；
`set_tab` 只刷状态真变了的按钮；`set_day` 里 badge 的 QSS 规则是 `#badge[kind="off"]`
这样的 id 选择器、不依赖祖先属性，改为只有 kind 变了才重刷。

**视觉回归**：中英双语 61 场景截图自检 + `compare_shots` 逐像素对比 → 59/61 完全一致，
另 2 处残差经「同代码跑两次」复现，确认为截图 harness 自身的非确定性。

### 2.8 P1-6　面板收起后停掉时钟 tick（`eb951d9`）

面板收起后 `CalendarWidget` 的 1 Hz 时钟仍在跑（每秒 `setText` + `_update_sub`：
重新解析午休/下班配置、3~4 次 i18n 查表、字体度量），看不见时纯属浪费。
`hideEvent` 停、 `showEvent` 恢复。**只停显示用的时钟**，`_sink_timer` 保留 ——
它负责挂桌面带的健康维护与失焦沉底。

### 2.9 P1-7 / P2-14　桌面图标摆位不冻结界面 + 落点快照去 O(N×M)（`f9692b5`）

* `fixup`（释放图标后统一摆位）与 `_place_icons_at`（落放后摆位）原先用
  `time.sleep` 轮询等 Explorer 把新图标加进 ListView —— **最坏分别冻结界面 3 秒与
  1.5 秒**。改用 `QApplication.processEvents(ExcludeUserInputEvents)` 代替纯 sleep
  （绘制与定时器照常跑，但**排除用户输入事件**避免重入），轮询间隔改指数退避。
* `_snapshot_icon_zones` 原先在**每个图标的循环里**调 `os.listdir(桌面)`（系统开
  「隐藏扩展名」时显示名缺后缀必然找不到）→ O(图标数 × 桌面文件数) 的磁盘风暴
  （200 图标 = 4 万次 exists + 200 次 listdir），拖拽起始直接卡住。改为先扫一次建
  「主名 → 全名」映射。

### 2.10 P1-8　目录监听只在路径真变了时才重建（`aedd4d5`）

`_rewatch()` 原先在每次 `refresh()` 里都 `removePaths + addPath` 重建 ——
① 白费一次句柄重建；② **remove 与 add 之间的窗口里到达的变更被永久丢弃**
（Windows 的 `ReadDirectoryChangesW` 缓冲区随 remove 一起丢弃），快速连续复制文件时
列表会少文件（数据正确性问题）。改为只在路径真变了时才重建。

### 2.11 P1-9　远端版本查询推迟到首次打开视频页（`378d123`）

视频功能启用成功后立刻查远端版本（PyPI + GitHub 两次 HTTPS，外加加载 Windows 证书
存储），启动后 2.5 秒内实测占 **4.45% CPU**；内网/离线环境还会挂到 10 秒超时。
改为 `VideoWidget.showEvent` 首次显示时查一次 —— 用户没打开过视频页就完全不联网。

### 2.12 P1-10　截图遮罩预渲染（`2577bfb`）

`ShotOverlay.paintEvent` 每次都先把**所有屏幕**的底图全量画一遍、再 `fillRect` 盖
一层全屏灰罩；选区有效时还要 clip 到选区把整张底图再画一遍。拖拽框选 100+ fps 时
即**每帧 3 次全桌面合成**（4K 双屏 66 MB×3，理论 6.6~13 GB/s 内存带宽）。

改为预渲染「底图 + 灰罩」成一张位图（会话内底图不变，只建一次），paintEvent 只
blit 一次；选区镂空只渲染**选区那么大小**的一块纯底图。

**验证**（`perf-audit/verify_overlay.py`）：同一组合成底图 + 5 种选区（单屏内 / 跨两屏 /
全屏 / 超出边界），新旧算法逐像素比对，**差异均为 0**。

> 顺带记下一个坑：跨屏时源矩形要用**该屏图自身的坐标**（`inter` 是虚拟桌面坐标，
> 要减掉屏幕原点），否则第二块屏会取到错位的源区域。

### 2.13 P1-11　长图帧匹配改用 C 层迭代（`722c500`）

`_find_shift` 是 O(n²/4) 的纯 Python 索引循环（1080 行签名时约 7.3 万次迭代/tick，
实测每 tick 30~60 ms，全在 GUI 线程）。

改为先把整行均值与行内桶各自抽成列表，再用**切片 + `map(operator.sub)` +
`map(abs)`** 求和 —— 迭代由 C 层驱动。

**验证**（`perf-audit/verify_findshift.py`）：18 组（3 种签名长度 × 6 组随机数据，
含「cur 是 prev 下滚 shift 行」的真实滚动形态）逐组比对，位移与灰度差**完全一致**；
**122.4 ms → 60.4 ms，快 2.03 倍。**

### 2.14 P1-12　翻译图层改后台构建（`de707da`）

翻译图层原先在 `paintEvent` 里构建 —— 4K 选区 dpr=2 时一次性分配 132 MB，逐像素
亮度采样（20 段落 20 万次 `img.pixel()` + `QColor` 构造）加逐字符字体度量
（300 字段落 × 25 档，O(n²) 字符串拼接），合计 0.2~1 秒，全在 GUI 线程。

* `translation_render._luminance` 改为一次性把像素读成字节再按步长取
  （ARGB32 每像素 4 字节）→ **4 种区域结果与原实现完全一致，速度 7.4 倍**。
* 图层构建移到后台线程（`QImage` 可跨线程读写，`QPainter` 画 `QImage` 在工作线程同样
  安全），完成后经 `sig_layer_ready` 回主线程回填；`paintEvent` 只负责画已就绪的图层。
* 导出路径先调 `_ensure_tl8n_layer()`：后台还没建好就同步补一次，保证导出一定含译文。

**行为变化**：翻译完成后译文图层是**异步出现**的（此前是第一次重绘时构建）。测试相应适配。

### 2.15 P2-12　跑马灯改用预建色相笔（`49f6053`）

跑马灯每帧要对边框的每一小段（300 px 宽的记录行约 120 段）新建一个
`QColor.fromHsv` + `QPen` —— 20 fps 下**每秒 2400 次**颜色转换与 QPen 分配；
`_sc()` 还要在每次调用时做一遍函数内 `import app` + 缩放计算。

改为按色相档预建一排 `QPen`，每帧只做整数运算 + 数组下标；`_sc` 结果按值缓存。

**实测 0.604 → 0.270 ms/帧（2.24×）**。档位取 360 = 与原实现 `int(frac*360)` 同一套
索引 → **渲染像素与原版逐点相同**（跑马灯场景 `transfer_busy` 截图比对完全一致）。

---

## 三、最终测量数据

### 3.1 启动（`perf-audit/results/final-startup.json`）

| 轮次 | import | QApplication | FloatingPanel | BoxManager | show | **可交互** | 工作集 | 私有 |
|---|---|---|---|---|---|---|---|---|
| 1（磁盘缓存冷） | 1126 ms | 1222 ms | 1744 ms | 1923 ms | 1960 ms | **1965 ms** | 164.1 MB | 85.5 MB |
| 2 | 212 | 318 | 803 | 1042 | 1082 | **1090** | 163.6 | 85.0 |
| 3 | 206 | 310 | 755 | 960 | 1006 | **1013** | 161.7 | 84.2 |
| 4 | 197 | 296 | 664 | 877 | 913 | **919** | 156.6 | 81.1 |
| 5 | 187 | 277 | 665 | 899 | 944 | **951** | 155.9 | 81.1 |
| **中位（2~5）** | 206 | 310 | 755 | 960 | 1006 | **1013** | 161.7 | 84.2 |

对比优化前（5 次中位）：可交互 **6348 ms**、工作集 202.9 MB、私有 133.5 MB。

### 3.2 空闲与长跑（`perf-audit/results/final-runtime.json`）

**长跑 10 分钟（20 s 采样）**：

| 指标 | 优化前 | 优化后 | 说明 |
|---|---|---|---|
| 工作集 前半/后半均值 | 210.2 / 219.2 MB | **153.7 / 145.2 MB** | **−30%** |
| 私有内存 前半/后半均值 | 136.9 / 149.2 MB | **79.6 / 80.5 MB** | **−46%** |
| 工作集增长 | +8.93 MB | **−8.54 MB** | 下降，无泄漏 |
| 私有内存增长 | +12.37 MB | **+0.88 MB** | 10 分钟仅 +0.88 MB |
| 句柄 delta | −35 | **−28** | 无泄漏 |
| GDI / USER delta | 0 | **0** | 无泄漏 |
| 线程数 | 16~30 波动 | **12~23 波动** | 非单调增长 |
| 稳态 CPU（单核%） | 1.6~1.8 | **1.13~1.30** | **−20~25%** |

**空闲 600 s 窗口**：CPU **1.75% 单核**、工作集 135.3 MB、私有 98.3 MB、句柄 1393、线程 23。

> ⚠️ **口径说明**：优化前的「空闲 0.833%」是 **45 s** 短窗口测的（落在启动余热之外的
> 平稳段），与本轮 600 s 窗口**不可直接比**；可比的口径是同为 10 分钟长跑的稳态 CPU
> 序列 —— **1.6~1.8% → 1.13~1.30%（降 20~25%）**。

**结论：长期稳定性无退化（句柄/GDI/USER 零增长、线程非单调、内存几乎不增长），
同时常驻内存与稳态 CPU 都明显下降。**

### 3.3 视觉回归

| 改动 | 验证方式 | 结果 |
|---|---|---|
| P0-1 图标 | `verify_icons.py` 逐像素 + 端到端截图目检 | 30/30 一致；42 个快捷方式均显示目标图标 |
| P1-5 日历 | 中英 61 场景截图自检 + `compare_shots` | 59/61 一致，2 处为 harness 固有噪声 |
| P1-10 遮罩 | `verify_overlay.py` 5 种选区逐像素 | 差异全 0 |
| P1-11 帧匹配 | `verify_findshift.py` 18 组逐组比对 | 位移与灰度差完全一致 |
| P2-12 跑马灯 | 中英 61 场景截图自检 | 60/61 一致，跑马灯场景逐像素相同 |
| P1-12 图层 | `_luminance` 4 种区域逐位比对 | 完全一致 |

---

## 四、修复的既存缺陷（顺带发现）

| 缺陷 | 位置 | 说明 |

| 缺陷 | 位置 | 说明 |
|---|---|---|
| `ctypes.UINT` 不存在 | `boxes.py` `_lnk_target_dir` | 应为 `wintypes.UINT`；Release 调用会抛 `AttributeError` |
| 组件下载临时文件同名 | `video_dl.py` | 见 §2.3 |
| 下载异常不杀子进程 | `video_dl.py` | 见 §2.4 |
| 目录监听重建丢事件 | `boxes.py` `_rewatch` | 见 §2.10 |
| 越界采样行为不一致 | `translation_render._luminance` | 我在优化时引入的偏差（越界坐标从「钳到边界」变成「跳过」）——被新增的防退化测试当场抓到并修正 |

---

## 五、未实施项与原因

| 项 | 原因 |
|---|---|
| **P1-7 的 `enum_icons` 批量化** | 每个桌面图标要 2 次 `WriteProcessMemory` + 2 次**同步** `SendMessageW`（阻塞 Explorer UI 线程）。批量化需改跨进程结构体布局，是易错点；本轮只消除了 GUI 冻结（改 `processEvents`），跨进程调用次数未降。**建议单独立项并配合多图标桌面实测** |
| **P1-11 把抓帧+匹配整体移出 GUI 线程** | 抓帧用 `QScreen.grabWindow`，跨线程调用 `QScreen` 有风险；匹配结果决定拼接位移，搬到工作线程会引入「拼接错位」的正确性风险。本轮只把匹配计算提速 2 倍 |
| **P1-4 的 `setStyleSheet` 作用域收窄** | 从 `QApplication` 改成面板级会改变设置窗 / 格子 / 弹窗的样式作用域（格子窗口不是面板的子控件）→ 需逐窗口核对 QSS 选择器。本轮只做了零风险的 `build_qss` 缓存 |
| **P2-10 四个 tab 惰性构造** | 收益 −223 ms，但 `main.pyw` 与 `app.py` 多处直接访问 `panel.transfer` / `panel.video`，改动面大、风险高。建议在其它项稳定后单独评审 |
| **P2-13 `BoxStore` 拆文件** | 涉及旧版本数据兼容 |
| **引入 numpy 加速长图匹配** | 用户已批准，但经实测 `map` + C 层迭代已拿到 2.03 倍；再引入 numpy 要为**小众功能**给安装包加约 15 MB 依赖，性价比不足，故未引入 |
| **P2-11 弹层统一 `deleteLater`** | 需要逐个核对「动画未完成就删」的时序（`DuePopup` / `TimePickerPopup`） |
| **P2-16 发送线程 180 s 不可中断** | 涉及 `transfer.py` 协议层的 socket 超时调整，需与接收端一起验证 |
| **P3 各项** | 收益小，按建议书优先级未做 |

---

## 六、后续值得继续的事

1. **P1-7 的 `enum_icons` 批量化** —— 唯一还剩的「秒级 GUI 冻结」来源，需在 100+ 图标
   桌面实测后单独立项。
2. **P2-10 四 tab 惰性构造** —— 启动还能再快 200 ms 量级、内存再降几十 MB。
3. **长图抓帧整体移出 GUI 线程** —— 需先解决 `QScreen` 跨线程调用的安全性。
4. **打包版性能对比** —— 本轮全部在源码态测量；`dist/` 下无当前版本产物，需构建一次
   `python build.py` 后对比 exe 版的启动与内存（PyInstaller onedir 与源码的差异）。
5. **长期运行（>1 小时）稳定性** —— 本轮只跑到 10 分钟；建议补一次 2 小时的内存曲线，
   验证 `P2-11` 之外的累积问题。

---

## 七、如何复现

```bat
:: 前置：确保没有 zbox 实例在跑（否则新进程会被 IPC 转发、测量失真）
python perf-audit\probe.py info

:: 冷启动（5 次）
python perf-audit\probe.py startup --runs 5 --out perf-audit\results\<tag>-startup.json

:: 稳态空闲 / 长跑
python perf-audit\probe.py idle --seconds 60 --out perf-audit\results\<tag>-idle.json
python perf-audit\probe.py longrun --seconds 600 --interval 20 --out perf-audit\results\<tag>-longrun.json

:: 启动分阶段归因（最关键的一张表）
python perf-audit\stage_probe.py --out perf-audit\results\<tag>-stage.json

:: 各项专项验证
python perf-audit\verify_icons.py        :: 图标与原路线逐像素一致
python perf-audit\verify_overlay.py      :: 遮罩预渲染与原算法逐像素一致
python perf-audit\verify_findshift.py    :: 帧匹配结果一致 + 加速比
python perf-audit\verify_transfer.py     :: 传输服务三场景
python perf-audit\verify_box_icons.py    :: 格子图标端到端截图

:: 视觉回归（中英各一套）
set ZBOX_SHOT=perf-audit\shots_after && set ZBOX_SHOT_LANG=zh-CN && python main.pyw
python tools/compare_shots.py perf-audit\shots_before perf-audit\shots_after perf-audit\cmp

:: 回归测试
python -m unittest discover -s tests -v
```

**测量注意事项**
* 探针给子进程设 `APPDATA=<临时目录>` 并复制一份真实配置，**不写坏用户数据、不改动
  用户桌面图标状态**；注册表里的桌面右键菜单会随程序启动/退出切换形态（程序本身的
  正常行为）。
* 外部窗口探测曾误判（面板挂到桌面带后是 Progman 的 child，且格子窗口与面板同名同
  标题 `'zbox'`）——最终基线一律以进程内插桩为准。
* 「冷启动」均指**进程冷启动**；Windows 层面的「清空文件缓存后冷启动」需管理员 +
  第三方工具，本轮未做。

---

*本报告的全部数值均可用 §7 的命令复现。标注「实测」的有原始 JSON 佐证；标注
「未实施」「未测量」的条目已在 §5 与建议书 §1.4 中明确标注，未按缺陷定性。*
