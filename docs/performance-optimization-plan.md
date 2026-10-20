# zbox 性能审计与优化建议书

> 审计日期：2026-10-20　　审计对象：`D:\Document\code\zbox`（工作区含未提交的截图翻译相关改动）
> 阶段：本文件为**阶段 1–3 的产出**（基线测量 + 代码审计 + 方案设计）。
> **实施状态**：已于 2026-10-20 经用户审核通过后开始分批实施（P0/P1/P2）。
> 每批的实测结果记录在 `docs/performance-optimization-report.md`；本文件的问题清单与验收标准保持为审计当时的基线。
> 原始测量数据、探针脚本与复现方法见 `perf-audit/`（独立工作区，不污染仓库原有结构）。

---

## 一、执行摘要

### 1.1 技术架构

| 维度 | 现状 |
|---|---|
| 语言 / 框架 | Python 3.12.8 + PySide6 6.8.3（Qt 6），唯一第三方依赖 |
| 进程模型 | 单进程、GUI 线程 + 若干后台线程（`threading.Thread` / `QThread` / 原生宿主子进程） |
| 打包 | PyInstaller 两段式：`main.pyw` → onedir 本体；`setup.pyw` → onefile 安装包（`--noupx`） |
| 运行数据 | `%APPDATA%\zbox\`（config / todos / holidays / boxes + `icons/`） |
| 特色机制 | 面板与桌面格子**挂桌面带**（`SetParent` 到 Progman/WorkerW）；格子靠文件的「隐藏属性」收纳（不搬文件）；格子右键菜单由原生宿主 `zshell_host.exe` 提供 |
| 测试 | `unittest` 211 用例（`tests/`，14.4s 全绿）；`transfer_selftest.py` 16 用例；截图自检 harness（`selfshot.py`，61 场景） |

### 1.2 整体性能风险评估

**结论：zbox 当前不存在「持续增长的内存泄漏」，但存在两处会直接劣化用户体验的启动阻塞，外加一批常驻 CPU 与周期性卡顿。**

| 维度 | 评级 | 实测依据 |
|---|---|---|
| 启动速度 | **高风险** | 冷启动到可交互 **6.35s**（中位），其中 **86% 是可消除的同步阻塞** |
| 空闲内存 | 中风险 | 工作集 **204MB** / 私有 **133MB**（四 tab 一次性全构造） |
| 空闲 CPU | 中风险 | **0.833% 单核**常驻（面板收起后仍不降） |
| UI 流畅度 | 中高风险 | 格子刷新 = 全量重建 + 每条目一次 shell 图标提取，**83.6ms/次** |
| 文件操作性能 | 高风险 | 同上；另有桌面图标位置记忆的跨进程调用风暴（最坏 GUI 线程冻结 3s） |
| 长期稳定性 | 低风险 | 10 分钟长跑采样见 §2.3，句柄/GDI/USER 均无增长；仅发现对象泄漏点（QMenu/QDialog/QTimer 不释放） |

### 1.3 最值得优先解决的三个问题

1. **启动时逐条目向 shell 提取图标，48 次调用耗 4020ms（占启动 65%）**
   `boxes.py:1249` `_baked_icon` 无任何缓存 —— 每次 `refresh()` 都重新问 shell 要图标。
   这是**整个项目最大的单点性能问题**，同时影响启动、格子刷新、视图切换三处。

2. **传输服务在 GUI 线程同步启动，阻塞 1269ms（占启动 21%）**
   `transfer_ui.py:717` `enable_service()` 同步做 `bind`/`listen` 53327 + 组播组播。

3. **四个 tab 在启动时一次性全部构造**（日历 / 待办 / 传输 / 视频解析）
   `app.py:3139-3146` —— 用户可能永远不点其中三个。

### 1.4 证据充分程度

| 结论 | 证据强度 |
|---|---|
| 启动各阶段耗时占比 | **实测**（进程内插桩打点，3 轮重复，抖动 <5%） |
| 图标提取是启动主因 | **实测**（48 次调用累计计时 4020ms，直接归因到 `_baked_icon`） |
| `enable_service` 是第二主因 | **实测**（`enable_service` 累计 1269ms，占 `TransferWidget.__init__` 的 99.8%） |
| 空闲 CPU / 内存 | **实测**（45s 窗口 + 10 分钟长跑采样） |
| 图标提取单次 83.6ms 的**成因**（.lnk 解析 vs shell 繁忙） | **待验证假设** —— 见 §4.1 的两种候选解释，实施前需二选一确认 |
| 桌面图标跨进程风暴的**实际发生频率** | **待验证假设** —— 代码路径确定，但需在多图标桌面上实测 |
| `screenshot.py` / `video_ui.py` 的长时运行表现 | **部分实测**（启动期已采样），稳态需专项压测 |

---

## 二、测试环境与方法

### 2.1 测量环境

| 项 | 值 |
|---|---|
| OS | Windows 11 Pro 10.0.26200（build 26200） |
| CPU | Intel Core i9-14900HX（24 核 / 32 线程，最高 2.2GHz） |
| 内存 | 32GB（34141495296 字节） |
| Python | 3.12.8（`C:\Program Files\Python312\python.exe`） |
| PySide6 | 6.8.3 |
| 工具 | py-spy 0.4.2、`-X importtime`、`unittest`；**未引入 psutil**（用 ctypes 直调 Win32） |
| 数据集 | 真实用户数据的**副本**（6 条待办 / 3 个格子 / 16 个桌面图标 / 42 条目的映射目录 / 1 个空白格子 3 文件 / 1 个失效映射格子） |

### 2.2 方法与口径

* **进程内插桩打点**（`perf-audit/stage_probe.py`）：monkeypatch 关键构造函数与函数，测「进程起点 → import 完成 → QApplication 建好 → 各大对象构造完 → 面板 show() → 事件循环首拍（可交互）」。**不改 `main.pyw` 一行代码**。
* **外部探针**（`perf-audit/probe.py`）：`ctypes` 直调 `GetProcessMemoryInfo` / `GetProcessTimes` / `GetProcessHandleCount` / `Thread32First` 取内存、CPU、句柄、线程数；`EnumWindows` + 桌面带 child 枚举定位挂带后的面板窗口。
* **py-spy 采样**（`perf-audit/flame.py`）：`py-spy record --format raw`，按栈帧聚合。
* **微基准**（`perf-audit/microbench.py`）：100 / 1000 / 10000 条目下的 scandir、stat、图标提取耗时。

⚠️ **口径说明（重要）**
* 本文档所有「冷启动」均指**进程冷启动**（进程从创建到可交互）。Windows 层面的「清空文件缓存后冷启动」需要管理员 + 第三方工具，本轮**未做**，故数值不可与「重启电脑后首次启动」直接比较。
* 测量时 `APPDATA` 指向临时目录并**复制一份真实配置**（`perf-audit/probe.py::_seed_appdata`），因此**不写坏用户数据、不改动用户桌面图标状态**；仅注册表里的桌面右键菜单会随程序启动/退出切换形态（程序本身的正常行为）。
* 外部窗口探测**曾误判**：面板挂到桌面带后是 Progman 的 child，且格子窗口与面板同名同标题（`'zbox'`），`EnumWindows` 会先撞上格子窗口、测出偏小的数（978ms vs 实测 6185ms）。最终基线一律以进程内插桩为准。

### 2.3 基线数据

#### 冷启动（5 次，`perf-audit/results/baseline-startup.json`）

| 轮次 | import | QApplication | FloatingPanel | BoxManager | show | **可交互** | 工作集 | 私有 |
|---|---|---|---|---|---|---|---|---|
| 1 | 156ms | 492ms | 2338ms | 6525ms | 661ms | **6621ms** | 202.7MB | 133.1MB |
| 2 | 160ms | 532ms | 2396ms | 6647ms | 6735ms | **6749ms** | 209.6MB | 136.9MB |
| 3 | 160ms | 500ms | 2131ms | 6241ms | 6332ms | **6348ms** | 196.6MB | 130.5MB |
| 4 | 153ms | 483ms | 2094ms | 6200ms | 6284ms | **6299ms** | 204.9MB | 133.9MB |
| 5 | 160ms | 504ms | 2115ms | 6183ms | 6272ms | **6286ms** | 202.9MB | 133.5MB |
| **中位** | 160ms | 500ms | 2131ms | 6241ms | 6332ms | **6348ms** | 202.9MB | 133.5MB |

#### 启动内部归因（`perf-audit/results/baseline-stage-detail3.json`）

| 阶段 / 函数 | 次数 | 累计耗时 | 占启动 |
|---|---|---|---|
| `import main` | — | 142ms | 2.3% |
| `QApplication()` | 1 | 286ms | 4.6% |
| `FloatingPanel()` | 1 | 1552ms | 25% |
| └ `TodoWidget.__init__` | 1 | 176ms | 2.8% |
| └ `CalendarWidget.__init__` | 1 | 34ms | 0.5% |
| └ `apply_theme` | 1 | 21ms | 0.3% |
| └ `VideoWidget.__init__` | 1 | 13ms | 0.2% |
| **`BoxManager()`** | **1** | **3999ms** | **65%** |
| └ `BoxWindow.__init__` | 3 | 4037ms | — |
| └ `BoxWindow.refresh` | 4 | 4030ms | — |
| └ **`_baked_icon`** | **48** | **4014ms** | **65%** |
| **⟳ `TransferWidget.__init__`** | 1 | 1272ms | 21% |
| └ **`enable_service`** | **1** | **1269ms** | **21%** |
| `panel.show()` | 1 | 74ms | 1.2% |
| 事件循环首拍（可交互） | — | **6185ms** | 100% |

#### import 开销（`perf-audit/results/baseline-imports.json`）

`import main` 累计 199.69ms（self 19.7ms）：`PySide6.QtCore` 77ms、`app` 61ms、`shiboken6` 60ms（其中 `shibokensupport.signature.loader` 37ms）、`calendar_data` 24.7ms（几乎全是 `urllib.request` 24ms）。**import 本身不是瓶颈**，无需做懒加载改造。

#### 稳态空闲（45s 窗口，`perf-audit/results/baseline-idle.json`）

| 指标 | 值 |
|---|---|
| CPU（单核百分比） | **0.833%**（45s 墙钟消耗 0.375s CPU 时间） |
| 工作集 / 私有内存 | 203.99MB / 133.45MB |
| 峰值工作集 | 211.7MB |
| 句柄数 | 1448 |
| 线程数 | 21 |

#### 文件操作微基准（`perf-audit/results/baseline-microbench.json`）

| 条目数 | `scandir`+`stat`（每条目） | `listdir`+`isdir` | 图标提取（热缓存） |
|---|---|---|---|
| 100 | 0.09ms/条目 | 0.35ms/条目 | 0.417ms/条目（首次，冷） |
| 1000 | 0.08ms/条目 | 0.24ms/条目 | **0.012ms/条目** |
| 10000 | 0.09ms/条目 | 0.29ms/条目 | 0.012ms/条目 |

> 目录枚举本身**不是**瓶颈（每条目 0.1ms 量级）。**图标提取才是**，且实际环境比微基准慢 **约 7000 倍**（83.6ms/次 vs 0.012ms/次）—— 说明慢的不是「取图标」这件事本身，而是它与 Explorer 的交互（见 §4.1）。

#### 长跑稳定性（10 分钟 / 15s 采样，`perf-audit/results/baseline-longrun.json`）

| 指标 | 前半段均值 | 后半段均值 | 差值 |
|---|---|---|---|
| 工作集 | 210.23MB | 219.16MB | **+8.93MB** |
| 私有内存 | 136.86MB | 149.23MB | **+12.37MB** |

采样曲线（前 8 个点，节选）：

| t(s) | 工作集 | 私有 | CPU(单核%) | 句柄 | 线程 |
|---|---|---|---|---|---|
| 15 | 202.47MB | 132.95MB | 3.85 | 1475 | 30 |
| 76 | 202.32MB | 132.50MB | 1.79 | 1447 | 18 |
| 137 | 201.76MB | 132.51MB | 1.62 | 1449 | 18 |
| 198 | 201.94MB | 132.57MB | 1.63 | 1448 | 19 |
| **259** | **235.18MB** | **150.06MB** | 1.78 | 1474 | **27** |
| 320 | 234.68MB | 149.16MB | 1.77 | 1447 | 18 |
| 381 | 234.70MB | 149.16MB | 1.70 | 1449 | 18 |
| 442 | 230.93MB | 149.51MB | 1.66 | 1467 | 24 |
| 503 | 203.75MB | 149.22MB | 1.62 | 1443 | 16 |
| 565 | 203.75MB | 149.22MB | 1.54 | 1443 | 16 |

**解读（严格区分「泄漏」与「分配器保留」）**
* **句柄 delta = -35**（下降）、**GDI/USER delta = 0** → **无 Win32 资源泄漏证据**。
* **线程数在 16~30 间波动**（采样点可见 30 → 18 → 19 → 27 → 18 → 24 → 16），**非单调增长** → **无线程堆积证据**。
* 私有内存的 +12.37MB 是**一次阶跃**（在 ~259s 处从 132.5MB 跳到 150MB），**不是持续增长**。工作集随后回落（→203.75MB）而私有内存不降 → 典型的 **Python/PySide6 分配器保留已释放的内存**，按任务要求**不判定为泄漏**。
* 阶跃时刻伴随**线程数 +8**（19→27）与一次 `holiday update ok` 事件 → 与「节假日后台更新完成 → `panel.refresh_holidays()` → 日历重建 105 个 DayCell」高度吻合（**待验证假设**：需在关闭节假日自动更新时复测确认）。
* 稳态 CPU 约 **1.6~1.8% 单核**（含 2Hz 看门狗 + 1Hz 时钟 + 60s 桌面图标快照 + 传输服务），高于 §2.3 的 0.833%（后者是 45s 空闲窗口、且在节流区间内）。

#### 回归测试基线

`python -m unittest discover -s tests` → **211 用例全绿，14.44s**（本轮所有优化的验收下限）。

---

## 三、应用生命周期与性能调用链

### 3.1 冷启动调用链（实测标注耗时）

```
python main.pyw
 │
 ├─ [0ms] import main ────────────────────────────────── 142ms
 │    └─ PySide6.QtCore 77ms / app 61ms / shiboken6 60ms / calendar_data 25ms
 ├─ [142ms] QApplication(sys.argv) ───────────────────── 286ms
 │    └─ 含 AA_ShareOpenGLContexts → Qt 建 OpenGL proxy 上下文
 ├─ [484ms] Config / HolidayStore / TodoStore ────────── 3ms
 ├─ [531ms] FloatingPanel(...) ──────────────────────── 1552ms
 │    ├─ CalendarWidget(...)                             34ms  (105 个 DayCell + 420 次 polish)
 │    ├─ TodoWidget(...) → rebuild()                    176ms  (6 行 widget + 2 遍行高测量)
 │    ├─ TransferWidget(...) → enable_service()        1272ms  ★ 端口 bind + 组播 announce
 │    ├─ VideoWidget(...)                               13ms
 │    ├─ apply_theme() → build_qss + 全应用 setStyleSheet 21ms
 │    └─ _ensure_band() ×7                              36ms  (SetParent 挂桌面带)
 ├─ [2084ms] BoxManager(...) ────────────────────────── 3999ms  ★ 恢复 3 个格子
 │    ├─ restore() → BoxWindow.__init__ ×3             4037ms
 │    │    └─ refresh() ×4 → _baked_icon ×48           4014ms  ★ 向 shell 逐条目取图标
 │    ├─ BoxWindow.show() ×3                            155ms
 │    ├─ hide_icons()                                    21ms  (SetFileAttributes + SHChangeNotify)
 │    └─ _restore_desktop_icons()                        6ms  (跨进程枚举桌面图标)
 ├─ [6084ms] panel.show() ────────────────────────────── 74ms
 └─ [6185ms] qapp.exec() 首拍 → 【可交互】★
