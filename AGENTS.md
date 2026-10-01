# 解决方案

四个原则，集中在一个文件中，直接解决这些问题：

| 原则         | 解决什么问题          |
| ---------- | --------------- |
| **编码前思考**  | 错误假设、隐藏困惑、缺少权衡  |
| **简洁优先**   | 过度复杂、臃肿抽象       |
| **精准修改**   | 无关编辑、触碰不应碰的代码   |
| **目标驱动执行** | 通过测试优先、可验证的成功标准 |

## 四个原则详解

### 1. 编码前思考

**不要假设。不要隐藏困惑。呈现权衡。**

LLM 经常默默选择一种解释然后执行。这个原则强制明确推理：

- **明确说明假设** — 如果不确定，询问而不是猜测
- **呈现多种解释** — 当存在歧义时，不要默默选择
- **适时提出异议** — 如果存在更简单的方法，说出来
- **困惑时停下来** — 指出不清楚的地方并要求澄清

### 2. 简洁优先

**用最少的代码解决问题。不要过度推测。**

对抗过度工程的倾向：

- 不要添加要求之外的功能
- 不要为一次性代码创建抽象
- 不要添加未要求的"灵活性"或"可配置性"
- 不要为不可能发生的场景做错误处理
- 如果 200 行代码可以写成 50 行，重写它

**检验标准：** 资深工程师会觉得这过于复杂吗？如果是，简化。

### 3. 精准修改

**只碰必须碰的。只清理自己造成的混乱。**

编辑现有代码时：

- 不要"改进"相邻的代码、注释或格式
- 不要重构没坏的东西
- 匹配现有风格，即使你更倾向于不同的写法
- 如果注意到无关的死代码，提一下 —— 不要删除它

当你的改动产生孤儿代码时：

- 删除因你的改动而变得无用的导入/变量/函数
- 不要删除预先存在的死代码，除非被要求

**检验标准：** 每一行修改都应该能直接追溯到用户的请求。

### 4. 目标驱动执行

**定义成功标准。循环验证直到达成。**

将指令式任务转化为可验证的目标：

| 不要这样做... | 转化为...                |
| -------- | --------------------- |
| "添加验证"   | "为无效输入编写测试，然后让它们通过"   |
| "修复 bug" | "编写重现 bug 的测试，然后让它通过" |
| "重构 X"   | "确保重构前后测试都能通过"        |

对于多步骤任务，说明一个简短的计划：

```
1. [步骤] → 验证: [检查]
2. [步骤] → 验证: [检查]
3. [步骤] → 验证: [检查]
```

强有力的成功标准让 LLM 能够独立循环执行。弱标准（"让它工作"）需要不断澄清。

---
# Repository Guidelines

## Project Structure & Module Organization

Zviber 是 Windows 桌面悬浮面板（日历 + 待办），PyQt5，Python 3.8+，Win7 / Win10 / Win11 通用。
平铺布局，一个模块一个职责：