```

### 3.2 稳态运行期

| 任务 | 周期 | 载体 | 代价 |
|---|---|---|---|
| 日历时钟 tick | 1s | `app.py:537` `QTimer(1000)` | `setText` + `_update_sub()`（重新解析倒计时配置 + 3~4 次 `t()` + 字体度量） |
| 桌面层级看门狗 | 500ms | `app.py:3181` `QTimer(500)` | `FindWindowW('Progman')` + 可能的 `SetParent` + **`_dbg` 同步磁盘写**（run.cmd 默认 `ZBOX_DEBUG=1`） |
| 跨天/主题复查 | 30s | `app.py:3160` `QTimer(30000)` | 读注册表判断 AUTO 主题 |
| 桌面图标位置快照 | 60s | `boxes.py:3578` `QTimer(60000)` | **跨进程全量枚举桌面图标（6N 次调用）+ 全量 `boxes.json` 写盘** |
| 盒子目录监听 | 事件驱动 + 300ms 去抖 | `boxes.py:1211` `QFileSystemWatcher` | 每次事件 → **全量 `refresh()`（含逐条目取图标）** |
| 桌面双击钩子 | 100Hz 轮询 | `boxes.py:3232` | `GetAsyncKeyState`；按下时才做跨进程命中测试 |
| 传输服务 | 常驻 | `transfer.py` | HTTP 线程 + 组播发现线程 |
| 视频组件联网 | 启动即触发 | `video_ui.py:1173` | 查 PyPI + GitHub 两次 HTTPS（含 `ssl.load_default_certs`） |

### 3.3 可能存在的重复工作

* **同一图标被反复提取**：4 次 `refresh()` × 12 条目 = 48 次 `_baked_icon`，而实际只有 12 个不同路径 → **约 4 倍重复**。
* **QSS 全量重算**：`build_qss()` 每次调用都对 ~19.7KB 的 QSS 做 244 处 px 正则替换，无任何结果缓存（`themes.py:719-734`）。
* **`QApplication.setStyleSheet` 是全应用级操作**（`app.py:3283`）：一次主题切换 = 全应用数千控件 QSS 重解析 —— 而本应用窗口远多于面板自身（设置窗、格子、弹窗…）。
* **倒计时配置每秒重新解析**：`app.py:640-641` 每秒 `parse_noon_range` / `parse_time_text`。
* **配置写盘放大**：`cfg.set()` 每次调用都全量写 `config.json`；`_save_pos()` 一次拖拽结束写 **2 次**（`app.py:3531-3532`）。

---

## 四、性能问题清单

> 每条给出：位置 / 原理与触发条件 / 证据状态 / 影响 / 严重度 / 修复方案 / 副作用与回归风险 / 预期收益与验证方法。

### 4.1 P0-1　启动期逐条目提取图标，48 次耗 4014ms（占启动 65%）

| 项 | 内容 |
|---|---|
| **位置** | `boxes.py:1249-1256` `_baked_icon()` → `boxes.py:1236-1247` `_icon_for()` → `QFileIconProvider.icon()`；调用链 `BoxManager.restore` (`boxes.py:3601`) → `BoxWindow.__init__` (`boxes.py:1206`) → `BoxWindow.refresh` (`boxes.py:1326`) → `boxes.py:1366` |
| **原理** | `_baked_icon` **没有任何 memo 缓存**：函数体每次都重新向 shell 索要图标。`QFileIconProvider` 返回的 `QIcon` 不驻留内存（AGENTS.md 记载的历史卡顿点），烘焙成位图虽解决了 **paint 路径**的重复生成，但**刷新路径**每次仍要重新提取 N 次。4 次 `refresh()` × 12 条目 = 48 次 |
| **实测** | 48 次累计 **4014ms → 83.6ms/次**。专项归因（`perf-audit/results/icon-bench.json`）见下表 |
| **触发条件** | 每次启动（恢复格子）、每次目录监听事件触发的 `refresh()`、每次切换列表/图标视图（`set_view` 会全量重烘） |
| **证据状态** | **已实测**（归因到 `_baked_icon` 本身精确无误，成因也已定位） |
| **成因归因** | 专项脚本 `perf-audit/icon_bench.py` 测得：<br>• 普通 `.txt`（42 个）：中位 **0.006ms**，总 33.7ms<br>• 真实目录（40 个，以 `.lnk`/`.exe` 为主）：中位 **6.2ms**，P90 **35ms**，**总 6888ms**，**单条最大 5006.7ms**<br>• 最慢条目：`快捷键检测.exe` **5006.7ms**、`暴雪战网.lnk` **1534.1ms**、`炉石传说.lnk` 43ms<br>• **第二轮提取同一批 `.txt` 只要 2.2ms**（shell 内部有缓存）<br>**结论**：① 慢的是 `.lnk`/`.exe` 这类**需解析目标再取目标图标**的类型，不是普通文件；② 存在**秒级长尾**（单条 5 秒）；③ shell 的缓存只在**同一进程生命周期外**无效 —— zbox 每次启动对 shell 而言都是「第一次」，故长尾每次都要重付。④ **memo 缓存的收益被实测证实**（第二轮 6888ms → 2.2ms，差 3000 倍），但它是**进程内**的，**跨启动无效** |
| **影响** | 启动 6.35s → 4.0s；**格子刷新 = 一次 N×83.6ms 的 GUI 线程冻结**（42 条目即 3.5s）；视图切换同样冻结 |
| **严重度** | **P0** —— 证据充分、收益最大、可测量 |
| **修复方案** | ⚠️ **依据实测归因，异步化是主、缓存是辅**（缓存是进程内的，跨启动无效，而秒级长尾每次启动都要重付）。<br>① **【主】提取移出 GUI 线程的关键路径**：先以占位图标建列表，图标按批提取后经信号回主线程替换（`setItemWidget` / `setIcon`）。GUI 线程不再被 5 秒长尾阻塞。<br>② **【辅】memo 缓存**：key = `(绝对路径, is_dir, 图标尺寸, dpr)`，value = 烘焙好的 `QIcon`；失效策略用「文件 mtime + size」或直接依赖 watcher 事件清空。消除**同一次运行内**的重复提取（实测 48 → ~12 次），并让「点刷新」几乎免费（实测第二轮 2.2ms）。<br>③ **【辅】只取可见行**：列表视口通常只显示 10~15 行，按 `visualItemRect` 裁剪可见范围，其余滚动到时再取。<br>④ 提取分批时**给单条设超时/上限**（如单条超过 200ms 即放弃并用通用图标），避免长尾条目把整批拖住。 |
| **副作用与回归风险** | 缓存必须与文件系统变更一致，否则会显示**过期图标**（违反「保护文件数据」约束）→ 缓存失效必须挂在 `QFileSystemWatcher` 事件上；异步替换图标时若用户在替换前已滚动/删除条目，需按 item 有效性校验后再写入；`.lnk` 图标依赖目标文件，目标改了图标也应刷新；**占位图标到真实图标的替换会有视觉跳变** —— 需评估是否可接受（资源管理器也是渐进加载，但用户可能觉得「图标闪一下」） |
| **预期收益** | 启动图标阶段 4014ms → **首帧不再等待**（首帧路径上耗时 ≈ 0，实测目标 ≤ 50ms），图标在随后数秒内陆续补齐；格子刷新不再冻结 GUI 线程 |
| **验证方法** | `python perf-audit/stage_probe.py` 重跑，对比 `boxes:_baked_icon` 累计值；`python perf-audit/probe.py startup --runs 5` 对比 `boxmgr_ms`；`python -m unittest discover -s tests` 全绿；**手工核对图标显示正确、文件改名/换图标后能刷新** |

### 4.2 P0-2　传输服务在 GUI 线程同步启动，阻塞 1269ms（占启动 21%）

| 项 | 内容 |
|---|---|
| **位置** | `transfer_ui.py:717-733` `enable_service()`，由 `TransferWidget.__init__` 末尾 `transfer_ui.py:676` 同步调用 |
| **原理** | `enable_service()` 在 GUI 线程里依次完成：`TransferServer(...)` 构造（**bind + listen TCP 53327**）、`Discovery(...)` 构造、`server.start()`、`discovery.start()`、`announce()`（逐网卡发组播） |
| **实测** | `enable_service` 累计 **1269ms**，占 `TransferWidget.__init__`（1272ms）的 **99.8%**；整个启动的 21% |
| **触发条件** | 配置 `transfer_enabled=true` 时**每次启动**。用户配置里正是 true |
| **证据状态** | **已实测**（同步阻塞 1269ms 无争议）。1269ms 内部的**细分归属未打点**（bind/listen vs 组播 announce vs 防火墙 INPROC 变更）—— 属**待验证假设**，但无论哪一项，**把它挪出 GUI 线程都能消除对首帧的阻塞** |
| **影响** | 启动 +1.27s；首帧出现前界面无响应 |
| **严重度** | **P0** |
| **修复方案** | ① 把 `enable_service()` 挪到后台线程执行，经 `pyqtSignal` 回主线程切换门禁层形态（**注意**：失败时「端口被占」的提示也必须在主线程弹）。<br>② 或用 `QTimer.singleShot(0, ...)` 推迟到事件循环启动后，让**首帧先出来**（可交互时间从 6.35s 降到 ~1.0s，服务在首帧后 ~1s 内就绪）。<br>③ 两者可叠加：先出首帧，再后台起服务 |
| **副作用与回归风险** | 竞态：用户可能在服务就绪前点「启用传输」→ 需幂等（`self.server is not None` 已有守卫，但需处理「正在启动中」的中间态）；端口被占时的门禁层提示时机变化；`shutdown_service()` 与后台启动的竞态（退出时服务线程仍在起 → 需加「正在停止」标志或 join） |
| **预期收益** | 启动 **-1.27s**（首帧前不再阻塞） |
| **验证方法** | 重跑 `stage_probe.py` 看 `transfer:enable_service` 是否退出主线程路径；对比 `interactive_ms`；**手工验证** 端口被占时的提示仍能弹出、退出时端口正常释放（`netstat` 查 53327） |

### 4.3 P1-3　`_dbg` 在主线程做 2Hz 同步磁盘写（run.cmd 默认开启）

| 项 | 内容 |
|---|---|
| **位置** | `app.py:1720-1735` `_dbg()`；调用点 `app.py:3213`（**2Hz 的 `_desktop_mode_tick`**）、`app.py:3345/3363/3369/3391`（hover / 滑出动画） |
| **原理** | `_dbg` 每次调用 = `os.path.exists` + `os.path.getsize` + `open(path,'a')` + `write` + `close`，**全在 UI 线程**。`run.cmd:8` 默认 `set ZBOX_DEBUG=1` → 恒定生效。日志超 2MB 时 `app.py:1728-1730` 还会 `read` 1MB + `write` 1MB 做截断 |
| **实测** | 专项脚本 `perf-audit/dbg_io.py` 在 60s 窗口实测：**+120 行 / +7560 字节 → 2.00 行/秒、126 字节/秒**（与 2Hz 定时器完全吻合）。每次 `_dbg` 调用 = 1 次 `open(append)+write+close` → **约 2 次/秒的文件打开与关闭**。10 分钟 longrun 期间日志文件累积约 3.2 万行（跨多次运行累计）。**常态写盘量很小（126 B/s），不构成带宽压力** |
| **影响** | 常态：2 次/秒 的 `open`/`close` 系统调用 + 元数据更新（量小）。**真正的风险是日志超过 2MB 时**：`app.py:1728-1730` 的截断逻辑每次调用要 `read` 1MB + `write` 1MB → **每 2 秒一次 2MB 级读+写**（约 1MB/s 的 IO 抖动），且发生在 UI 线程 → **这是可感知的周期性卡顿** |
| **严重度** | **P1**（**已按实测下调** —— 常态开销远小于初判，风险集中在 2MB 截断路径） |
| **修复方案** | ① 把 `_dbg` 改成内存环形缓冲（`collections.deque(maxlen=N)`），进程退出时一次性落盘 —— 保留排障能力，消掉主线程 IO **与 2MB 截断的周期性 IO**。<br>② 或用 `logging.handlers.RotatingFileHandler`（自带后台写 + 轮转）。<br>③ 至少把 `tick:` 这类低价值心跳日志降频（10 分钟产生 3 万行，价值极低） |
| **副作用与回归风险** | 崩溃时缓冲区未落盘 → 丢失最后若干条日志。需在 `aboutToQuit` 冲刷，并在 `crash_native.log` / `debug_due.log` 路径保留关键信息。排障时「日志实时性」下降 —— 需在 README/AGENTS 说明 |
| **预期收益** | 消除 2Hz 主线程磁盘写与 2MB 周期性卡顿；空闲 CPU 下降 |
| **验证方法** | 改后观察 `%TEMP%\zbox_debug.log` 内容完整性；对比 `idle.json` 的 `cpu_pct_1core`；长跑期间用 Process Monitor 确认无周期性写盘 |

### 4.4 P1-4　`build_qss` 无缓存 + `QApplication.setStyleSheet` 全应用 QSS 重解析

| 项 | 内容 |
|---|---|
| **位置** | `themes.py:719-734` `build_qss()`；`app.py:3283` `QApplication.instance().setStyleSheet(...)` |
| **原理** | ① `build_qss` 每次调用都对 ~19.7KB 的 QSS 做 **244 处 px 正则替换**（`themes.py:729`，lambda 逐个回调），且 `themes.py:732` 的 `import re` 写在函数体内每次执行；参数完全决定输出却**无任何缓存**。<br>② `QApplication.setStyleSheet` 是**全应用级**操作 —— 会让应用下**所有窗口的所有控件** unpolish+polish 一遍。本应用除面板外还有设置窗、格子窗、弹窗 |
| **实测** | `apply_theme` 累计 21ms（构造期一次）。**主题切换时的全应用重解析成本未单独测量** —— 属**待验证假设**（预估远大于 21ms，因为构造期控件数远少于运行期） |
| **影响** | 主题切换时全应用卡顿；构造期 21ms |
| **严重度** | **P1** |
| **修复方案** | ① `build_qss` 加 `functools.lru_cache`（参数 `(key, cn_font, num_font, scale, icon_dir)` 全是字符串/数字，可哈希）→ 主题切换退化为一次 dict 查找。<br>② `themes.py:732` 的 `import re` 提到模块级（`re` 已被 `sys.modules` 缓存，但每次仍走一遍 `__import__` 路径）。<br>③ `app.py:3283` 改为 `self.setStyleSheet(...)`（面板自身）而非 `QApplication.instance()` —— 但需确认设置窗/格子是否依赖应用级 QSS（**这是主要风险点**） |
| **副作用与回归风险** | ③ 若有其它窗口依赖应用级 QSS，改成窗口级会导致它们样式丢失 —— 需逐一核对 `themes.py` 里选择器的作用域。① 缓存键必须包含全部影响输出的参数（尤其 `scale` 与 `icon_dir`） |
| **预期收益** | 主题切换从「全应用 QSS 重解析」降到「面板级」；构造期 -15ms |
| **验证方法** | 改后**逐屏截图比对**（`ZBOX_SHOT` 自检，中英各一套）确认样式无回归；测主题切换耗时前后对比 |

### 4.5 P1-5　`DayCell.set_day` 无条件 4 次 polish，QSS 重解析风暴

| 项 | 内容 |
|---|---|
| **位置** | `app.py:369-371`（`for w in (self, self.num, self.sub, self.badge): w.style().unpolish(w); w.style().polish(w)`） |
| **原理** | `unpolish+polish` 会丢弃样式缓存并**重新解析整份 QSS**，是 Qt6 最贵的样式操作。`DayCell.set_day` 无条件对 4 个控件各做一次：`refresh()` 建 3 页 = 105 格 = **420 次**；`_apply_dim` 跨月 = **315 次**；`_select_day` 点日期 = **315 次**（只改 1~2 格却遍历全部 105 格） |
| **实测** | `CalendarWidget.refresh` 累计 33ms（含 105 格构建 + 420 次 polish + 105 次农历计算 + 105 次字体测量） |
| **影响** | 跨月滚动 / 点日期时的可见卡顿；日历刷新 33ms |
| **严重度** | **P1** |
| **修复方案** | ① **属性值未变则不 polish**：比较 `w.property('dim')` 与新值，不同才 unpolish/polish。<br>② `num`/`sub`/`badge` 的属性选择器在 QSS 里是 `#dayNum` 这类 objectName 选择器，**不依赖祖先属性** → 只需 polish `self`。<br>③ `_select_day` 改成只刷新**受影响的两格**（旧选中 + 新选中），不走全量遍历 |
| **副作用与回归风险** | QSS 后代选择器（如 `DayCell[dim=true] #dayNum`）确实依赖祖先属性 —— ② 需**逐条核对 `themes.py` 中所有与 dayNum/daySub/badge 相关的选择器**，确认是否有依赖祖先属性的写法（若有则不能省）。这是**必须验证**的一点 |
| **预期收益** | 日历刷新 33ms → **≤ 10ms**；跨月/点选卡顿消失 |
| **验证方法** | 改后跑中英截图自检逐屏比对；测 `CalendarWidget.refresh` 累计值变化 |

### 4.6 P1-6　面板收起后定时器仍在跑（时钟 1Hz + 看门狗 2Hz + 跨天 30s）

| 项 | 内容 |
|---|---|
| **位置** | `app.py:537-539` `_clock`（1000ms）、`app.py:3181-3183` `_sink_timer`（500ms）、`app.py:3160-3162` `_midnight`（30000ms）；`close_panel()` (`app.py:3535`) 只 `hide()`，`hideEvent` (`app.py:3296`) 未 stop 任何定时器 |
| **原理** | 面板收起（最小化按钮 / 桌面右键隐藏）后，三个定时器继续运行。`_desktop_mode_tick` 每次做 `FindWindowW('Progman')` + 可能 `SetParent` + `_dbg` 磁盘写（§4.3）；`_clock` 每次做 `setText` + `_update_sub()`（重新解析倒计时配置 + 3~4 次 `t()` + 字体度量） |
| **实测** | 空闲 CPU **0.833% 单核**（面板**可见**状态下测得；收起态更高，未单独测量 —— **待验证**） |
| **影响** | 收起状态下 CPU 占用不降反升 |
| **严重度** | **P1** |
| **修复方案** | `hideEvent` 里 stop `_clock`/`_sink_timer`/`_midnight`，`showEvent` 里 restart。⚠️ **注意**：`_sink_timer` 负责挂带健康维护，停掉可能让格子沉底 —— 需确认 `_ensure_band` 的补挂职责（`boxes.py` 有独立的补挂逻辑，`app.py:3203` 的 tick 是双保险）。**保守做法**：只停 `_clock`（纯显示），保留 `_sink_timer` |
| **副作用与回归风险** | 停 `_sink_timer` 可能影响「面板挂带健康」与「失焦沉底」行为 —— 需实测面板隐藏后再显示是否仍在正确层级 |
| **预期收益** | 收起态 CPU 显著下降 |
| **验证方法** | 隐藏面板后测 `idle` CPU；显示/隐藏来回切换确认层级与挂带正常 |

### 4.7 P1-7　桌面图标位置记忆的跨进程调用风暴 + GUI 线程阻塞轮询