- `main.pyw` — 入口：单实例 IPC（`QLocalServer`）、节假日后台更新、（frozen 时）`--uninstall` 卸载向导入口
- `app.py` — 面板 UI（日历 / 待办 / 双栏 / 顶部栏滑出与拖动）、`SettingsDialog` 与节假日导入引导窗
- `boxes.py` — 桌面格子：空白格子（文件移入数据目录）与文件夹映射格子、双击桌面显隐
- `calendar_data.py` — 内置国务院节假日数据、农历换算、三源联网回退与离线导入
- `themes.py` — 两套主题 QSS（深色 `nocturne` / 浅色 `mica`）加 `auto` 伪主题；`%CN%`/`%NUM%` 为字体占位符
- `version.py` — 版本号唯一来源：关于窗、设置窗左下角、安装向导、卸载注册表项共用 `APP_VERSION`，发版只改这一个文件
- `sysutil.py` — 注册表集成：开机自启、桌面右键菜单、应用列表卸载项（默认 HKCU，免管理员）
- `installer.py` — 安装向导（选项/进度/完成页）与卸载向导（可选删除个人数据）；供 setup exe（安装）与程序本体 `--uninstall`（卸载）共用
- `install.py` — 源码方式的系统集成（只装开机自启）
- `setup.pyw` — 安装包入口：build.py 把它打成 onefile exe，内嵌 onedir 本体为 payload，双击弹安装向导
- `build.py` / `build.cmd` — 生成图标与 DPI 清单，两段式 PyInstaller：main.pyw 打 onedir 本体（`dist\build\app\`），setup.pyw 内嵌本体打成单个安装包 `dist\ZviberPanel-Setup-v<版本>-<架构>.exe`（架构标识跟随打包用的 Python：x64 / x86 / arm64）
- `run.cmd` — 双击启动面板；已在运行则切换显隐
- `stop.cmd` — 双击停止面板：先 `--quit` 经 IPC 礼貌退出（正常清理菜单注入），残留进程强制结束
- `designs/` — 两套主题的设计稿（HTML，浏览器可直接打开）

运行时数据在 `%APPDATA%\ZviberPanel\`（`config.json` / `todos.json` / `holidays.json` / `icons/`）——不要提交。

## Build, Test, and Development Commands

```bat
pip install PyQt5            :: 唯一依赖（Win7 需 Python 3.8 + "PyQt5==5.15.*"）
pythonw main.pyw             :: 源码方式运行（或双击 run.cmd）
python build.py              :: 打包 exe 安装包（或双击 build.cmd）
python install.py            :: 源码方式开启开机自启
python install.py --remove   :: 移除自启并清理旧的右键菜单
set ZVIBER_SHOT=designs\verify && python main.pyw   :: 截图自检
```

自检导出两主题 × 日历/待办/双栏截图后自动退出，改 UI / 主题 / 布局后必跑。
**跑之前先退出正在运行的实例**：否则单实例分支会把这次启动当成一次 `--toggle` 转发给已运行实例
（用户的面板被显隐一次），本进程直接退出，一张图都不会导出，而且没有任何报错。
截图目录与设计稿渲染图已 gitignore，不要提交。

- 另有 `ZVIBER_GRABSCREEN=<路径>`：抓取真实屏幕上面板所在区域（含系统合成效果）后退出。
- `run.cmd` / `build.cmd` / `stop.cmd` 是给最终用户双击的入口，**以 GBK 保存并自带 `chcp 936`，同时保持
  CRLF 行尾**，改完绝不能另存为 UTF-8，否则双击后中文提示乱码。
- `build.py` 除生成图标外还写 DPI 感知清单（`--manifest`）交给 PyInstaller：**PyInstaller 默认
  打的 exe 没有 DPI 感知声明**，进程被系统按 unaware 虚拟化，`ui_scale()` 读到 96 DPI，界面就
  完全不放大（源码运行由 Qt 运行时自己设了感知，没这个问题）。图标、清单连同 spec 与 PyInstaller
  工作目录全部收在 `dist\build\` 下——这三个 path 都是 `build.py` 显式传的绝对路径，
  **别把 `--workpath` / `--specpath` 删掉**，PyInstaller 默认往当前目录扔 `build\` 和 `*.spec`，
  根目录就乱了。`dist\` 整个目录已被 gitignore。
- 改功能时 README 与本文件（AGENTS.md）都要同步。

## 架构细节与坑位

### 数据流与进程模型（`main.pyw` + `sysutil` + `installer`）

数据流：`main.pyw`（入口）→ 构造 `Config` / `HolidayStore` / `TodoStore` → 注入 `FloatingPanel`，
面板只通过 store 读写，所有持久化落在 `%APPDATA%\ZviberPanel\`（`config.json`、`todos.json`、
`holidays.json`、运行时生成的 `icons/`）——**绝不提交这些数据**。

`main()` 的顺序是有意的，改动前先读懂：设置 excepthook → `installer.maybe_install()`
（仅 frozen exe 生效，只处理 `--uninstall` 卸载向导，返回 True 直接退出）→ 单实例 IPC 探测
（`QLocalSocket` 连 `sysutil.IPC_KEY`，已运行则发 `toggle` 后退出）→ 建面板 → 起 `QLocalServer`
接收 `toggle` / `quit` → `context_menu_set_running(True)` 注入桌面右键级联菜单。

- 单实例靠 `QLocalServer` 名称 `zviber-panel-v1`；消息由 `_on_ipc` 按 `actions` 字典分发，`quit` 消息供卸载程序请求退出。
- 桌面右键是**级联菜单**：父项「zviber桌面格子」用 `MUIVerb` + `ExtendedSubCommandsKey` 自引用（子项放父项 `shell\` 子键下，子键名字母序即菜单顺序，故带 A_/B_… 前缀）。两个实测坑：① 别用 `SubCommands` 方案——它只按 **HKLM** 的 `Explorer\CommandStore` 解析，HKCU 的不认，免管理员安装没法用；② 父项绝不能有 `command` 子键，否则退化成直链不展开。7 个二级项：显示/隐藏、新建格子、新建文件夹格子、显示/隐藏格子、设置、关于、退出，各走 `--toggle`/`--new-box`/`--new-folder-box`/`--toggle-boxes`/`--settings`/`--about`/`--quit` 命令行参数，经 IPC（`IPC_ACTIONS`）转发给运行中的实例，不新起进程。**菜单形态跟随运行状态**：`context_menu_set_running()` 在面板启停时改写——运行中 = 级联七项，未运行 = 直链单项「单击启动」（安装时写入的就是直链形态）；HKLM 安装无权改写，运行时往 HKCU 写覆盖层、退出删掉回落；源码运行（无安装记录）启动时注入级联菜单、退出时整体删除（崩溃残留由下次启动时 `sync_context_menu` 清掉）。
- `installer.setup_main()`（setup exe 入口）里 `ZVIBER_AUTO_INSTALL` 是静默安装测试钩子。
- **没有系统托盘图标**（已移除）：显隐/新建格子/设置/关于/退出等入口全在桌面右键级联菜单，
  别再往回加托盘。设置窗口是**非模态**的（桌面右键「设置」或标题栏 ⚙），已开着就 `raise_()`，不会叠第二个。

### 崩溃诊断与日志

⚠️ **PyQt5 里槽函数中未捕获的异常会让进程直接 abort（qFatal），不是打个日志就完事**——实测无自定义
excepthook 时 exit 127、连输出都没有。`main()` 里那句 `sys.excepthook = _debug_excepthook` 正是挡这个的
（改成落盘 `debug_due.log`，程序继续跑）；它的注释写着「定位后移除」，但**删掉它 = 任何槽里的异常都会
静默崩掉整个面板**，要删先确认有别的兜底。反过来说，它也把这类 bug 变成静默的了：后台更新那次
`hstore.merge` 漏写实现，在应用里只会静静地不更新，是离屏脚本才把它揪出来。

日志与诊断手段一览：

- `debug_due.log`（`%APPDATA%\ZviberPanel\`）：Python 层未捕获异常，excepthook 始终落盘。
  **ctypes 回调（如 WH_MOUSE_LL 的 `proc`）里的异常不走 excepthook**——被 ctypes 吞掉打印到
  pythonw 不可见的 stderr，还会向系统返回垃圾值；所以 `boxes.py` 的 `proc` 自带 try/except
  落盘同一文件（带 `--- DesktopClickHook ---` 标记）。
- `crash_native.log`（同目录）：`main()` 里 `faulthandler.enable()` 落盘 Qt/C++ 层原生崩溃
  （访问冲突直接杀进程时，Python 堆栈的唯一痕迹）。
- `zviber_debug.log`（`%TEMP%\`）：`ZVIBER_DEBUG=1` 时 `_dbg()` 埋点日志（run.cmd 常开，
  自带 2MB 轮转），只记滑动/悬停/tick 等埋点，不含崩溃堆栈。
- **进程冻结但没崩**：`py-spy dump --pid <pid> --native` 直接抓所有线程的 Python + Qt 混合栈
  （2026-09 靠它实锤了钩子线程 winId 死锁，见下方格子章节）。

### 面板（`app.py`）

`FloatingPanel` 是无边框**不透明**顶层窗口：不用 `WA_TranslucentBackground`（分层窗口禁用
ClearType，文字发灰），圆角靠 Win11 DWM，Win7/10 降级为圆角遮罩（`round_corners`）；
也不用 `QGraphicsDropShadowEffect`（Qt5 下破坏顶层窗合成），所以 `SHADOW = 0`、无阴影留白。
（`FloatingPanel.__init__` 里那句「阴影改为 paintEvent 手绘」是旧注释，类中已无 `paintEvent`。）

- **`QStackedLayout` 必须先挂父控件再 `addWidget`**：第一个页面会立刻成为当前页被 `show()`，
  无父状态下闪出一个默认大小的顶层白框（2026-10 启动/建格子白闪的根因，`app.py` 的 `content`
  与 `boxes.py` 的 `pages` 两处同坑，都是先 `addLayout` 进父控件再添加页面）。
- 单栏用 `_SlideStack`（横向滑动切页动画，接口兼容 QStackedWidget 子集），
  双栏用 `QHBoxLayout`，两者由 `self.content`（QStackedLayout）切换。
- 尺寸常量 `SINGLE_W / DUAL_W / PANEL_H`；`cfg` 键：`theme` / `dual` / `tab` / `pos` /
  `off_noon` / `off_evening`，`Config` 用 `__getattr__` 暴露为属性。
- **桌面格子模式**：窗口标志是 `FramelessWindowHint | Tool`，**故意不带 `WindowStaysOnTopHint`**
  ——面板就该被别的窗口正常盖住，别再顺手加回去。
- **顶部栏默认收起**（`_slide_titlebar`）：栏窗高度 0↔`sc(42)` 做动画，靠 `_set_tb_height` 把它摆到
  面板顶边**上方**（`y = self.y() - h`）实现「向上滑出」，主窗口不动。进入面板（`enterEvent`）展开；
  离开后等 150ms 用 `_check_hover()` 看光标落点再决定收不收（光标从面板挪进展开栏会先触发面板的
  `leave`，不等这一拍就会抖）。
- **栏窗也是桌面带成员**（`_ensure_band` 里随面板一起 `pin_to_desktop`）：栏窗是独立顶层 Tool 窗，
  不挂带时悬停弹出会盖住压在面板上的应用窗口。拖拽期间随面板一起临时脱带、松手挂回；
  `pin_to_desktop` 内部已处理可见窗口挂带丢 `WS_VISIBLE` 的坑（ShowWindow SW_SHOWNA）。
- **拖动把手**：展开的顶部栏、日历左侧的时分秒与日期行，都走同一个 `eventFilter` 里的
  MouseButtonPress/Move/Release 直接 `move()`，松手 `_save_pos()` 落盘。过滤器只装在
  `titlebar` / `cal.clock_hm` / `cal.sub` 三个控件上——装在哪就只对谁生效（标题栏里设置、关闭
  按钮的点击不受影响）；想再划一块可拖区域，得把过滤器也装到那个控件上。
- 时间设置两处约定：`off_noon` 是**区间** `'HH:mm-HH:mm'`（旧版单值 `'12:00'` 按开始点 +1 小时
  兼容）；时间框一律用自由文本 `QLineEdit` + `parse_time_text` / `parse_noon_range` 解析，
  不用 `QTimeEdit`——它按时/分分段校验，全选后直接打字会被校验器拒掉，且根本打不进冒号。
  解析器认中文冒号与全角数字；输入中能解析就即时落盘，失焦才归一化。
- **午休与下班时间都可以留空**（存空串 = 不设这个时间点）：午休要两端都有效才算数，只填一半
  按留空处理。留空后重开设置窗口必须还是空框——所以初值直接读配置，**不能再拿默认值兜底**
  （兜底会让空值悄悄变回 12:00-13:00，用户以为没清掉）。
- 日历顶部倒计时按这两个值出三档：午休前「距午休」→ 午休区间内「距上班」（倒计时到午休结束）
  → 「距下班」，下班后「今天已下班」。休息日显示「今天休息」；**任一时间留空则整块不显示**
  （没填全就不猜时间点，时钟行留白）。
- 时钟行右侧那行小字（倒计时 / 翻月后的「yyyy年MM月」）要与左边的时分秒**底边齐平**：
  布局用 `Qt.AlignBottom` 对齐控件底边，再由 `_sync_sub_baseline()` 补一段下边距顶到同一条
  文字基线（40px 与 10.5px 的字体 descent 差多少，小字就沉下去多少）。**别改成
  `Qt.AlignBaseline`**——Qt 对 QLabel 取的并不是文字基线，实测比底边对齐偏得更多。
  `_update_sub()` 每秒都会调它，所以拿字体的 height/ascent/descent 当缓存键，没变立即返回。
- 所有动态属性（`dim` / `active` / `we` 等）驱动的 QSS 选择器，改属性后必须
  `unpolish` + `polish` 才会重绘。子孙选择器依赖祖先属性时，祖先与其子控件都要重刷
  （见 `_apply_dim`）。

#### 日历的连续周条带

日历不是「一月一页」，而是把周序列切成 42 格（6 周）的 `_GridPage` 条带，首尾相接不重复周，
因此平移停在任意位置都不会出现跨页重复行。`_GridViewport` 在上/当前/下三个页面间平移：

- 平移中切到 `pixmaps` 位图缓存（每帧只 blit 三张图），停手 200ms 后 `_end_pan` 切回活页面。
- `_page_pixmap` 抓图前必须预填透明——否则深色主题下平移会闪白。
- 置灰（非当月）跟随视口中线所在周，平移中只置 `_dim_dirty` 记账，停手时一次性 `_apply_dim`。
- 滚轮走 `_glide` 阻尼动画，触摸板（pixelDelta）直接跟手不走动画。

#### 待办行的多行文本

待办文字是 word-wrapped 的 `QLabel`，行高不再固定，**必须显式同步 item 的 sizeHint**
（`TodoWidget._sync_row_heights`，挂在 `TodoList.on_resize` 上），否则 `QListWidget` 还按
36px 压扁行、长文字被裁。测量姿势：先 `list.doItemsLayout()` 让行按新行宽摆好，再问文字标签
`heightForWidth(它自己的宽度)`——按布局估算出来的宽度算会少算一行；跑两遍是因为第一遍定出的
新高度可能带出滚动条、行宽还会再变一次。编辑器行高度由 `_open_editor` 固定，同步时要跳过。

日期 tag（`due_chip`）：逾期→「逾期 N 天」，当天→「今天」，7 天内→「还剩 N 天」，更远只报日期。
日期格式统一由 `fmt_due_date` 给出 `M.d`（如 `10.7`），**行内 tag 与编辑器里的日期按钮共用它**
——两处各写各的格式就会出现「编辑时 10/9、保存后 10.09」这种不一致。

### 主题与 DPI（`themes.py` + `app.py`）

`themes.py` 有两套真主题：`nocturne`（深色）、`mica`（浅色），`THEME_ORDER` 定顺序；另有伪主题 `AUTO`
（设置窗里的「跟随系统」），`THEME_CHOICES = THEME_ORDER + [AUTO]` 是设置窗选项顺序，`Config` 按它校验。
真主题要同时进 `THEMES` 与 `THEME_ORDER`；`auto` 靠 `app.resolve_theme()` 解析成实际主题（系统「应用模式」
是浅色就用 mica），`_check_date` 那个 30s 定时器会复查一次，所以系统里改了颜色最多 30 秒后跟着切。
主题 dict 不只有 `qss`：`name`（设置窗口单选项文案）、`count_fmt`（待办计数文案，两套主题措辞不同）、
`week`（周一为首的周标签）都按主题区分。QSS 内有三种占位符：`%CN%` / `%NUM%`（字体名）、
`%ICON_DIR%`（`app._indicator_icons()` 在运行数据目录生成的 checkbox/radio 图标，正斜杠路径）。
`build_qss()` 还会把所有 `Npx` 按 DPI 缩放比放大。

`designs/*.html` 是两套主题的像素级设计稿（HTML 可直接在浏览器打开），调主题时对着它改。

DPI 约定：**设计尺寸按 100% 基准写死，运行时用 `app.sc(v)` 换算**（`ui_scale()` 取
`GetDpiForSystem()/96`，钳制在 0.75–3.0）。新增任何尺寸都要过 `sc()`，QSS 里的 px 由
`build_qss` 统一处理，不要手动乘。

### 节假日与农历（`calendar_data.py` + `main.pyw`）

`HolidayStore.info(d)` 的优先级：用户自定义（联网/导入）→ 内置官方数据 → 普通日。
内置 `EMBEDDED_OFF` / `EMBEDDED_WORK` 是国务院公布的年份安排，**新一年安排发布后要手工补**；
没有数据的年份只显示双休与农历节日，不标「休/班」角标。农历是 1900–2100 查表法（`LUNAR_INFO`），带缓存。

**三个数据源**（`SOURCES` 按顺序回退，三家 JSON 格式互不相同而 `parse_holiday_json` 全认）：
timor.tech `{"holiday":{"01-01":{...}}}` → jiejiariapi `/v1/holidays/<年>` 扁平 `{iso:{isOffDay}}`
→ holiday-cn（走 jsDelivr 镜像）`{"days":[{date,name,isOffDay}]}`。导入窗口里三个 URL 都能改
（内网镜像、换年份）。两个坑：① timor **不带 User-Agent 直接回 403**，UA 头是有意加的、别当冗余删；
② 有的源用同一个字段顺带标了「小年」这类传统节日（`isOffDay: false`），所以判「班」只认**落在周末**
的上班日（`_is_weekend`）——不然换个源就会平白多出几个「班」角标，三个源之间也就不一致了。

**后台更新**：`main.pyw` 的 `_HolidayWorker(QThread)` 只负责下载 + 解析，结果用信号交回主线程再合并，
**绝不跨线程动 store**；抓取期间界面不卡（三源 × 两年 × 10 秒超时最坏能到一分钟）。是否该更新看
`_auto_update_due()`：上次**尝试**时间（`cfg['holiday_ts']`，记尝试而不是成功，失败才不会反复重试）
不是今天就更新（每天第一次开程序），或距上次满 48 小时（程序长期不关）；手动「联网更新」与导入窗的
「下载并导入」走同一条通道，手动路径的结果写进调试日志（`_dbg`）。

日历格子右上角的「休」/「班」角标：只标法定节假日（`kind == 'off'`）与调休上班日（`kind == 'work'`），
**普通双休日不标**（双休只靠日期数字的弱化配色区分）。角标是 `DayCell.badge` 这个 QLabel，文字与配色
全由 `#badge[kind=…]` 的 QSS 给，摆位在 `DayCell._place_badge`——单栏一格只有约 43px 宽，尺寸必须靠
`adjustSize()` 自适应、且不能加 padding，写死尺寸或留内边距都会压住 19px 的日期数字。

### 系统集成（`sysutil.py` + `installer.py` + `install.py`）

- 注册表写入默认走 HKCU（**免管理员**，Win7/10/11 通用）；`all_users=True` 才写 HKLM
  （exe 安装向导的「此计算机」选项，需管理员）。清理函数对两个根都尝试、无权限时静默跳过。
- 涉及的键：`Run`（自启）、`Directory\Background\shell\ZviberPanel`（桌面右键菜单）、
  `Uninstall\ZviberPanel`（应用列表卸载项）。
- **桌面右键菜单只属于 exe 安装**：只有 `installer.install()` 会写菜单，`install.py` 只写开机自启。
  每次启动 `installer.sync_context_menu()` 按 `Uninstall\ZviberPanel` 的 `InstallLocation` 判定——
  没有任何安装记录就清掉菜单残留（旧版 install.py 的源码安装、向导取消、半卸载）。**调用时机必须在 IPC 转发之后**——源码模式没有安装记录，转发进程（`--new-box` 等）若先跑这步会把运行中面板刚注入的级联菜单当残留删掉（真实 bug）。`context_menu_remove` 要自底向上清三层子键（winreg 不能删带子键的键），含旧版直链菜单的 `command` 残留。
- `sysutil.launcher_cmd()` 区分 frozen（直接启自身）与源码（优先 `pythonw.exe` 实现无窗口静默）。
- `installer.py` 的向导**只在 frozen 时生效**；源码运行走 `install.py`。
- 安装 = 把安装包内嵌的 payload（onefile 运行时解压到 `_MEIPASS\payload` 的 onedir 本体：exe + `_internal\`）**整体复制**到目标位置，按字节回报进度；目标目录已有旧安装（含 `ZviberPanel.exe`）时先整体清空再复制——`_check_dir` 只放行空目录/新目录/含 `ZviberPanel.exe` 的旧安装目录，别放宽这个签名判断，否则覆盖重装与卸载会误删用户文件。
- 卸载走与安装同风格的**卸载向导**（确认页 → 进度页 → 完成页）：确认页 checkbox「同时删除个人数据」勾选后连同 `%APPDATA%\ZviberPanel`（待办、格子、配置）一起 rmtree，默认保留；程序目录用延迟 `rmdir` 删除（exe 运行中删不掉自己）。

### 桌面格子（`boxes.py`）

桌面文件归类格子：`BoxManager` 总管（恢复/新建/解散/显隐），`BoxWindow` 单格，
`BoxStore` 存 `%APPDATA%\ZviberPanel\boxes.json`（`visible` + 格子记录列表）。
格子管理入口在桌面右键级联菜单（新建格子 / 新建文件夹格子 / 显示隐藏格子）；截图自检模式不创建格子。

- **层级策略（踩坑三轮后的终态）：挂桌面带（`pin_to_desktop`，免疫 Win+D）
  + 永不主动沉底 + 被桌面整理表层压住时由 WinEvent 钩子/看门狗抬回。**
  带内窗口点击激活会浮到应用窗口之上（实测确认），只要不主动 sink 它就一直在，
  这就是「格子永不消失」的关键——沉底（sink_to_desktop）只用于「被表层压住」的抬回。
  ❌ 不要学面板在失焦时沉底：格子会被拖到任何位置，沉到应用窗口之下 = 用户眼里的消失。
- **看门狗必须极廉**：每 tick 只做一次中心命中（`_covered_by_surface`），真被压住才跑
  `probe_desktop` 找锚点。probe 的多点 WindowFromPoint 是跨进程同步调用，命中无响应窗口
  会阻塞主线程——曾因每 500ms × 4 格子 × 6 点探测把界面打到转圈假死。
- **空白格子是真实文件夹**（`Boxes\<id>\`）：拖入 = `shutil.move` 进去，解散 = 全部还原回
  桌面（SHGetFolderPath 取真桌面，处理 OneDrive 重定向），不删文件。映射格子只读目录、
  `QFileSystemWatcher` 300ms 去抖刷新；路径失效显示「解散格子」页。
- **解散格子有二次确认**（`BoxConfirmDialog`：无边框 Tool 窗，结构仿面板「关于」窗，
  视觉沿用格子的深色磨砂圆角，空白/映射格子提示语不同）。`QMessageBox` 只还剩删除确认在用，
  `_box_qss` 里给它补了深色底——白字落默认浅色底会看不清。
- **双击标题名称 = 原地内联重命名**（QLineEdit 替换 QLabel，回车/失焦提交、Esc 取消；
  事件在过滤器里吃掉，不再触发双击收起）。映射格子点左上角文件夹图标 = 打开所在文件夹
  （eventFilter 里按下即开，双击/松开都吃掉防连带拖动与收起）；空白格子是背地里的
  存储目录，图标不可点。
- **视觉固定深色磨砂**，不挂主题系统。`WA_TranslucentBackground` 的 ClearType 问题这里接受
  （参考软件本身就是半透明）。**半透明窗口 show 的首帧会闪一帧白屏**（paint 未跑先合成），
  `_spawn` 里先 `setWindowOpacity(0)` 隐身、120ms 后再现身（同时盖住挂带 SetParent 的隐藏-重现）。
- **双击桌面空白显隐**（`BoxManager.toggle_all`）：桌面图标 + 全部格子 + 面板一起显隐，
  图标显隐 = ShowWindow 桌面的 `SysListView32`（`find_desktop_listview` 定位，Progman
  找不到再扫 WorkerW）。`DesktopClickHook` 独立线程**轮询左键沿**（GetAsyncKeyState 每 20ms）
  按 GetDoubleClickTime 判双击——**不要用 WH_MOUSE_LL 全局钩子**：每个系统鼠标事件都要同步等
  Python 回调拿 GIL，GUI 线程拖拽重绘时全系统鼠标卡顿 5-10 秒，ctypes 回调里的崩溃还直接
  闪退进程（2026-10 拖拽格子卡顿→闪退的根因，c000041d + 访问冲突）。坑：① 命中链先排我们自己的窗口；
  ② 认 Progman 家族 + `SysListView32` + 全屏工具窗（桌面整理软件覆盖层）；
  ③ **`SysListView32` 要过跨进程 `LVM_HITTEST`**：点在图标/文件夹上不算空白（结构体开在
  explorer 地址空间里 SendMessage 才读得到）；
  ④ **第一击也必须落在桌面上**，否则「拖开格子 → 快速点它腾出的空位」会误判双击桌面，
  全部格子被隐藏（真实用户 bug）。
- **已可见的窗口 SetParent 挂带后 win32 侧 WS_VISIBLE 会丢**（Qt 仍认为可见不重绘 = 消失），
  `_repin` 里补 `ShowWindow(SW_SHOWNA)`。面板在 init 挂带（未 show）所以没踩过。
- **凡是进 ctypes 的 Win32 函数都要显式声明 restype/argtypes**（含 GetMessageW）——windll
  默认按 32 位截断，64 位下指针参数高位丢失，钩子线程静默失效。
- `boxes.json` 读取用 `utf-8-sig`：手工编辑带出的 BOM 会让 `utf-8` 读失败、save 用空数据
  覆盖原文件（`config.json` 在 app.py 里有同样的坑，暂未动）。
- **格子文件右键 = 系统外壳菜单**（`shell_context_menu`，与资源管理器同款）：纯 ctypes COM，
  零新增依赖。实测坑：① 取菜单用 `CDefFolderMenu_Create2`，别走 `IShellFolder::GetUIObjectOf`
  ——某些系统组件的 vtable 布局不可依赖（实测访问冲突）；② 菜单对象无站点（SetSite）时
  `InvokeCommand` 对所有动词一律 E_FAIL，动词执行改走 `GetCommandString` 取动词名 +
  `ShellExecuteEx`；③ ShellExecuteEx 必须在独立 STA 线程里调且带 `SEE_MASK_ASYNCOK`
  ——Qt 把 GUI 线程初始化成 MTA（壳动词在 MTA 下返回成功但什么都不做），同步调用又会
  吊死调用线程（壳内部要等本线程泵消息）；④ `QueryContextMenu` 标志要给
  `CMF_EXPLORE|CMF_CANRENAME`，否则菜单没有「重命名」；⑤ **别传 `ahKeys`**——传了会整个
  替换壳默认的动词/扩展合并，菜单只剩壳内置项（扩展全丢）；⑥ 壳默认菜单不合并用户范围
  （HKCU\Software\Classes）注册的 progid 动词，也不合并 `HKCR\*\shell` 静态动词
  （如 ToDesk 快传）——两类都要手工补到菜单顶部（已存在的不重复补，第 0 项
  SetMenuDefaultItem 加粗，图标用 ExtractIconExW 取 exe 图标 + SetMenuItemInfo 的
  `MIIM_BITMAP=0x80` 挂位图，注意 0x20 是 MIIM_DATA 不是位图掩码）；⑦ `IExplorerCommand`
  型注册项（如 Notepad++ 的 `ANotepad++64`）与 Defender 的 EPP 在非 Explorer 宿主下
  加载/添加失败，菜单里出不来（Windows 没有借用资源管理器菜单的 API，只能按注册表+COM
  自己拼，这两项拼不进是宿主限制）；⑧ 菜单跟随系统明暗要调 uxtheme 135 号序数
  `SetPreferredAppMode`（深色 2 / 浅色 3），不然深色系统上也是浅色菜单。
- 列表里 `.lnk` 显示名去掉后缀（对齐资源管理器），UserRole 仍存完整路径，拖出/打开不受影响
- **轮询线程里绝不调任何 Qt 方法（2026-09 真实死锁）**：`DesktopClickHook` 的轮询跑在独立线程，
  旧版 `own_hwnds()` 在其中调 `QWidget::winId()`——winId 会现场创建原生窗口，
  `flushWindowSystemEvents → QWaitCondition` 阻塞等主线程刷窗口事件，而工作线程持有 GIL、
  主线程绘制时 `PyGILState_Ensure` 又在等 GIL，两线程互等永久死锁（症状：任意左键点击后界面
  冻结；LL 钩子不返回期间系统对每个鼠标事件等超时 = 鼠标瞬间爬行）。修复：`own_hwnds` 只读主线程
  预建的 `frozenset` 快照（`_refresh_own_hwnds`，启动与格子增删时刷新、整体换引用）。
  Win32 API（WindowFromPoint / GetParent / GetClassNameW 等）跨线程调用是安全的，Qt 对象一律不碰。

## Coding Style & Naming Conventions

- 每个模块首行 `# -*- coding: utf-8 -*-`，4 空格缩进
- `snake_case` 函数、`UPPER_SNAKE` 常量、单引号字符串、`%` 格式化
- 模块 docstring 与行内注释一律中文——保持这个风格
- 无 linter / formatter；保持 diff 最小、与周围代码一致
- `run.cmd` / `build.cmd` 以 GBK 保存并自带 `chcp 936`，**改完不要另存为 UTF-8**，否则双击后中文提示乱码

## Testing Guidelines

没有单元测试框架。验证 = `ZVIBER_SHOT` 截图自检 + 手动检查桌面右键菜单形态切换（运行中级联 / 未运行直链）、开机自启。
改布局代码时要在 125% / 150% 缩放下确认。

## Commit & Pull Request Guidelines

仓库 [github.com/evachxji/zviber](https://github.com/evachxji/zviber)（public，MIT）。
提交用 `feat:` / `fix:` / `refactor:` / `docs:` 前缀 + 简短中英文摘要。
PR 需说明改了什么与为什么；视觉改动附自检截图；注明验证过的 Windows / Python 版本。

## Security & Configuration Tips

- 注册表只写 HKCU（免管理员）；「此计算机」安装写 HKLM 才需要 UAC 提权
- 网络访问仅限 timor.tech 的节假日接口——该接口不带 User-Agent 会回 403；
  内网用户走离线 JSON 导入，这条路径必须一直可用