| 项 | 内容 |
|---|---|
| **位置** | `boxes.py:2389-2412` `_DesktopIconLayout.enum_icons()`（每个图标 **6 次跨进程调用**：2×WriteProcessMemory + 2×SendMessageW 同步 + 2×ReadProcessMemory）；`boxes.py:2438-2496` `fixup()`（**3 秒超时 × 100ms 轮询 = 最多 30 次全量枚举**，且 `boxes.py:2456` 在 **GUI 线程 `time.sleep(0.1)`**）；`boxes.py:3754-3776` `_place_icons_at()`（**1.5 秒 × 50ms 轮询**，同样 GUI 线程 sleep）；`boxes.py:3622-3635` `_save_desktop_icons()`（**60s 定时器** → 全量枚举 + 全量 `boxes.json` 写盘） |
| **原理** | `SendMessageW` 是**同步**的，会阻塞到 Explorer UI 线程处理完；Explorer 忙于重排桌面图标时本进程直接被挂住。`fixup` / `_place_icons_at` 用「GUI 线程 sleep 轮询」等待新图标出现（AGENTS.md 记载：Explorer 图标进 ListView 实测有 0~0.6s+ 延迟，必须轮询） |
| **实测** | 本轮数据集（16 个桌面图标）下 `_restore_desktop_icons` 仅 6ms、`enum_icons` 5.5ms —— **规模小，未暴露问题**。真实用户桌面 100~300 图标时：`enum_icons` 单次 6N = 600~1800 次跨进程调用；`fixup` 最坏 30 次全量枚举 = **1.8~5.4 万次跨进程调用** + **GUI 线程冻结 3 秒** |
| **触发条件** | 释放格子图标（`show_icons`）、拖出落到桌面（`overlay_drop`）、每 60s 的周期快照、启动 3s 后的补一次恢复 |
| **证据状态** | **代码路径与复杂度已确证**（静态审计 + 行号）；**实际发生频率与耗时是待验证假设**（需在多图标桌面实测） |
| **影响** | 拖出格子落桌面时 **1.5 秒无响应**；退出程序/隐藏格子时 **3 秒冻结**；每分钟一次顿挫 |
| **严重度** | **P1**（若用户桌面图标多则升 P0） |
| **修复方案** | ① **`time.sleep` 换成事件循环驱动的轮询**（`QTimer` + 状态机），GUI 线程不被冻结 —— 这是最低风险的改法，行为等价。<br>② 轮询改**指数退避**（50→100→200→400ms）以减少枚举次数。<br>③ `enum_icons` 批量化：一次 `WriteProcessMemory` 写整块 `LVITEMW` 数组、`LVM_GETITEMPOSITION` 换用不回的读法。<br>④ `_save_desktop_icons` 在**桌面图标无变动**时跳过（比对上次的枚举结果哈希） |
| **副作用与回归风险** | ① 改为定时器后，轮询期间窗口可能被拖动 → 需保证状态机正确收尾。<br>③ 跨进程结构体布局改动是**易错点**，必须对照 `native/` 与实测验证 |
| **预期收益** | 消除 1.5s / 3s 的 GUI 冻结；60s 周期卡顿减半 |
| **验证方法** | 在 100+ 图标的桌面场景下测 `fixup`/`_place_icons_at` 耗时；确认图标位置仍被正确恢复（**这是数据正确性问题，必须逐项核对**） |

### 4.8 P1-8　`refresh()` 每次重建文件监听（丢失事件窗口）

| 项 | 内容 |
|---|---|
| **位置** | `boxes.py:1455-1462` `_rewatch()`，在 `refresh()` 内无条件调用（`boxes.py:1343`） |
| **原理** | 每次 refresh 都 `removePaths` + `addPath` 重建 `ReadDirectoryChangesW` 句柄。**remove 与 add 之间的窗口里到达的变更被永久丢弃** —— 快速连续复制时列表可能少文件（数据一致性风险） |
| **实测** | 未单独测量（单次 remove+add <1ms） |
| **影响** | 数据正确性（漏文件）+ 轻微性能损耗 |
| **严重度** | **P1**（正确性 > 性能） |
| **修复方案** | `_rewatch()` 只在**被监听路径真的变了**时才重建；否则不动 |
| **副作用与回归风险** | 路径不变时不重建 → 需确认 `QFileSystemWatcher` 在目录被删/重建后仍能正确恢复（失效页切回有效页的路径） |
| **预期收益** | 消除事件丢失窗口；每次 refresh 省一次句柄重建 |
| **验证方法** | 连续复制文件到映射目录，确认列表最终完整；目录删除/重建后 watcher 恢复 |

### 4.9 P1-9　启动即联网查组件版本（含 SSL 证书链加载）

| 项 | 内容 |
|---|---|
| **位置** | `video_ui.py:1173-1183` `_refresh_versions()` → `video_dl.py:287` `latest_version()`（PyPI JSON → GitHub API 兜底）+ `latest_ffmpeg_version()`；触发点 `video_ui.py:1161`（功能启用成功后） |
| **原理** | 配置 `video_enabled=true` 且组件已在本地时，启动路径 `video_ui.py:1081-1082` → `set_enabled(True)` → `_refresh_versions()` → **启动即发起 2~4 个 HTTPS 请求**。每次 `urlopen` 首次要 `ssl.load_default_certs()` 读 Windows 证书存储 |
| **实测** | py-spy 采样：`ssl.load_default_certs` 占 **4.45%** CPU 样本、`urlopen` 4.45%。**该线程不阻塞 GUI**（后台 daemon thread），但占 CPU 与网络 |
| **影响** | 启动后 2.5 秒内的后台 CPU 与网络开销；离线/内网环境下 HTTPS 会挂到 10s 超时 |
| **严重度** | **P1** |
| **修复方案** | ① 版本检查**推迟到用户打开视频 tab 时**再触发（而不是构造期）。<br>② 或给版本查询加「本次会话只查一次 + 结果缓存到 config」的机制，跨启动复用（版本号一天内不会变） |
| **副作用与回归风险** | 推迟后用户首次打开视频页可能多等 ~1s 才看到版本号（当前是构造期查、打开即见）—— 可在打开页时先显示本地版本、后台再补远端版本 |
| **预期收益** | 启动后 2.5s 内的后台 CPU 与网络归零 |
| **验证方法** | 抓包/观察网络连接确认启动阶段无外网请求；对比启动后 5s 的 CPU 曲线 |

### 4.10 P2-10　四个 tab 在启动时一次性全部构造

| 项 | 内容 |
|---|---|
| **位置** | `app.py:3139-3146`（`CalendarWidget` / `TodoWidget` / `TransferWidget` / `VideoWidget`），全部加入 `self.single_stack`（`app.py:3152-3157`） |
| **原理** | `_SlideStack` 是自写的堆叠容器，切 tab 才 `show()`。**用户可能永远不点其中三个**，但三个都在启动时完整构造（含子控件、QSS、信号接线） |
| **实测** | `TodoWidget` 176ms、`CalendarWidget` 34ms、`VideoWidget` 13ms、`TransferWidget` 1272ms（其中 1269 是 P0-2 的服务启动，与构造本身无关）。**三 tab 的纯构造合计 ≈ 223ms** |
| **影响** | 启动 +223ms；内存 +（四个 tab 的控件树） |
| **严重度** | **P2** |
| **修复方案** | 按需惰性构造：`TodoWidget`/`TransferWidget`/`VideoWidget` 在首次 `set_tab` 到该页时才实例化。`CalendarWidget` 保留（首屏就是它） |
| **副作用与回归风险** | ⚠️ **风险偏高**：① 大量代码直接访问 `self.todo` / `self.transfer` / `self.video`（`app.py`、`main.pyw:375/381/385/391` 都在用 `panel.transfer`、`panel.video`）→ 需改成属性惰性访问；② 构造期发生的事（如 `transfer.set_theme`）时机变化；③ `main.pyw` 在 `FloatingPanel(...)` 之后立刻连 `panel.transfer.notify` 与 `panel.video.shutdown` → 需改为属性访问触发惰性构造。**这是本轮风险最高的一项** |
| **预期收益** | 启动 -223ms；内存 -30~60MB（待实测） |
| **验证方法** | 全量测试 + 中英截图自检逐屏比对 + 手工走遍四个 tab |

### 4.11 P2-11　弹层对象建了不删（QMenu / QDialog / QFrame / QTimer）

| 项 | 内容 |
|---|---|
| **位置** | `app.py:1600` `TodoWidget._menu`（QMenu，`exec()` 后不删）、`app.py:1519` `DuePopup`（引用被覆盖）、`app.py:2676` `TimePickerPopup`；`boxes.py:1927` `_build_menu` 的 QMenu、`boxes.py:4021` `_popup_show_icons_menu` 的 QMenu；`boxes.py:3663` `_note_drag_leave_own` 每次新建 `QTimer(self.panel)`；`transfer_ui.py:1827` `_record_menu`、`transfer_ui.py:1182` `_pick_files`；`main.pyw:434` `AboutDialog`；`main.pyw:418-427` `open_settings`（旧 SettingsDialog 仍在 panel 的 children 里） |
| **原理** | 以 `parent=self` 创建的弹层，Qt 会在 parent 析构时回收 —— **不会泄漏出进程**，但会持续增加 parent 的 children 数量、内存单调增长、每次新建都要付 QSS polish 成本 |
| **实测** | 长跑采样（§2.3）未见内存单调增长 —— 因为这些弹层在 10 分钟内未被反复创建。**属结构性泄漏点，未在本次长跑中触发** |
| **严重度** | **P2** |
| **修复方案** | ① `QMenu` 在 `exec()` 返回后 `deleteLater()`（Qt 文档：阻塞式 `exec()` 不会自动删除）。<br>② `QDialog` / `QFrame` 弹层统一 `setAttribute(Qt.WA_DeleteOnClose)`。<br>③ `boxes.py:3663` 的 QTimer 改为**复用单个实例**（`self._unhide_timer` 已有字段但被重新赋值前未复用）。<br>④ `open_settings` 在替换引用时对旧 dlg 调 `deleteLater()` |
| **副作用与回归风险** | ⚠️ `deleteLater()` 与「parent 还在用这个对象」的时序 —— 例如 `DuePopup` 关闭动画未完成就删会被截断，需在动画 `finished` 后再删。`boxes.py:3663` 的 QTimer 复用需注意 `_cancel_unhide` 的语义 |
| **预期收益** | 消除长期运行的对象累积；内存曲线更平 |
| **验证方法** | 反复开关菜单/弹层 100 次后测内存与 children 数量（`len(parent.children())`） |

### 4.12 P2-12　glow 跑马灯 20fps 整卡重绘 + 每帧约 120 次 HSV 转换

| 项 | 内容 |
|---|---|
| **位置** | `glow.py:31-33`（50ms 定时器 = 20fps）、`glow.py:51-53` `_tick`（`self.update()` = **整卡重绘**）、`glow.py:71-76`（每帧逐段 `QColor.fromHsv` + `QPen` + `drawLine`） |
| **原理** | ① `self.update()` 不带 region = 整卡重绘，`super().paintEvent` 会把 QSS 背景整个重画；② 圆角矩形周长按 6px 细分 = 约 120 段，**每帧 120 次 HSV 颜色转换 + 120 次 QPen 分配**，20fps 即每秒 2400 次 |
| **实测** | 未单独打点（仅在传输/视频活动时触发）。**属待验证假设**，但代码路径与复杂度确定 |
| **影响** | 传输中/视频下载时的 CPU 与合成开销；多任务并发时 N 张卡 = N 个 20fps 定时器 |
| **严重度** | **P2** |
| **修复方案** | ① 描边画在**独立的透明叠加子控件**上，`update()` 只碰它，QSS 背景不参与重绘。<br>② 用 `QConicalGradient` 笔刷一次填充整个边框路径，替代逐段 `drawLine`（每帧从 120 次降到 1 次）。<br>③ 或把渐变预渲染成贴图，每帧只做相位偏移 |
| **副作用与回归风险** | ⚠️ 视觉必须**逐像素一致** —— 用 `tools/compare_shots.py` 对比前后截图；渐变实现与逐段 HSV 的色相插值可能有细微差异，需目检三图 report.md |
| **预期收益** | 动画期间 CPU 显著下降 |
| **验证方法** | `tools/compare_shots.py` 前后对比；测动画期间 CPU |

### 4.13 P2-13　`BoxStore.save()` 全量重写 + 60s 桌面图标快照全量枚举

| 项 | 内容 |
|---|---|
| **位置** | `boxes.py:401-407` `BoxStore.save()`（全量 `json.dump`）；触发点 `boxes.py:1452/1523/1559/1836/1880/3911/3814/3635`（折叠/展开/加锁/排序/视图切换/导入/解散**各写一次**）；`boxes.py:3578-3581` 60s 定时器 → `boxes.py:3622-3635` `_save_desktop_icons`（全量枚举桌面图标 + 全量写盘） |
| **原理** | `desktop_icons` 有 100+ 项时 `boxes.json` 达几十 KB，每次点击交互都全量重写 + 落盘（GUI 线程同步） |
| **实测** | 未单独测量（`boxes.json` 当前 2.4KB）。**属待验证假设** |
| **影响** | 每次交互一次同步写盘；每 60s 一次跨进程枚举 + 全量写盘 |
| **严重度** | **P2** |
| **修复方案** | ① `BoxStore.save()` 加**脏标记 + 300ms 去抖合并**（连续操作只落盘一次）。<br>② `desktop_icons` 与盒子记录**分开存储**（两个文件），避免每次交互都重写桌面图标数据 |
| **副作用与回归风险** | 去抖意味着崩溃时可能丢最后一次改动 —— 去抖窗口不宜过大（300ms 内崩溃的损失可接受）。⚠️ 拆分数据文件影响**旧版本兼容**（需保留读旧格式的路径） |
| **预期收益** | 减少写盘频次 |
| **验证方法** | 断电/强杀测试确认数据不丢；对比写盘次数 |

### 4.14 P2-14　`_snapshot_icon_zones` 在循环里 `os.listdir(桌面)` → O(N×M)

| 项 | 内容 |
|---|---|
| **位置** | `boxes.py:3468-3488`，`boxes.py:3481` 在**循环体内**调 `os.listdir(desk)` |
| **原理** | 对每个桌面图标，先 `os.path.exists(p)`；系统开启「隐藏扩展名」时显示名不带后缀 → 必然失败 → **每个图标触发一次全量 `os.listdir(桌面)`** |
| **实测** | 未单独测量。**复杂度 O(N×M) 确证**：N=200 图标 × M=200 文件 = 4 万次 `os.path.exists` + 200 次 `listdir`，**每次拖拽开始都跑一遍**（`boxes.py:820-821`） |
| **影响** | 拖出格子的**起始延迟**（用户感受：按下鼠标后半秒才拖起来） |
| **严重度** | **P2** |
| **修复方案** | 把 `os.listdir(desk)` **提到循环外做一次**，建成 `主名→全名` 映射；用 `os.scandir` 一次遍历同时拿到名字与类型，避免重复 `exists` |
| **副作用与回归风险** | 低。需注意「隐藏扩展名」时的显示名匹配规则（与 `_DesktopIconLayout` 的匹配逻辑保持一致） |
| **预期收益** | 拖拽起始延迟从 O(N×M) 降到 O(N+M) |
| **验证方法** | 在多图标桌面测拖拽起始耗时；验证落点判定（命中桌面文件夹图标 → 落进它）仍正确 |

### 4.15 P3 级问题（低收益，列而不优先实施）

| 编号 | 问题 | 位置 | 说明 |
|---|---|---|---|
| P3-15 | `glow._sc()` 每次调用做函数内 `import app` | `glow.py:15-18` | 20fps × N 卡；改惰性缓存即可（保留循环 import 的安全性） |
| P3-16 | `_save_pos()` 两次 `cfg.set` = 两次全量写盘 | `app.py:3531-3532` | 合并为一次 |
| P3-17 | glow 相位周期注释与实现不符（注释 2.5s，实际 2.0s） | `glow.py:52` | 文档 bug |
| P3-18 | `paintEvent` 异常时 `QPainter` 未 `end()` | `glow.py:59-84` | 正确性隐患（会被吞异常掩盖） |
| P3-19 | `set_tab` 4 个 tab 按钮无条件全 polish | `app.py:3272-3274` | 只改 1 个状态却全刷 |
| P3-20 | `_select_day` 遍历全部 105 格改 1~2 格 | `app.py:726-727` | 315 次 polish（与 P1-5 同源） |
| P3-21 | `_update_sub` 每秒重解析 `off_noon`/`off_evening` + 多次 `t()` | `app.py:640-641` | 1Hz 常驻小开销 |
| P3-22 | 面板隐藏后 `_clock` 仍跑 | `app.py:537` | 与 P1-6 同源，可合并处理 |
| P3-23 | `firewall_blocked()` 未命中时每次启服务都重跑 powershell | `transfer_ui.py:788-801` | 每次启传输服务 ~1~2s 子进程；加会话内缓存 |
| P3-24 | `round_corners`/`round_bar_top` 每次 `setMask` | `app.py:1815-1853`, `3308`, `3388` | 滑出动画每帧一次窗口区域重设 |
| P3-25 | `__init__` 末尾冗余调 `_tick()` | `app.py:543` | 构造期多跑一次 `_update_sub` 全套 |
| P3-26 | `DesktopClickHook` 100Hz 轮询线程 | `boxes.py:3232` | 每次 `GetAsyncKeyState` 很轻，但有 GIL 争抢；可降到 50Hz 或改用低优先级消息钩子（**风险较高，不推荐**） |

### 4.16 P0-4　视频组件并发下载无锁 → 可能装出半截 exe（**正确性 bug**）

| 项 | 内容 |
|---|---|
| **位置** | `video_ui.py:1104-1116` `set_enabled(True)` 每次都起一条 `_prep_work` 线程；`video_ui.py:1119` `set_enabled(False)` 只做 `self._prep_seq += 1` **作废结果，不取消正在跑的线程**；`video_dl.py:182` / `video_dl.py:206` 共用同名临时文件 `tools/.dl_partial` |
| **原理** | 快速「关→开→关→开」→ 两条 `_prep_work` 并发执行 `video_dl.ensure_tools()` → 都写同一个 `tools/yt-dlp.exe` 与同一个 `.dl_partial` → **同名临时文件互相覆盖 + `os.replace` 竞争** → 可能产出半截 exe |
| **实测** | 未实测（**代码路径确定、触发条件明确**）。AGENTS.md 记载 OCR 组件 v2 起改为运行时经 pip 镜像链安装，若 `ensure_tools` 也走类似路径，风险面更大 |
| **影响** | 组件损坏 → 视频解析功能全废，用户需重装 |
| **严重度** | **P0** —— 唯一「无去重 + 有破坏性」的组合 |
| **修复方案** | ① `set_enabled` 加 `_prep_running` 标志，已在跑则不重复起线程。<br>② 加取消事件，让 `set_enabled(False)` 真正中止下载。<br>③ `video_dl.py` 的临时文件名加唯一后缀（pid + 线程 id），`os.replace` 前校验目标。<br>④ `ocr_runtime.py:184-187` 同类问题：**先 `rmtree` 再 `os.replace`**，两步之间被杀会导致「已装好的被删、新组件没装上」→ 改为「先装到临时目录，再原子切换」 |
| **副作用与回归风险** | 取消逻辑要保证不留半成品；`.dl_partial` 改唯一名后，崩溃残留的清理逻辑（`finally`）要跟着改 |
| **预期收益** | 消除组件损坏风险 |
| **验证方法** | 快速反复开关视频功能 20 次 → 校验 `tools/yt-dlp.exe` 与 `ffmpeg.exe` 可执行（跑 `--version`）且哈希完整 |

### 4.17 P0-5　视频子进程异常时不终止 → 孤儿进程继续写文件

| 项 | 内容 |
|---|---|
| **位置** | `video_dl.py:516-519` 异常分支只做 `self._proc = None`，**既不 `terminate()` 也不 `wait()`** |
| **原理** | `progress_cb` / `done_cb` 抛异常时，yt-dlp 子进程继续运行并写入输出目录，直到自然结束 |
| **实测** | 未实测（代码路径确定） |
| **影响** | 孤儿进程占 CPU/网络；输出目录留下半成品文件；退出时 `video.shutdown()` 找不到它，无法终止 |
| **严重度** | **P0**（资源泄漏 + 数据残留） |
| **修复方案** | 异常分支补 `terminate()` → `wait(timeout)` → 必要时 `kill()`；并把 `self._proc` 置空前先记住句柄以便退出时清理 |
| **副作用与回归风险** | 强制 terminate 会中断下载 → 需确保 `.part` 清理路径仍生效（AGENTS.md 记载 `_cleanup_parts` 会清） |
| **预期收益** | 消除孤儿进程与残留文件 |
| **验证方法** | 构造异常场景（如在回调里抛错）后确认无残留 `yt-dlp` 进程 |

### 4.18 P1-10　截图遮罩每次重绘 = 2 次全桌面合成（拖拽时 100+ fps）

| 项 | 内容 |
|---|---|
| **位置** | `screenshot.py:1344-1391` `ShotOverlay.paintEvent`；`:1346-1347` 全屏 `drawPixmap`；`:1364-1367` 选区有效时**再画一遍全屏**；`:1748` 每次 `mouseMoveEvent` 调 `self.update()` |
| **原理** | 遮罩窗尺寸 = 多屏联合矩形。每帧把**所有屏幕**的 QPixmap 全量画一遍，划选时再画第二遍。4K 单屏 33.2MB、双屏 66.4MB → 每帧搬运 66~133MB 像素 |
| **实测** | 未单独打点。**理论量级**：100fps × 66MB = **6.6GB/s 内存带宽** —— 这是截图交互卡顿的首要来源 |
| **影响** | 框选/拖标注时的卡顿；高分辨率多屏更糟 |
| **严重度** | **P1** |
| **修复方案** | ① 把「底图 + 灰罩」**预渲染成一张 QPixmap**（会话开始时一次），`paintEvent` 只 `drawPixmap` 一次 + 画标注。<br>② 选区镂空用 `QRegion` 差集**裁剪**绘制，而非重画全屏。<br>③ 或用 `QWidget::setMask` 表达镂空（但抗锯齿边缘会糙） |
| **副作用与回归风险** | ⚠️ **视觉一致性是硬要求** —— 预渲染后选区边缘的抗锯齿表现可能与现在不同，必须用 `tools/compare_shots.py` 逐像素比对灰罩边缘 |
| **预期收益** | 截图交互帧率大幅提升 |
| **验证方法** | `compare_shots.py` 前后比对；实测框选时的帧率 |

### 4.19 P1-11　截长图每 280ms 在 GUI 线程做全屏抓帧 + 85K 次 Python 迭代

| 项 | 内容 |
|---|---|
| **位置** | `screenshot.py:2513`（280ms 定时器）→ `screenshot.py:2548-2588` `_long_tick`；`:2560` `scr.grabWindow(0).toImage()`；`:2573/2575` `_row_sig`（`bytes(g.bits())` 把整个灰度缓冲拷进 Python bytes）；`:2576` `_find_shift` |
| **原理** | 每 tick 抓整屏 + QPixmap→QImage 转换 ≈ **100MB 缓冲（4K）**；`_find_shift` 是 O(n²) 纯 Python 迭代（n=540 行）→ **约 85,000 次迭代/tick**，实测单 tick 30~60ms |
| **实测** | 未单独打点。**理论量级**：3.57 tick/s × 100MB ≈ **350MB/s** 内存带宽 + 单核 15~20% 占用 |
| **影响** | 长图模式下界面持续卡顿；`LONG_MAX_H=30000` 意味着极端情况要跑几十秒 |
| **严重度** | **P1** |
| **修复方案** | ① `_row_sig` 改用 **numpy 向量化**（项目已有 numpy 依赖？—— `requirements` 仅 PySide6，**numpy 不可用**，见下方风险）。<br>② 或把 `_find_shift` 的粗筛改用 `bytes` 的内置查找/数组库替代纯 Python 双重循环。<br>③ 抓帧改用 Win32 `BitBlt` 只抓**选区区域**（而非整屏）到工作线程。<br>④ 降低抓帧频率（280ms → 400ms）配合滚轮限速同步 |
| **副作用与回归风险** | ⚠️ **numpy 不是项目依赖**（AGENTS.md：唯一依赖是 PySide6）—— 引入 numpy 会增加安装体积（~15MB）与打包复杂度，**需先确认**。若不引入 numpy，只能走 ②③ 的纯 Python / Win32 路线。<br>另：`bytes(g.bits())` 的坑项目已有记载（PySide6 的 `bits()` 直接返回带尺寸的 memoryview，必须先 `bytes()` 转换） |
| **预期收益** | 长图模式卡顿显著缓解 |
| **验证方法** | 长图拼接结果**必须与现状逐像素一致**（拼接错位是功能性回归）；测长图期间的帧率与 CPU |

### 4.20 P1-12　翻译图层在 `paintEvent` 里构建 → GUI 线程冻结 0.2~1 秒

| 项 | 内容 |
|---|---|
| **位置** | `screenshot.py:2345-2361` `_paint_tl8n` → `translation_render.py:82-112` `build_layer`；`translation_render.py:88-90` 分配 ARGB32 层；`:98` `_pixelate`；`:102` `_luminance`（`translation_render.py:45-54` **逐像素 `img.pixel(x,y)`**）；`:106` `fit_font` → `translation_core.py:205-215` 逐字符 `horizontalAdvance` |
| **原理** | `paintEvent` 是**绝不能做重活**的地方（GUI 线程 + 可能在合成线程中被调用）。`build_layer` 里：4K 选区 dpr=2 → **单次 132MB 分配**；`_luminance` 每段落 10,000 次 `QImage.pixel()` 调用（20 段落 = 20 万次）；`fit_font` 逐字符度量 + O(n²) 字符串拼接（300 字段落 × 25 档 ≈ 7500 次度量） |
| **实测** | 未单独打点。**理论量级**：一次翻译图层构建 ≈ 132MB 分配 + 0.2~1s 的 Python 循环 |
| **影响** | 翻译功能首次出图时界面冻结；且每次重绘还要把 132MB 图层缩放绘制一遍 |
| **严重度** | **P1** |
| **修复方案** | ① 把 `build_layer` 移出 `paintEvent`：在 OCR 结果到达后（`sig_tl8n` 的 GUI 阶段）用 `QTimer.singleShot(0, ...)` 或后台线程构建，构建完成再挂上图层。<br>② `_luminance` 改用 `QImage.bits()` + `memoryview` 批量计算（或 `QImage.constBits()` + numpy，**受 P1-11 的 numpy 依赖约束**）。<br>③ 图层缓存：同一选区不重复构建 |
| **副作用与回归风险** | 后台线程构建图层 → QImage 跨线程使用需保证「构造在工作线程、绘制在 GUI 线程」的时序（QImage 本身可跨线程读，但**不可在 GUI 线程仍在用时被释放**）。翻译图层是**新功能**（未提交），改动风险相对可控 |
| **预期收益** | 消除翻译时的 0.2~1s 冻结 |
| **验证方法** | 翻译功能端到端截图对比（马赛克+译文图层必须逐像素一致）；测翻译完成时的界面响应 |

### 4.21 P2 级补充问题（后台任务与截图模块）

| 编号 | 问题 | 位置 | 说明 / 修复要点 |
|---|---|---|---|
| P2-15 | 跨线程信号**全部**依赖隐式 `AutoConnection`，全仓库零处显式 `Qt.QueuedConnection` | `transfer_ui.py` / `video_ui.py` / `screenshot.py` / `doubao_web.py` | 当前依赖 PySide6 为 Python 线程创建的 dummy QThread 自动排队 —— **行为正确但完全靠隐式约定**。⚠️ `transfer.py:712` 把 `self.sig_file_done.emit` 直接当 HTTP 回调赋给 server，将来若改成 lambda 会**在 HTTP 线程里直接跑 UI 代码**。修复：显式 `Qt.QueuedConnection` |
| P2-16 | 传输发送线程在 `prepare-upload` 上阻塞 **180s**，`cancel_event` **无法打断** | `transfer_ui.py:1248` / `:1404`，`transfer.py:737`（注释已明说）、`transfer.py:42` | 用户点「取消」后线程仍挂着最多 180s；期间再点「重试」会**再起一条新线程**，旧线程未 join → 180s 内反复取消+重试可堆积 ~18 条线程。修复：给 socket 设较短超时并让循环检查 `cancel_event`；重试前先 join/标记旧线程 |
| P2-17 | `_animate_bar` 每次调用 new 一个 `QPropertyAnimation` 且不 stop 上一个 | `transfer_ui.py:1851-1864` | 进度 10Hz → 每条活动记录每秒创建 10 个 QObject，新旧动画同时写同一 `bar.value` 互相打架（视觉抖动）。修复：复用同一个动画对象 |
| P2-18 | 防火墙检查在**未命中**时每次启用传输都重跑 | `transfer_ui.py:792`（`_fw_warned` 只在命中时置位）、`sysutil.py:490-497` | `Get-NetFirewallApplicationFilter -All` 要枚举全部应用过滤器，实测 1~3s CPU。修复：改为「已检查过」语义（无论结果都置位） |
| P2-19 | OCR 每次翻译都新起 Python 子进程加载 ONNX 模型 | `ocr_runtime.py:123-144` | 模型不常驻 → 每次翻译付一次模型加载（秒级 + 数百 MB RSS）。修复：模型常驻或至少复用子进程 |
| P2-20 | `doubao_web.make_page()` 每次翻译新建 `QWebEngineView` | `doubao_web.py:348-370` | Chromium 渲染进程反复创建/销毁，可能残留僵尸 renderer 数秒。修复：复用同一个 view |
| P2-21 | 截图 `_WheelGuard` 停止时不 join；`_start_long` 里 `self._ready.wait(2)` 会阻塞 GUI 线程最多 2s | `screenshot.py:797-802`、`:2504` | 实测通常 <1ms，极端情况卡 2s。修复：超时降到 200ms 或改异步 |
| P2-22 | OCR 结果聚类 O(行数²) 在 GUI 线程 | `screenshot.py:2227` → `translation_core.py:116-133` | 200 行 OCR → 4 万次迭代。修复：移出 GUI 线程 |
| P2-23 | 鼠标移动时的 Z 序遍历（每次约 900 次 ctypes 调用） | `screenshot.py:1691-1694` → `:684-701` | 150 个顶层窗口 → 鼠标移动 100 次/秒 = 9 万次/秒 ctypes。修复：窗口列表加 200ms TTL 缓存 |
| P2-24 | 长图预览 `append_chunk` 每次追加都重建整张累加图 | `screenshot.py:562-586` | 累加到 30000 物理像素时单次拷 ~19MB，累计数百 MB~GB 级重复拷贝。修复：增量拼接或只维护缩略图 |

---

## 五、优化优先级

| 优先级 | 编号 | 问题 | 预期收益（实测口径） | 风险 | 工作量 |
|---|---|---|---|---|---|
| **P0** | P0-1 | 启动期图标提取 4014ms | 启动 **-3.6s ~ -3.9s** | 中（缓存失效策略） | 中 |
| **P0** | P0-2 | `enable_service` 同步 1269ms | 启动 **-1.27s** | 中（线程竞态） | 小 |
| **P0** | P0-4 | 视频组件并发下载无锁 → 半截 exe | **正确性**（功能全废） | 中（取消逻辑） | 小 |
| **P0** | P0-5 | 视频子进程异常不终止 → 孤儿进程 | 资源泄漏 + 文件残留 | 低 | 小 |
| **P1** | P1-3 | `_dbg` 2Hz 主线程磁盘写（常态小，**2MB 截断路径重**） | 消除截断期卡顿 | 低 | 小 |
| **P1** | P1-4 | `build_qss` 无缓存 + 全应用 setStyleSheet | 主题切换卡顿 | 中（作用域核对） | 小 |
| **P1** | P1-5 | `DayCell.set_day` 无条件 polish | 日历刷新 33ms → ≤10ms | 中（QSS 选择器依赖） | 小 |
| **P1** | P1-6 | 面板隐藏后定时器不停 | 收起态 CPU 降 | 低~中 | 小 |
| **P1** | P1-7 | 桌面图标跨进程风暴 + GUI 阻塞轮询 | 消除 1.5s/3s 冻结 | 中（跨进程结构体） | 大 |
| **P1** | P1-8 | `_rewatch` 每次重建监听 | 数据正确性 | 低 | 小 |
| **P1** | P1-9 | 启动即联网查组件版本 | 启动后 CPU/网络 | 低 | 小 |
| **P1** | P1-10 | 截图遮罩每次重绘 2 次全桌面合成 | 截图交互卡顿 | 中（视觉一致） | 中 |
| **P1** | P1-11 | 长图抓帧全屏 + 85K 次 Python 迭代（GUI 线程） | 长图模式卡顿 | 中（numpy 依赖取舍） | 中 |
| **P1** | P1-12 | 翻译图层在 `paintEvent` 里构建 | 消除 0.2~1s 冻结 | 中（跨线程图像） | 中 |
| **P2** | P2-10 | 四 tab 全构造 | 启动 -223ms | **高**（跨模块引用多） | 大 |
| **P2** | P2-11 | 弹层对象不释放 | 长期内存 | 中（动画时序） | 中 |
| **P2** | P2-12 | glow 整卡重绘 + 逐段 HSV | 动画期 CPU | 中（视觉一致性） | 中 |
| **P2** | P2-13 | `BoxStore.save` 全量重写 | 写盘频次 | 低~中（兼容性） | 中 |
| **P2** | P2-14 | `_snapshot_icon_zones` O(N×M) | 拖拽起始延迟 | 低 | 小 |
| **P2** | P2-15 ~ P2-24 | 见 §4.21 | 线程堆积 / 正确性 / CPU | 低~中 | 各自小~中 |
| **P3** | P3-15 ~ P3-26 | 见 §4.15 | 小 | 低 | 各自小 |

**排序依据**：先解决「有实测证据 + 收益最大 + 风险可控」的；P1-7 虽收益大但涉及跨进程内存结构，风险与工作量都最高，排在 P1 末位。

---

## 六、优化实施方案

### 6.1 第一批：P0（启动主路径）

**步骤 0（P0-1 的成因归因）—— ✅ 已完成**
专项脚本 `perf-audit/icon_bench.py` 已定位成因（见 §4.1「成因归因」）：
慢的是 `.lnk`/`.exe` 这类需解析目标再取目标图标的类型，且存在**秒级长尾**（单条 5 秒）；
第二轮提取只要 2.2ms → **memo 缓存有效但仅限进程内**，**异步化才是解决启动慢的主手段**。
（`B. 快捷方式 .lnk` 组因 COM 构造 .lnk 失败被跳过 —— 已由 C 组真实目录覆盖，不影响结论。）

**步骤 1（P0-1 图标）**
* 改动文件：`boxes.py`
* ① **【主】异步化**：`BoxWindow` 增加一个图标预取器，用 `QTimer` 在 GUI 线程**分批**提取（每批 1~3 个，单帧预算 <5ms），结果回主线程写入对应 item；列表先用占位图标建好。
  > ⚠️ **Qt 线程约束**：`QFileIconProvider` 不是线程安全的、且依赖 GUI 线程对象 —— **不要**直接丢到工作线程。可行路线：① GUI 线程分批提取（**建议先做这个**：改动小、风险低、已能消除首帧阻塞）；② 改用 Win32 `SHGetFileInfoW` 在工作线程取位图（彻底不阻塞，但要一并迁移 `.url` 的自定义图标逻辑 `boxes.py:1258-1296`，工作量与风险都更高）。
* ② **【辅】memo 缓存**：`self._icon_cache = {}`，key = `(abspath, is_dir, size, dpr)`；命中直接返回。
  * 缓存失效：目录变更事件触发时清空该目录条目的缓存；文件改名/删除由 `refresh()` 的 diff 自然淘汰。
* ③ **【辅】可见性裁剪**：只对 `self.list.visualItemRect(item)` 与视口相交的条目提取；不可见条目留占位图标，滚动到时再取。
* ④ **长尾保护**：单条提取超过阈值（建议 200ms）即放弃该条专用图标、改用通用图标，避免一个坏 `.lnk` 拖住整批。

**步骤 2（P0-2 传输服务）**
* 改动文件：`transfer_ui.py`
* 把 `enable_service()` 的调用从 `__init__` 末尾挪到 `QTimer.singleShot(0, ...)`（先出首帧）或后台线程 + 信号回主线程。
* ⚠️ 「端口被占」的 `_show_gate('occupied')` 必须在 **GUI 线程**执行 → 若走后台线程，需用 `pyqtSignal` 回到主线程切换门禁层。
* ⚠️ `shutdown_service()` 与「正在启动」的竞态 → 加 `_starting` 标志，退出时若在启动中则等待或直接标记取消。

**步骤 3（P1-3 `_dbg`）**
* 改动文件：`app.py`
* `_dbg` 改为内存 `deque(maxlen=2000)` 缓冲 + `aboutToQuit` 冲刷；保留「日志超 2MB 轮转」语义到冲刷时处理。
* `app.py:3213` 的 `tick:` 心跳日志**降频**（如每 30 次记一次）。

**回滚方案**：三个改动均**独立可回滚**（各自单文件、单函数）。P0-1 建议先只做「缓存」部分（不改变线程模型），验证收益后再决定是否做异步化 —— 缓存改动可单独 revert。

### 6.2 第二批：P1

| 项 | 改动文件 | 要点 | 回滚 |
|---|---|---|---|
| P1-4 | `themes.py`, `app.py` | `build_qss` 加 `lru_cache`；`import re` 提到模块级；`setStyleSheet` 作用域核对后再改 | 单文件 revert |
| P1-5 | `app.py` | 属性值未变不 polish；核对 `themes.py` 中 dayNum/daySub/badge 选择器是否依赖祖先属性 | 单函数 revert |
| P1-6 | `app.py` | `hideEvent` stop `_clock`（保守方案，保留 `_sink_timer`） | 单函数 revert |
| P1-7 | `boxes.py` | `time.sleep` 轮询 → `QTimer` 状态机；指数退避 | 单函数 revert；跨进程结构体改动单独提交 |
| P1-8 | `boxes.py` | `_rewatch` 仅在路径变化时重建 | 单函数 revert |
| P1-9 | `video_ui.py` | 版本查询推迟到打开视频 tab；结果缓存 | 单函数 revert |

**测试新增**：
* `tests/test_box_icon_cache.py` —— 验证缓存命中、文件变更后失效、图标内容正确。
* `tests/test_boxes_refresh_watch.py` —— 验证 `_rewatch` 在路径不变时不重建监听、路径变化时正确重建。
* 现有 `tests/test_box_snap.py` / `tests/test_box_title_actions.py` 需保持全绿。

### 6.3 第三批：P2

P2-10（四 tab 惰性构造）**风险最高，建议单独一批、单独评审**：需先盘点 `self.todo` / `self.transfer` / `self.video` 的全部跨模块引用（`app.py`、`main.pyw:375/381/385/391`、`boxes.py`），改为 `@property` 惰性访问。

其余 P2 项按 §4 各自方案实施，逐项独立 revert。

### 6.4 明确**不建议**实施的方向

| 方向 | 不建议的原因 |
|---|---|
| 引入数据库 / 消息队列 / 进程池 | 桌面工具的数据量与并发量远未到需要；增加部署体积与维护成本 |
| 换 UI 框架 / 重写架构 | 当前 PySide6 够用；重写风险远大于收益 |
| 用 `psutil` 等新依赖 | 探针已用 ctypes 直调 Win32 完成，无必要 |
| 引入常驻常线程池 | 现无线程堆积问题（实测 21 线程） |
| 把 `DesktopClickHook` 换成全局钩子 | AGENTS.md 已记载教训：全局钩子会让全系统鼠标卡顿 5~10 秒 |
| 移除视觉特效（glow / 呼吸灯 / 圆角） | 任务明确要求不牺牲体验；应优化实现而非移除效果 |
| 大规模重构 `boxes.py` | 该文件 4051 行、坑位极多；只做**范围明确的小改动** |

---

## 七、性能测试计划

### 7.1 工具与环境

* 探针：`perf-audit/probe.py`（启动/空闲/长跑）、`perf-audit/stage_probe.py`（分阶段）、`perf-audit/flame.py`（py-spy 采样）、`perf-audit/microbench.py`（文件操作微基准）
* 回归：`python -m unittest discover -s tests -v`（211 用例，基线 14.44s）
* 协议自检：`python transfer_selftest.py`（改 `transfer.py` 后必跑）
* 视觉回归：`ZBOX_SHOT=designs/verify-zh python main.pyw` + `ZBOX_SHOT=designs/verify-en python main.pyw`，再用 `python tools/compare_shots.py <before> <after> <报告目录>` 逐像素 diff
* 系统级：Process Monitor（文件/注册表 IO）、Windows 性能计数器（`\Process(zbox)\% Processor Time`、`Working Set - Private`、`Handle Count`、`Thread Count`）

### 7.2 场景与口径

| 场景 | 口径 | 样本量 |
|---|---|---|
| **冷启动** | 进程创建 → 事件循环首拍（可交互）。每次用**空的** APPDATA（首次安装态）与**真实数据副本**各跑 | 各 ≥ 7 次，取中位数与 P90 |
| **热启动** | 紧接着的第二次启动（OS 文件缓存与 .pyc 已热，进程全新） | ≥ 7 次 |
| **首次渲染** | 面板 `show()` 完成时刻（`panel.show() 后` 打点） | 同上 |
| **空闲 CPU** | 稳定后 60s 窗口，CPU 时间增量 / 墙钟 | 3 次 |
| **空闲 CPU（收起态）** | 面板隐藏后 60s 窗口 | 3 次 |
| **典型负载** | 打开四个 tab 各一次、切换视图、展开/折叠格子、触发一次目录刷新 | 手工 + 计时 |
| **压力：多文件** | 映射格子指向 100 / 1,000 / 10,000 条目的目录，各测 `refresh()` 耗时 | 每档 3 次 |
| **压力：多格子** | 6 / 12 个格子同时存在，测启动与刷新 | 每档 3 次 |
| **压力：多桌面图标** | 桌面 100 / 300 个图标，测 `_restore_desktop_icons` / `_save_desktop_icons` / `fixup` | 每档 3 次 |
| **长跑稳定性** | 连续运行 30 分钟，每 30s 采样工作集/私有/句柄/线程/GDI/USER | 1 次；另跑 10 分钟快速版 |
| **动画压力** | 传输进行中 + 3 个视频任务并行，测 CPU 与帧率 | 手工 |

### 7.3 优化前后对比方式

* 每项优化**独立**测量：改一项 → 跑该场景 → 记录 → 再改下一项（避免归因混淆）。
* 结果统一存 `perf-audit/results/<stage>-<item>.json`，用 `baseline-*.json` 做 diff。
* 启动类指标以 `stage_probe.py` 的分阶段打点为主（外部探测不可靠，见 §2.2）。
* **每次改动后必须 `python -m unittest discover -s tests` 全绿**（211 用例为下限）。

### 7.4 结果记录格式

```json
{
  "item": "P0-1 图标缓存+分批提取",
  "before": {"boxmgr_ms": 3999, "baked_icon_ms": 4014, "baked_icon_calls": 48, "interactive_ms": 6185},
  "after":  {"boxmgr_ms": 420,  "baked_icon_ms": 380,  "baked_icon_calls": 12, "interactive_ms": 1900},
  "delta":  {"interactive_ms": "-4285 (-69%)"},
  "tests": "211 passed",
  "shots": "verify-zh / verify-en 无差异"
}
```

---

## 八、量化验收标准

> **区分三类**：`实测` = 本轮已测得；`目标` = 优化后需达成的阈值（**待实施后填入实测值**）；`待验证` = 当前无法测量，附阻塞条件与后续方案。

### 8.1 启动

| 指标 | 当前实测 | 目标 | 验收方法 |
|---|---|---|---|
| 冷启动→可交互（真实数据） | **6348ms**（中位，5 次） | **≤ 2000ms** | `probe.py startup --runs 7` 中位数 |
| 冷启动→可交互（首次安装，空数据） | 未测 | **≤ 1200ms** | 同上，`copy_real=False` |
| `BoxManager()` 构造 | **3999ms** | **≤ 600ms** | `stage_probe.py` 的 `boxmgr_ms` |
| `_baked_icon` 累计 | **4014ms / 48 次** | 首帧路径上 **≤ 50ms**（提取全部移出首帧）；同批次内调用数 **≤ 15 次**（缓存命中） | `stage_probe.py` 的 `boxes:_baked_icon` |
| 单条图标提取长尾 | **5006.7ms**（`快捷键检测.exe`） | **≤ 200ms**（超阈值改用通用图标） | `perf-audit/icon_bench.py` 的 `slowest` |
| 同批二次提取 | **6888ms → 2.2ms**（实测差 3000 倍） | 保持该量级 | `icon_bench.py` 的 D/E 组 |
| `enable_service` 占用首帧前时间 | **1269ms** | **≤ 50ms**（或完全移出主线程路径） | `stage_probe.py` 的 `transfer:enable_service` 与 `interactive_ms` 的差 |
| `import main` | 142ms | 不变（**不追求**） | — |
| `QApplication()` | 286ms | **≤ 200ms**（评估去掉无条件 `AA_ShareOpenGLContexts`） | `stage_probe.py` |

### 8.2 内存与 CPU

| 指标 | 当前实测 | 目标 | 验收方法 |
|---|---|---|---|
| 启动后工作集 | 202.9MB | **≤ 160MB** | `probe.py startup` |
| 启动后私有内存 | 133.5MB | **≤ 110MB** | 同上 |
| 稳态空闲 CPU（面板可见） | **0.833% 单核** | **≤ 0.35%** | `probe.py idle --seconds 60` |
| 稳态空闲 CPU（面板收起） | **未测量** | **≤ 0.15%** | 同上（需先实现隐藏停表） |
| 30 分钟长跑工作集增长 | **10 分钟样本 +8.93MB（一次阶跃，非持续）** | **≤ 5MB 持续增长**（阶跃本身不计） | `probe.py longrun --seconds 1800` |
| 30 分钟长跑句柄增长 | **-35**（无泄漏） | **≤ 20** | 同上 |
| 30 分钟长跑线程增长 | **16~30 波动（非单调）** | **无单调增长** | 同上 |
| 稳态 CPU（长跑期间） | 1.6~1.8% 单核 | **≤ 1.0%** | 同上 |
| GDI / USER 对象增长 | **delta = 0**（10 分钟内无增长） | **≤ 50** | 同上 |

### 8.3 UI 流畅度与文件操作

| 指标 | 当前实测 | 目标 | 验收方法 |
|---|---|---|---|
| 格子 `refresh()`（42 条目） | 隐含 ≈ 42×83.6ms ≈ **3.5s** | **≤ 150ms** | `stage_probe.py` + 专项计时脚本 |
| 图标视图切换重烘（42 条目） | 同量级 | **≤ 150ms** | 同上 |
| 日历 `refresh()` | 33ms | **≤ 10ms** | `stage_probe.py` 的 `app:CalendarWidget.refresh` |
| 跨月滚动（315 次 polish） | 未单独测量 | **≤ 20ms** | 专项计时 |
| `_restore_desktop_icons`（16 图标） | 5.5ms | 基线保持 | `stage_probe.py` |
| `fixup()` GUI 线程冻结（最坏） | 理论 **3s** | **0**（改事件循环驱动） | 100+ 图标桌面实测 |
| `_place_icons_at()` GUI 线程冻结（最坏） | 理论 **1.5s** | **0** | 同上 |
| `_snapshot_icon_zones`（N 图标） | 理论 O(N×M) | **O(N+M)** | 专项计时 + 代码审查 |

### 8.4 稳定性与正确性

| 指标 | 当前 | 目标 |
|---|---|---|
| 回归测试 | 211 用例全绿（14.44s） | **持续全绿**，新增用例 ≥ 6 个 |
| 传输协议自检 | 16 用例 | 全过（改 `transfer.py` 后必跑） |
| 视觉回归（61 场景 × 2 主题） | 基线 | `compare_shots.py` 报告无版式/尺寸/配色差异 |
| 桌面图标位置恢复正确性 | 基线（16 图标） | **逐项核对位置未被改错**（数据正确性硬约束） |
| 格子内容与磁盘一致性 | 基线 | 文件增删改后列表**不漏、不重、不错**（P1-8 的核心验收） |

### 8.5 暂时无法测量的项（阻塞条件 + 后续方案）

| 项 | 阻塞原因 | 后续方案 |
|---|---|---|
| GDI / USER 对象泄漏量 | `GetGuiResources` 需 `PROCESS_QUERY_INFORMATION` 权限，探针以 `PROCESS_QUERY_LIMITED_INFORMATION` 打开时返回 0 | 改用 `PROCESS_ALL_ACCESS`（需管理员）或改用 `NtQueryInformationProcess` |
| 「磁盘冷启动」 | 需管理员 + `RAMMap`/`EmptyStandbyList` 清空文件缓存 | 用 RAMMap Empty File Cache 后测首启；本轮不纳入验收 |
| 打包版（exe）性能 | `dist/` 下无当前版本产物，构建耗时数分钟 | 实施阶段构建一次 `python build.py`，对比源码版与 exe 版的启动/内存 |
| 真实多图标桌面的 `fixup` 耗时 | 当前桌面仅 16 个图标 | 造 100/300 个桌面图标后实测 |
| 触控板/高 DPI 下的真实卡顿 | 需硬件环境 | 125%/150% 缩放下人工验证 |

---

## 九、建议实施顺序与风险

### 9.1 建议顺序

| 批次 | 内容 | 预计收益 | 累计启动时间 |
|---|---|---|---|
| **第一批** | P0-1 图标（异步提取 + 缓存 + 可见性裁剪） | **-3.6s** | 6.35s → **~2.7s** |
| **第一批** | P0-2 传输服务移出首帧前 | **-1.27s** | → **~1.4s** |
| **第一批** | P0-4 / P0-5 组件并发锁 + 子进程终止（**正确性**） | 消除功能损坏与孤儿进程 | — |
| **第二批** | P1-5 日历 polish、P1-6 隐藏停表、P1-8 `_rewatch`、P1-9 版本查询推迟、P1-4 QSS 缓存、P1-3 `_dbg` 内存缓冲 | 合计 **-0.3s** + 消除多处卡顿 | → **~1.1s** |
| **第三批** | P1-10 截图遮罩预渲染、P1-12 翻译图层移出 paintEvent | 截图/翻译交互流畅度 | — |
| **第三批** | P1-7 桌面图标跨进程风暴（风险最高，单独评审） | 消除 1.5s/3s 冻结 | — |
| **第四批** | P1-11 长图抓帧优化（**需先决定是否引入 numpy**） | 长图模式流畅度 | — |
| **第五批** | P2-14 拖拽起始延迟、P2-13 写盘合并、P2-11 弹层释放、P2-12 glow 优化、P2-15~24 | — | — |
| **第六批**（可选） | P2-10 四 tab 惰性构造（**需单独评审**） | -223ms / 内存 -30~60MB | → **~0.9s** |

### 9.2 暂不建议实施

* **P2-10 四 tab 惰性构造**：跨模块引用面大（`main.pyw` 与 `app.py` 多处直接访问 `panel.transfer` / `panel.video`），收益 223ms 相对风险偏高，建议在 P0/P1 全部落地并稳定后再评估。
* **P3-26 改钩子机制**：AGENTS.md 已记载全局钩子导致全系统鼠标卡顿的教训，收益小、风险大。
* **拆分 `boxes.json` 数据格式**（P2-13 的一部分）：涉及旧版本兼容，建议与其它 P2 解耦、单独评估。

### 9.3 需要确认的设计取舍

1. **图标提取的线程模型**：GUI 线程分批（简单、稳妥、视觉无跳变）vs. Win32 `SHGetFileInfoW` 工作线程（彻底不阻塞、但要重写图标获取路径、`.url` 的自定义图标逻辑需一并迁移）。**建议先做前者**。
2. **传输服务是否允许「首帧后才就绪」**：从「启动即监听」改为「启动后立即在后台监听、首帧先出」会让「程序刚起来时对端还发现不了我」的时间窗从 0 变成约 1 秒。**需确认可接受**。
3. **`_dbg` 改内存缓冲后，日志不再实时落盘**：崩溃现场的最后若干条日志会丢。**需确认是否接受**（可保留「关键事件立即 flush」的折中）。
4. **P1-5 是否允许改变 polish 粒度**：需先核对 `themes.py` 中所有 dayNum/daySub/badge 选择器，确认没有依赖祖先属性的写法。**若存在依赖，则该方案要调整为「只 polish 受影响控件」而非「只 polish self」**。
5. **`setStyleSheet` 作用域**（P1-4）：改为面板级会改变设置窗/格子/弹窗的样式作用域，**需逐窗口核对**。
6. **是否为 P1-11 长图优化引入 numpy**：项目目前**唯一依赖是 PySide6**，numpy 会增加约 15MB 安装体积与打包复杂度。若不引入，只能走纯 Python 优化 + Win32 `BitBlt` 局部抓帧路线（收益会打折）。
7. **截图遮罩预渲染的视觉一致性**（P1-10）：预渲染后选区边缘的抗锯齿表现可能与现状有差异 —— 需确认「灰罩边缘允许 ±1 像素级差异」是否可接受，还是必须逐像素一致。
8. **P0-4 的取消语义**：用户「关闭视频功能」时，正在进行的组件下载应当**中断**还是**跑完**？中断更快但可能留下半成品，跑完更安全但关了还在下载。

### 9.4 工作量与风险总览

| 批次 | 内容 | 工作量 | 风险 | 回滚粒度 |
|---|---|---|---|---|
| 第一批 | P0-1 图标异步化 + P0-2 传输服务异步 + P0-4/P0-5 正确性 | 1~1.5 天 | 中 | 每项单函数独立 revert |
| 第二批 | P1-3/4/5/6/8/9（小改为主） | 0.5~1 天 | 中 | 同上 |
| 第三批 | P1-10 截图预渲染 + P1-12 翻译图层（视觉/线程风险） | 1~1.5 天 | 中 | 单独提交 |
| 第三批 | P1-7 桌面图标跨进程风暴（风险最高，单独评审） | 1~2 天 | **中高**（跨进程内存结构） | 单独提交，跨进程改动独立 revert |
| 第四批 | P1-11 长图抓帧（**需先决定 numpy 取舍**） | 0.5~1.5 天 | 中 | 同上 |
| 第五批 | P2-11~14 + P2-15~24 | 1~1.5 天 | 中 | 同上 |
| 第六批（可选） | P2-10 四 tab 惰性构造（**需单独评审**） | 1 天 | **高** | 单独提交 |

---

## 附录 A：复现测量

```bat
:: 前置：确保没有 zbox 实例在跑（否则新进程会被 IPC 转发后立即退出）
python perf-audit\probe.py info

:: 冷启动（5 次）
python perf-audit\probe.py startup --runs 5 --out perf-audit\results\<tag>-startup.json

:: 稳态空闲
python perf-audit\probe.py idle --seconds 60 --out perf-audit\results\<tag>-idle.json

:: 长跑内存曲线
python perf-audit\probe.py longrun --seconds 1800 --interval 30 --out perf-audit\results\<tag>-longrun.json

:: 启动分阶段归因
python perf-audit\stage_probe.py --out perf-audit\results\<tag>-stage.json

:: CPU 热点采样
python perf-audit\flame.py --tag <tag>

:: 文件操作微基准
python perf-audit\microbench.py --sizes 100 1000 10000 --out perf-audit\results\<tag>-micro.json
```

**注意事项**
* 测量期间**不要**同时运行 zbox 实例（会触发 IPC 转发）。
* 探针会复制一份真实 `%APPDATA%\zbox` 到临时目录并把 `APPDATA` 指向它，**不写坏用户数据**；但注册表里的桌面右键菜单会随程序启动/退出切换形态（程序本身的正常行为）。
* 首次运行需先 `New-Item perf-audit\tmp,perf-audit\results -ItemType Directory -Force`。

## 附录 B：审计覆盖范围

| 模块 | 审计方式 | 结论摘要 |
|---|---|---|
| `main.pyw` | 精读 + 进程内插桩 | 启动链路清晰；`AA_ShareOpenGLContexts` 无条件设置；节假日后台更新在独立线程（正确） |
| `app.py`（3558 行） | 全量审计 + 插桩 | 定时器清单完整；`_dbg` 2Hz 磁盘写；QSS 全量重算；polish 风暴；弹层不释放 |
| `boxes.py`（4051 行） | 全量审计 + 插桩 | 图标提取无缓存（启动主因）；桌面图标跨进程风暴；`_rewatch` 丢事件窗口；`_snapshot_icon_zones` O(N×M) |
| `glow.py` | 全量审计 | 20fps 整卡重绘；逐段 HSV；`_sc` 函数内 import |
| `transfer_ui.py` | 全量审计 + 插桩 | `enable_service` 同步 1269ms（启动第二主因）；发送线程 180s 不可中断；`_animate_bar` 每次 new 动画对象；防火墙检查每次重跑；QMenu 不释放 |
| `video_ui.py` | 全量审计 + 插桩 | **组件并发下载无锁 → 可能装出半截 exe（正确性 bug）**；启动即联网查版本；卡片关闭不取消解析线程 → 对已销毁对象 emit 信号 |
| `screenshot.py` | 全量审计 + 插桩 | **遮罩每次重绘 = 2 次全桌面合成**；长图抓帧 280ms 一次全屏 grabWindow + 85K 次 Python 迭代（均在 GUI 线程）；翻译图层在 `paintEvent` 里构建（132MB 分配 + 逐像素 Python 循环）；鼠标移动时 Z 序遍历 900 次 ctypes/次 |
| `doubao_web.py` / `ocr_runtime.py` | 全量审计 | QtWebEngine 全懒加载（不影响启动）；每次翻译新起 OCR 子进程加载模型；`ocr_runtime` 的「先 rmtree 再 replace」两步窗口有组件丢失风险 |
| `themes.py` | 审计 | `build_qss` 无缓存；244 处 px 正则 |
| `build.py` | 精读 | onedir + onefile；`--noupx`；**QtWebEngine 为懒加载**（`doubao_web.py` 全在函数内 import），打包不会拖慢启动 |
| `sysutil.py` / `installer.py` | 审计 | 注册表操作为启动期少量调用，非热点；`appdata_dir()` 的迁移检查每次调用都跑（频率低） |

---

*本建议书基于 2026-10-20 的实测数据。所有标「实测」的数值均可由附录 A 的命令复现；标「待验证」的条目已在 §1.4 与各条目的「证据状态」中明确标注，未按缺陷定性。*
