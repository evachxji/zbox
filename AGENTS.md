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

Zbox 是 Windows 桌面悬浮面板（日历 + 待办 + 局域网传输），PyQt5，Python 3.8+，Win7 / Win10 / Win11 通用。
平铺布局，一个模块一个职责：

- `main.pyw` — 入口：单实例 IPC（`QLocalServer`）、节假日后台更新、局域网传输服务启动、（frozen 时）`--uninstall` 卸载向导入口
- `app.py` — 面板 UI（日历 / 待办 / 传输 / 顶部栏滑出与拖动）、`SettingsDialog` 与节假日导入引导窗
- `boxes.py` — 桌面格子：空白格子（桌面文件的收纳视图，不搬文件、只隐藏桌面图标）与文件夹映射格子、双击桌面显隐
- `calendar_data.py` — 内置国务院节假日数据、农历换算、三源联网回退与离线导入
- `transfer.py` — 局域网文件传输协议核心（参照 LocalSend v2 的私有实例）：UDP 组播发现 + HTTP REST 传输，纯标准库零 Qt
- `transfer_ui.py` — 面板「传输」tab：设备列表、文件多选 + 拖拽发送、传输记录、接收确认弹窗、发送方取消；传输服务生命周期自持（默认关闭的门禁层、启用/停用、「?」说明弹窗）
- `transfer_selftest.py` — 传输协议自动化自检（13 用例，动态端口，不依赖组播/Qt）
- `themes.py` — 两套主题 QSS（深色 `nocturne` / 浅色 `mica`）加 `auto` 伪主题；`%CN%`/`%NUM%` 为字体占位符
- `version.py` — 版本号唯一来源：关于窗、设置窗左下角、安装向导、卸载注册表项共用 `APP_VERSION`，发版只改这一个文件
- `sysutil.py` — 注册表集成：开机自启、桌面右键菜单、应用列表卸载项（默认 HKCU，免管理员）
- `screenshot.py` — QQ 风格截图：全屏灰罩遮罩（`ShotOverlay`）、框选/8 手柄调整、矩形/椭圆/文字标注（颜色 + 反色）、导出复制/保存/钉图、滚动截长图；`HotkeyManager` 全局热键
- `pinshot.py` — 钉图窗 `PinWindow`：置顶无边框贴图，拖拽移动、双击关闭，不持久化
- `installer.py` — 安装向导（选项/进度/完成页）与卸载向导（可选删除个人数据）；供 setup exe（安装）与程序本体 `--uninstall`（卸载）共用
- `install.py` — 源码方式的系统集成（只装开机自启）
- `setup.pyw` — 安装包入口：build.py 把它打成 onefile exe，内嵌 onedir 本体为 payload，双击弹安装向导
- `build.py` / `build.cmd` — 生成图标与 DPI 清单，两段式 PyInstaller：main.pyw 打 onedir 本体（`dist\build\app\`），setup.pyw 内嵌本体打成单个安装包 `dist\zbox-Setup-v<版本>-<架构>.exe`（架构标识跟随打包用的 Python：x64 / x86 / arm64）
- `native/` — 外壳菜单宿主：`zshell.cpp`（C++ 源码，契约见下方「格子文件右键」）
  + `build_native.cmd`（cl /MT 静态 CRT 编译出 `zshell_host.exe`，需 MSVC Build Tools）；
  exe 随仓库提交，改源码后需重新编译并一起提交
- `run.cmd` — 双击启动面板；已在运行则切换显隐
- `stop.cmd` — 双击停止面板：先 `--quit` 经 IPC 礼貌退出（正常清理菜单注入），残留进程强制结束
- `designs/` — 两套主题的设计稿（HTML，浏览器可直接打开）
- `website/` — 产品介绍页（纯静态无构建），线上 https://zbox.wzyjc.cn（腾讯云 COS 静态托管）；
  `deploy-cos.py` 一键上传部署 / `--bind-cert <ID>` 绑定续期证书，细节见 `.claude/skills/site-deploy/`
- `android/` — Android 端独立 Gradle 工程（Kotlin + Compose，与 PC 代码完全分离）
- `build-apk.cmd` — 双击打包 Android APK：自动定位 JDK 17 再调 `gradlew assembleDebug`
- `assets/` — README 引用的图标与功能截图
- `docs/` — 历史实现计划存档（`superpowers/plans/`）

运行时数据在 `%APPDATA%\zbox\`（`config.json` / `todos.json` / `holidays.json` / `boxes.json` / `icons/`）——不要提交。
**目录名 2026-10 由 `zviber` 改成 `zbox`**：`sysutil.appdata_dir()` 首次调用时自动把旧目录搬过来
（`_migrate_appdata`：整目录 rename → 逐文件 `_merge_tree`；同名文件以新目录为准，被占用的下次启动再搬），
老用户的待办 / 格子 / 配置不丢。唯一例外：旧配置里的 `transfer_enabled` 会被
`_reset_migrated_transfer` 重置为关闭——升级后第一次启动不该直接监听端口、弹防火墙授权，
想用传输在传输页手动启用一次（防火墙提示出现在那一刻）。只有配置真从旧目录搬过来才重置，
新目录已有的配置不碰。

## Build, Test, and Development Commands

```bat
pip install PyQt5            :: 唯一依赖（Win7 需 Python 3.8 + "PyQt5==5.15.*"）
pythonw main.pyw             :: 源码方式运行（或双击 run.cmd）
python build.py              :: 打包 exe 安装包（或双击 build.cmd）
native\build_native.cmd      :: 编译外壳菜单宿主 zshell_host.exe（改 native\zshell.cpp 后必跑）
python install.py            :: 源码方式开启开机自启
python install.py --remove   :: 移除自启并清理旧的右键菜单
python transfer_selftest.py  :: 传输协议自检（全过打印 SELFTEST OK）
cd android && gradlew.bat assembleDebug   :: 构建 Android debug APK（或双击 build-apk.cmd）
set ZBOX_SHOT=designs\verify && python main.pyw   :: 截图自检
```

自检导出两主题 × 日历/待办/传输共 6 张截图后自动退出，改 UI / 主题 / 布局后必跑。
**跑之前先退出正在运行的实例**：否则单实例分支会把这次启动当成一次 `--toggle` 转发给已运行实例
（用户的面板被显隐一次），本进程直接退出，一张图都不会导出，而且没有任何报错。
截图目录与设计稿渲染图已 gitignore，不要提交。

- 另有 `ZBOX_GRABSCREEN=<路径>`：抓取真实屏幕上面板所在区域（含系统合成效果）后退出。
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
面板只通过 store 读写，所有持久化落在 `%APPDATA%\zbox\`（`config.json`、`todos.json`、
`holidays.json`、运行时生成的 `icons/`）——**绝不提交这些数据**。

`main()` 的顺序是有意的，改动前先读懂：设置 excepthook → `installer.maybe_install()`
（仅 frozen exe 生效，只处理 `--uninstall` 卸载向导，返回 True 直接退出）→ 单实例 IPC 探测
（`QLocalSocket` 连 `sysutil.IPC_KEY`，已运行则发 `toggle` 后退出）→ 建面板
（传输服务由面板自持：`cfg['transfer_enabled']` 为真才创建并 start `TransferServer` + `Discovery`，
端口 53327 被占则传输页显示「不可用」门禁层；`ZBOX_SHOT` 下不起服务也不盖门禁层）→ 起 `QLocalServer`
接收 `toggle` / `quit` → `context_menu_set_running(True)` 注入桌面右键级联菜单。

- 单实例靠 `QLocalServer` 名称 `zbox-panel-v1`；消息由 `_on_ipc` 按 `actions` 字典分发，`quit` 消息供卸载程序请求退出。
- 桌面右键是**级联菜单**：父项「zbox桌面格子」用 `MUIVerb` + `ExtendedSubCommandsKey` 自引用（子项放父项 `shell\` 子键下，子键名字母序即菜单顺序，故带 A_/B_… 前缀）。两个实测坑：① 别用 `SubCommands` 方案——它只按 **HKLM** 的 `Explorer\CommandStore` 解析，HKCU 的不认，免管理员安装没法用；② 父项绝不能有 `command` 子键，否则退化成直链不展开。6 个二级项：新建格子、新建文件夹格子、显示/隐藏卡片、设置、关于、退出，各走 `--new-box`/`--pick-folder`/`--toggle`/`--settings`/`--about`/`--quit` 命令行参数，经 IPC（`IPC_ACTIONS`）转发给运行中的实例，不新起进程。**菜单形态跟随运行状态**：`context_menu_set_running()` 在面板启停时改写——运行中 = 级联六项，未运行 = 直链单项「单击启动」（安装时写入的就是直链形态）；HKLM 安装无权改写，运行时往 HKCU 写覆盖层、退出删掉回落；源码运行（无安装记录）启动时注入级联菜单、退出时整体删除（崩溃残留由下次启动时 `sync_context_menu` 清掉）。
  **第三种形态——全隐藏单项**：双击桌面把图标/格子/面板全收起来后，`toggle_all` 调
  `context_menu_set_icons_hidden(True)` 把桌面右键收成唯一直链项「显示桌面图标」
  （`--show-icons` 经 IPC 调 `BoxManager.show_all`，图标 + 格子 + 面板一起放回），恢复后切回级联；
  文件夹右键项在单项形态下一并撤掉、恢复时随级联带回。无实例时点到残留单项 = 正常启动后菜单归位。
  单项形态下还有一层主动拦截：`DesktopRightClickHook`（WH_MOUSE_LL）把落在桌面上的右键吞掉，
  Explorer 的系统菜单整体不弹，改弹自己的 QMenu 单项。「点外面关闭 / 右键换位置重弹」不靠
  Qt 的弹窗鼠标抓取（SetCapture 只在抓取时有按键按住才管别的线程窗口，菜单是从队列信号
  弹出的、抓不住桌面点击），由钩子代劳：菜单开着时点菜单以外发 `outside_clicked`——
  点桌面吞掉（系统菜单不弹、框选不发生）、点别的应用放行（窗口正常激活）只关菜单；
  桌面右键关掉当前菜单并在新位置重弹（`_reopen_menu` 标志，exec_ 返回后 singleShot 重弹）。
  点菜单自身（本进程窗口）放行给 Qt，菜单项才点得上。钩子只在全隐藏期间安装、恢复立即卸载，
  回调对非右键消息只做一次 wParam 比较就放行——与 boxes.py 文件头「不用常驻 WH_MOUSE_LL」的
  教训不冲突（那里反对的是常驻全量钩子）。两个硬约束：run() 必须用阻塞式 GetMessage 泵
  （LL 钩子回调靠安装线程的消息泵派发，事件要等钩子链返回才投递，轮询泵会给全系统鼠标加延迟）；
  ctypes 回调异常就地兜住落盘。命中判定与双击共用 `_hit_desktop`（blank_only 区分点中图标）。
  钩子装不上时降级：系统菜单照常弹，但里面只剩注册表那枚单项。
  恢复显示三者同帧：`_show_everything`（toggle_all 与 show_all 共用）先把收文件图标等
  慢操作（逐文件改属性 + SHChangeNotify）做完，再按实测绘制延迟倒序错峰翻牌——
  桌面图标（Explorer 画得最慢，~480ms）立即翻，格子延迟 ~230ms、面板延迟 ~320ms
  （`_SHOW_DELAY_BOXES`/`_SHOW_DELAY_PANEL`，经验值），三者凑到同一帧出现。
  紧挨着三连翻没用：三方绘制耗时不同，用户看到的是格子→面板→图标三批。
- `installer.setup_main()`（setup exe 入口）里 `ZBOX_AUTO_INSTALL` 是静默安装测试钩子。
- **没有系统托盘图标**（已移除）：显隐/新建格子/设置/关于/退出等入口全在桌面右键级联菜单，
  别再往回加托盘。设置窗口是**非模态**的（桌面右键「设置」），已开着就 `raise_()`，不会叠第二个。
  传输分支的托盘气泡通知通道因此整体不合并：传输服务起不来（端口被占）靠传输页门禁层的「不可用」提示呈现；
  收到文件请求时 `_transfer_notify` 改为唤起面板并切到传输 tab（接收确认是独立置顶小弹窗 `_RecvDialog`，记录同时进传输页记录区），
  「传输完成」等纯通知在传输页记录区可见。需要 Windows toast 通知的话另行加（AUMID 已设 `Zbox`）。

### 崩溃诊断与日志

⚠️ **PyQt5 里槽函数中未捕获的异常会让进程直接 abort（qFatal），不是打个日志就完事**——实测无自定义
excepthook 时 exit 127、连输出都没有。`main()` 里那句 `sys.excepthook = _debug_excepthook` 正是挡这个的
（改成落盘 `debug_due.log`，程序继续跑）；它的注释写着「定位后移除」，但**删掉它 = 任何槽里的异常都会
静默崩掉整个面板**，要删先确认有别的兜底。反过来说，它也把这类 bug 变成静默的了：后台更新那次
`hstore.merge` 漏写实现，在应用里只会静静地不更新，是离屏脚本才把它揪出来。

日志与诊断手段一览：

- `debug_due.log`（`%APPDATA%\zbox\`）：Python 层未捕获异常，excepthook 始终落盘。
  **ctypes 回调（如 WH_MOUSE_LL 的 `proc`）里的异常不走 excepthook**——被 ctypes 吞掉打印到
  pythonw 不可见的 stderr，还会向系统返回垃圾值；所以 `boxes.py` 的 `proc` 自带 try/except
  落盘同一文件（带 `--- DesktopClickHook ---` 标记）。
- `crash_native.log`（同目录）：`main()` 里 `faulthandler.enable()` 落盘 Qt/C++ 层原生崩溃
  （访问冲突直接杀进程时，Python 堆栈的唯一痕迹）。
- `zbox_debug.log`（`%TEMP%\`）：`ZBOX_DEBUG=1` 时 `_dbg()` 埋点日志（run.cmd 常开，
  自带 2MB 轮转），只记滑动/悬停/tick 等埋点，不含崩溃堆栈。
- **进程冻结但没崩**：`py-spy dump --pid <pid> --native` 直接抓所有线程的 Python + Qt 混合栈
  （2026-09 靠它实锤了钩子线程 winId 死锁，见下方格子章节）。

### 面板（`app.py`）

`FloatingPanel` 是无边框**不透明**顶层窗口：不用 `WA_TranslucentBackground`（分层窗口禁用
ClearType，文字发灰），圆角靠 Win11 DWM，Win7/10 降级为圆角遮罩（`round_corners`）；
也不用 `QGraphicsDropShadowEffect`（Qt5 下破坏顶层窗合成），所以 `SHADOW = 0`、无阴影留白。
（`FloatingPanel.__init__` 里那句「阴影改为 paintEvent 手绘」是旧注释，类中已无 `paintEvent`。）

- **`QStackedLayout` 必须先挂父控件再 `addWidget`**：第一个页面会立刻成为当前页被 `show()`，
  无父状态下闪出一个默认大小的顶层白框（2026-10 建格子白闪的根因，`boxes.py` 的 `pages`
  踩过这个坑，要先 `addLayout` 进父控件再添加页面）。
- 内容区是 `_SlideStack`（横向滑动切页动画）：日历/待办/传输三页**按 tab 顺序入栈**——
  `slide_to` 靠页面在列表里的先后判断左滑/右滑，顺序错了方向就反。
- 尺寸常量 `SINGLE_W / PANEL_H`；`cfg` 键：`theme` / `tab` / `pos` /
  `off_noon` / `off_evening` / `shot_hotkey`（截图热键，空串 = 不启用），`Config` 用 `__getattr__` 暴露为属性。
- **桌面格子模式**：窗口标志是 `FramelessWindowHint | Tool`，**故意不带 `WindowStaysOnTopHint`**
  ——面板就该被别的窗口正常盖住，别再顺手加回去。
- **顶部栏默认收起**（`_slide_titlebar`）：栏窗高度 0↔`sc(42)` 做动画，靠 `_set_tb_height` 把它摆到
  面板顶边**上方**（`y = self.y() - h`）实现「向上滑出」，主窗口不动。进入面板（`enterEvent`）展开；
  离开后等 150ms 用 `_check_hover()` 看光标落点再决定收不收（光标从面板挪进展开栏会先触发面板的
  `leave`，不等这一拍就会抖）。栏内布局 = tab 按钮组 + 最右「齿轮」+「最小化」按钮（`gear_btn`
  '⚙' / `min_btn` '—'，共用 `#minBtn, #gearBtn` 样式，两主题各一条）：齿轮发 `settingsRequested`
  信号弹设置窗（非模态去重在入口 `open_settings`）；最小化走 `close_panel()` 收起整张卡片
  （栏窗随面板一起收），再显示走既有通道（桌面右键 / 双击桌面 / 再跑一次 run.cmd 的 `--toggle`）。
  注意 `#closeBtn` 不是面板顶部栏的旧残留——它是设置窗/关于窗/日期弹层等弹窗关闭按钮的
  活样式（hover 变红），别当死代码删。
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
「下载并导入」走同一条通道，手动路径的结果经 `ui.show_toast_on(win, text, ok, hold_ms)` 在**触发按钮
所在窗口**的正中央反馈（托盘已移除的替代通道，细节仍写调试日志 `_dbg`）：toast 是该窗口的子控件，
单行胶囊居中淡入停留淡出，`ok=False` 失败配色，状态存放在 win 上各窗口独立；调用方经 `toast_win`
透传目标窗口（设置窗/导入窗都传 `self`），窗口已关闭则回落面板。设置窗「联网更新」、导入窗
「下载并导入」/「选择文件导入」都走它。

日历格子右上角的「休」/「班」角标：只标法定节假日（`kind == 'off'`）与调休上班日（`kind == 'work'`），
**普通双休日不标**（双休只靠日期数字的弱化配色区分）。角标是 `DayCell.badge` 这个 QLabel，文字与配色
全由 `#badge[kind=…]` 的 QSS 给，摆位在 `DayCell._place_badge`——单栏一格只有约 43px 宽，尺寸必须靠
`adjustSize()` 自适应、且不能加 padding，写死尺寸或留内边距都会压住 19px 的日期数字。

### 系统集成（`sysutil.py` + `installer.py` + `install.py`）

- 注册表写入默认走 HKCU（**免管理员**，Win7/10/11 通用）；`all_users=True` 才写 HKLM
  （exe 安装向导的「此计算机」选项，需管理员）。清理函数对两个根都尝试、无权限时静默跳过。
- **命名统一为全小写 `zbox`（2026-10 从 `zviber` 改名）**：程序本体 `zbox.exe`、
  安装目录（`%LOCALAPPDATA%\Programs\zbox` / `Program Files\zbox`）、安装包
  `zbox-Setup-v<版本>-<架构>.exe`、注册表键、单实例 IPC 名都跟着换。**改名前的兼容代码别当冗余删**：
  `installer.LEGACY_APP_EXE`（`_check_dir` 与覆盖重装要认旧 exe）、`sysutil.LEGACY_SHELL_KEY` /
  `LEGACY_UNINSTALL_KEY` / `legacy_integration_remove()` / `legacy_uninstall_reg_get()`
  （旧右键菜单与旧卸载项要清掉，否则「设置→应用」里会同时躺两个卸载项）、`autostart_remove()`
  顺带删旧名 Run 值、`installer._take_over_legacy()`（安装时接管并删掉旧安装目录）。
  **IPC 名重新起为 `zbox-panel-v1`**（旧版 zviber 用 `zviber-panel-v2`）：新旧版数据目录与注册表会互相覆盖，
  让它俩互不串话（各起一个实例）比新旧混用一个安全。
- 涉及的键：`Run`（自启）、`Directory\Background\shell\zbox`（桌面右键菜单）、
  `Directory\shell\zbox`（文件夹右键「添加到zbox桌面格子」，仅运行中注入，安装不写）、
  `Uninstall\zbox`（应用列表卸载项）。
- **桌面右键菜单只属于 exe 安装**：只有 `installer.install()` 会写菜单，`install.py` 只写开机自启。
  每次启动 `installer.sync_context_menu()` 按 `Uninstall\zbox` 的 `InstallLocation` 判定——
  没有任何安装记录就清掉菜单残留（旧版 install.py 的源码安装、向导取消、半卸载）。**调用时机必须在 IPC 转发之后**——源码模式没有安装记录，转发进程（`--new-box` 等）若先跑这步会把运行中面板刚注入的级联菜单当残留删掉（真实 bug）。`context_menu_remove` 要自底向上清三层子键（winreg 不能删带子键的键），含旧版直链菜单的 `command` 残留。
- `sysutil.launcher_cmd()` 区分 frozen（直接启自身）与源码（优先 `pythonw.exe` 实现无窗口静默）。
- `installer.py` 的向导**只在 frozen 时生效**；源码运行走 `install.py`。
- 安装 = 把安装包内嵌的 payload（onefile 运行时解压到 `_MEIPASS\payload` 的 onedir 本体：exe + `_internal\`）**整体复制**到目标位置，按字节回报进度；目标目录已有旧安装（含 `zbox.exe`）时先整体清空再复制——`_check_dir` 只放行空目录/新目录/含 `zbox.exe` 的旧安装目录，别放宽这个签名判断，否则覆盖重装与卸载会误删用户文件。
- 卸载走与安装同风格的**卸载向导**（确认页 → 进度页 → 完成页）：确认页 checkbox「同时删除个人数据」勾选后连同 `%APPDATA%\zbox`（待办、格子、配置）一起 rmtree，默认保留；程序目录用延迟 `rmdir` 删除（exe 运行中删不掉自己）。

### 截图（`screenshot.py` + `pinshot.py`）

- **会话**：`ShotOverlay` 是覆盖虚拟桌面的无边框置顶 Tool 窗，构造时**先逐屏
  `grabWindow(0)` 抓底图再显示**（顺序反了遮罩自己会入镜）。灰罩 = 底图上盖
  `MASK_COLOR`，选区镂空 = 裁剪选区把底图再画一遍——不用 WA_TranslucentBackground。
- **键盘**：全屏 Tool 窗未必拿得到焦点，遮罩与长图控制条都在 `showEvent` 里
  `grabKeyboard()`（Esc/Enter/Ctrl+Z 才可靠），`closeEvent` 里配对 release。
- **标注**：shapes 列表（rect/ellipse/text × 颜色 × 档位 × invert），QPainter 画在
  底图副本上；导出时按选区矢量重绘一遍（dpr 取覆盖屏幕最大值），撤销 = pop。
- **主题**：调色板 `PALETTES` 按 `resolve_theme(cfg.theme)` 二选一（nocturne 琥珀 /
  mica 蓝），工具条 QSS 现拼，不进 themes.py 的面板 QSS 体系。
- **全局热键**：`HotkeyManager` 用 `RegisterHotKey(HWND=None)`（走线程消息队列，
  不占钩子线程）+ `QAbstractNativeEventFilter` 收 `WM_HOTKEY`；空串 = 不注册，
  裸键只放行 F1-F12/PrintScreen；设置窗修改后 `apply()` 即时注销重注册，
  失败文案显示在设置窗「截图」行右侧。
- **截长图**：进长图模式**必须 hide() 遮罩**（否则抓帧抓到的是遮罩自己），
  之后由用户自己滚动页面（滚轮自然落在目标窗口），280ms 定时器抓选区帧，
  用灰度行签名 `_row_sig` 找纵向位移拼接；匹配失败（动画/跳变）只提示不硬拼。
  `_row_sig` 里 `bits().asarray()` 的对象不支持步长切片，要先 `bytes()` 转换。
- **钉图**：`PinWindow` 置顶 Tool 窗，**故意不挂桌面带**（挂带会被应用窗口压住，
  贴图的意义是浮在最上面）；拖拽移动、双击关闭；不持久化，进程退出即消失。

### 桌面格子（`boxes.py`）

桌面文件归类格子：`BoxManager` 总管（恢复/新建/解散/显隐），`BoxWindow` 单格，
`BoxStore` 存 `%APPDATA%\zbox\boxes.json`（`visible` + 格子记录列表）。
格子管理入口在桌面右键级联菜单（新建格子 / 新建文件夹格子 / 显示隐藏格子）；截图自检模式不创建格子。
另有**资源管理器文件夹右键「添加到zbox桌面格子」**（`Directory\shell\zbox` 静态动词，
`--add-folder "%1"` 传路径）：仅运行中注入（随 `context_menu_set_running` 与桌面级联菜单同生共死，
退出/卸载/覆盖安装时随 `_delete_shell_tree` 一并删除，崩溃残留被点到静默退出），路径经 `b'folder:'`
IPC 通道（与 `--pick-folder` 同一条）发回面板建格子；`new_folder` 按 normcase 去重——同一路径
已有格子不新建，改为显示出来并 `flash()` 透明度闪烁提示（「新建文件夹格子」对话框路线同样去重）。

- **格子内容两种视图**（标题栏 ≡ 菜单「查看」组，`rec['view']` 持久化，与排序组并列）：
  按列表（默认，ListMode + 16px 图标）/ 按图标（IconMode + 32px 图标 + 固定网格
  sc(84)×sc(72) + 名称两行折行）。QSS 里固定行高/左 padding 只对列表生效——
  选择器是 `QListWidget[view="list"]::item`，切换走 `BoxList.set_view`（改 `view`
  动态属性后 unpolish/polish 重刷），直接 setViewMode 不改属性会留着列表行高把图标格压扁。
  - **图标视图必须切 ScrollPerPixel**：IconMode 下默认 ScrollPerItem 的滚轮步进极小
    （滚很久只动一点），set_view 里顺带 `verticalScrollBar().setSingleStep(sc(24))`
    （一 notch ≈ 一格高）；切回列表恢复 ScrollPerItem。
  - **缩放卡顿是半透明分层窗口的结构性成本，别轻易再试「优化」**：格子是
    `WA_TranslucentBackground`，每次 resize = 布局 + CPU 光栅化全帧 + 整帧 ARGB
    上传 DWM（Qt5 不吃 GPU），而 move 零重绘所以拖动丝滑（实测 1.4-1.8ms vs 0.23ms）。
    2026-10 试过帧合流（8ms 定时器合并 mousemove）与双击当 press 修复，用户实测
    仍有行为问题，已整体回退——缩放维持每个 mousemove 直接 `_apply_resize` 的原始
    实现。两个相关事实备查：① 500ms 内的第二次按下 Qt 发 `MouseButtonDblClick`
    而非 Press（快速两抓时整次抓取无 `_op`，目前按原样保留）；②
    `QWidget.mouseDoubleClickEvent` 默认转发 `mousePressEvent`，收起格子后 `_op`
    残留一个 move 即来源于此，松手收尾无害。
- **层级策略（踩坑三轮后的终态）：挂桌面带（`pin_to_desktop`，免疫 Win+D）
  + 永不主动沉底 + 被桌面整理表层压住时由 WinEvent 钩子/看门狗抬回。**
  带内窗口点击激活会浮到应用窗口之上（实测确认），只要不主动 sink 它就一直在，
  这就是「格子永不消失」的关键——沉底（sink_to_desktop）只用于「被表层压住」的抬回。
  ❌ 不要学面板在失焦时沉底：格子会被拖到任何位置，沉到应用窗口之下 = 用户眼里的消失。
- **看门狗必须极廉**：每 tick 只做一次中心命中（`_covered_by_surface`），真被压住才跑
  `probe_desktop` 找锚点。probe 的多点 WindowFromPoint 是跨进程同步调用，命中无响应窗口
  会阻塞主线程——曾因每 500ms × 4 格子 × 6 点探测把界面打到转圈假死。
- **空白格子只是桌面文件的收纳视图，不搬动文件**（2026-10 改，四个用户实测 bug 的根因）：
  拖入 = 把文件记进 `rec['items']` + 给它加「隐藏」属性把桌面图标藏起来（文件仍在桌面原路径，
  右键属性的位置就是桌面）；关程序（`BoxManager.shutdown`）/ 解散格子 / 显隐格子
  （`set_boxes_visible`，双击桌面的 `toggle_all` 也走它）隐藏时用 `show_icons()` 还原属性，
  文件随即回到桌面。分组记录留在 `boxes.json`，
  下次启动 `restore()` 再 `hide_icons()` 收起来——「程序开着=文件在格子里，程序关着=文件在桌面」。
  - 旧版是把文件真 `shutil.move` 进 `%APPDATA%\zbox\Boxes\<id>\`：用户实测「属性里
    路径变成 AppData」「关程序后文件被吞在里面」，故改成现在这样。`_upgrade_blank_boxes()`
    在启动时把旧存储目录里的文件搬回桌面并转成 `items`（搬空才删目录）。
  - 不在桌面的文件拖进来会先搬到桌面（「格子里的文件都在桌面」是这套模型的前提）。
  - 隐藏机制只有「文件的隐藏属性」这一条路（资源管理器没有单项隐藏的 API）：
    `_hide_icon` 记下原属性到 `rec['attrs']`，`_show_icon` 按原值还原；改完必须
    `SHChangeNotify(SHCNE_UPDATEDIR, SHCNF_PATHW|SHCNF_FLUSH, 桌面)`（`_shell_refresh`），
    实测图标显隐 30-50ms 生效——不刷的话图标要过一会儿才消失（用户报的「有延迟」）。
    坑：① 若用户开了「显示隐藏的文件」，图标不会消失；② 属性会跟着「复制/剪切」走，
    所以拖出前先把隐藏位摘掉（`stage_for_drag` 里做的），宿主侧对 cut/copy/link
    动词也先摘隐藏位（见「格子文件右键」）；③ 面板被强杀（任务管理器 / 崩溃）时图标留在
    隐藏状态，下次启动会重新收进格子，一致但需要知道这一点。
  - **释放后图标落点要修正（`_DesktopIconLayout`，2026-10 用户报障）**：还原隐藏属性后，
    重新出现的图标由 Explorer 自行摆位——落在第一列从上往下第一个空位（用户眼里就是
    「跑到屏幕最左上角」）；桌面满员时还会把原有图标挤下去，而被挤的图标**不会回弹**
    （位置记忆当场被改写），再开程序也救不回来。`show_icons()` 因此改成：释放前
    `snapshot()` 快照全图标位置 → 还原属性+`_shell_refresh` → `fixup()` 轮询等新图标
    出现（**SHCNF_FLUSH 只是把通知投进 explorer 队列**，图标进 ListView 实测有 0~0.6s+
    延迟，必须轮询）→ 新图标 `LVM_SETITEMPOSITION` 挪到末尾行（快照最后一行之下另起一行，
    必是空行不挤人；贴屏幕下沿则塞末行最右图标之后）→ 被挤的原有图标按快照摆回
    （连锁错位两轮内收敛：每摆正一个就腾出一个空位）。
    实测依据（Win11 自由摆放桌面）：SET 到已占用位置 = 占用者被挤到下一空位（这就是
    「挤」的机制本身）；SET 到空位附近的坐标会被吸附到最近网格位（目标位置按
    `LVM_GETITEMSPACING` 网格估算即可，不必精确）。枚举是跨进程
    `LVM_GETITEMTEXTW`/`LVM_GETITEMPOSITION`（结构体开在 explorer 地址空间，与
    `_desktop_icon_at` 同一套）；SET 不用跨进程内存（lParam 直接打包坐标）。
    坑：① **自动排列（LVS_AUTOARRANGE）的桌面不插手**——位置全由排序规则决定，SET 会被
    立刻重排掉；② 枚举到的名字是**显示名**，系统「隐藏扩展名」时无扩展名——匹配全名
    优先、主名兜底，撞名（同主名不同扩展名）挑「位置不在快照里」的新项；③ shutdown 时
    多个空白格子各跑一次快照+修正，后跑的快照含先跑已挪好的图标（SET 回原位=无操作），
    幂等不用改。
  - **拖出 = 先把文件挪进桌面下的隐藏暂存夹 `桌面\.zbox\`（`stage_for_drag`）**：
    格子里的文件本来就在桌面上，直接拖到桌面就是把文件移动到它自己所在的目录 ——
    资源管理器会弹「源文件名和目标文件名相同」（用户实测）。挪进同盘的隐藏子目录后，
    拖到桌面 = 一次真实的跨目录移动（文件回到原路径），拖到资源管理器文件夹/别的格子
    也都正常。`finish_drag_out` 收尾：暂存文件还在 = 没搬走（取消拖拽/拖回格子）→ 搬回
    原路径继续藏着；暂存文件没了 = 被搬走了 → 从 `items` 里去掉（拖到桌面即「移出格子」，
    图标不再隐藏）。拖拽期间 `self._dragging` 有值：`refresh()` 直接返回（不然重建列表会把
    拖拽源那一行清掉）、`_entries_from_items()` 按暂存路径确认文件还在。暂存夹空了立刻删掉
    （桌面上不留目录），拖拽途中被强杀留下的残留在启动时由 `_upgrade_blank_boxes()`
    （内部 `_recover_files`）搬回桌面并补进记账。映射格子不参与这套（文件在别处）。
  - 拖到别的空白格子 = 换归属（`ungroup_paths`）；格子里改名要同步 `items`/`attrs` 的键
    （`rename_item`，否则文件会「藏着但不在任何格子里」）。
  - **落放效果（鼠标旁那个徽标）分两步，别混为一谈**：OLE 里徽标由 **DragOver** 报回的效果
    决定，而「源方要不要清理源文件」只看 **Drop** 报回的效果（`IDropTarget::Drop` 的
    `*pdwEffect`）。所以：
    - `drag_effect()`（悬停）**一律报 MoveAction** → 徽标显示「移动」。这与「文件被收进格子」
      的直觉一致，也是 DeskGo 那种「移动到 <格子名>」的观感；
    - `drop_effect(paths)`（落放）**按实际结果**回报：源文件都不在原处了才算 Move，否则 Copy。
    ⚠️ 绝不能把 **Drop** 一律报成 Move：报 Move 而文件仍在原处时，资源管理器会认为移动已完成、
    **把源文件删掉**（实测：探针回报 Move 不搬文件，桌面上的源文件当场消失；Qt 源码里那句
    `CFSTR_PERFORMEDDROPEFFECT` 也拦不住它）。实测组合「悬停 Move + 落放 Copy」：徽标写「移动」，
    源文件安然无恙、原地不动。
    为什么桌面文件拖进空白格子只能这样：文件本来就在桌面上、原地不动，报 Drop=Move 会被删，
    报 Drop=Copy 又只剩「复制」徽标；解耦之后徽标与文件实际去向各归各的。
    回归工具 `%TEMP%\dsh_badge_e2e.py`（真机从桌面图标拖进空白格子：抓徽标 + 校验源文件还在、
    图标被隐藏、进了记账、无错误框）。
- **映射格子只读目录**、`QFileSystemWatcher` 300ms 去抖刷新；路径失效显示「解散格子」页。
  空白格子也挂同一个 watcher，但看的是桌面目录（外面的删除/改名/剪切粘贴都要跟着刷新）。
- **整窗接受拖放（`BoxWindow.setAcceptDrops(True)` + `dragEnter/dragMove/dropEvent`）**：
  只有文件列表视口注册了拖放目标，拖到标题栏/空白提示区/边缘时 Qt 的 `findDnDTarget()`
  从光标下的控件往上找到窗口为止，窗口自己不接受就返回空 → **整个拖拽被忽略**，用户看到的
  就是鼠标变成红色禁止图标、怎么都放不进去（收起状态整格只剩标题栏，更是必然放不进去）。
  别只把列表当拖放目标，窗口这层必须接住。
- **拖放的前提是进程里 OLE 已初始化（STA）**：`main.pyw` 入口那句
  `CoInitializeEx(None, 0x2)` —— ⚠️ **`COINIT_APARTMENTTHREADED` 是 0x2，不是 0**
  （0 = `COINIT_MULTITHREADED`）。2026-10 用户报的「拖不进格子、鼠标变红色禁止图标」的
  **真身就是这个 0**：它把 GUI 线程定成 MTA，Qt 随后的 `OleInitialize()` 必然失败
  `RPC_E_CHANGED_MODE`（run.cmd 启动时 stderr 里那句警告），于是 `RegisterDragDrop`
  全线失败——**进程里所有窗口的拖放目标都没注册上**，往格子里拖什么都是禁止光标（跟
  「拖到哪个位置」「窗口是不是在列表上」都无关）。判据：`RevokeDragDrop(hwnd)` 在 MTA 下
  返回 `DRAGDROP_E_NOTREGISTERED`、STA 下返回 `S_OK`（一次性小实验即可判定）。
  `setup.pyw`、`_shell_invoke_async` / `_shell_exec_async` 里同样的初始化也都写 0x2。
  另注：OLE 没初始化时**从格子往外拖也拖不动**（`DoDragDrop` 起不来），注入式拖拽脚本
  会表现为「Qt 的 startDrag 跑了但目标收不到任何 DragEnter」。
- **解散格子有二次确认**（`BoxConfirmDialog`：无边框 Tool 窗，结构仿面板「关于」窗，
  视觉沿用格子的深色磨砂圆角，空白/映射格子提示语不同）。`QMessageBox` 只还剩删除确认在用，
  `_box_qss` 里给它补了深色底——白字落默认浅色底会看不清。
- **双击标题名称 = 原地内联重命名**（QLineEdit 替换 QLabel，回车/失焦提交、Esc 取消；
  事件在过滤器里吃掉，不再触发双击收起）。映射格子点左上角文件夹图标 = 打开所在文件夹
  （eventFilter 里按下即开，双击/松开都吃掉防连带拖动与收起）；**空白格子标题栏不显示图标**
  ——它背后没有对应的文件夹，图标只是无意义的点缀（`self.icon.hide()`，隐藏控件不占布局位置，
  标题栏只留名称）；映射格子照旧显示文件夹图标。
- **视觉固定深色磨砂**，不挂主题系统。`WA_TranslucentBackground` 的 ClearType 问题这里接受
  （参考软件本身就是半透明）。**半透明窗口 show 的首帧会闪一帧白屏**（paint 未跑先合成），
  `_spawn` 里先 `setWindowOpacity(0)` 隐身、120ms 后再现身（同时盖住挂带 SetParent 的隐藏-重现）。
- **双击桌面空白显隐**（`BoxManager.toggle_all`）：桌面图标 + 全部格子 + 面板一起显隐，
  图标显隐 = ShowWindow 桌面的 `SysListView32`（`find_desktop_listview` 定位，Progman
  找不到再扫 WorkerW）。`DesktopClickHook` 独立线程**轮询左键**（GetAsyncKeyState 每 10ms，一次按下两条路都认：低位 0x0001「距上次调用以来按下过」+ 高位 0x8000 由松到按的沿——只看高位沿时触摸板轻点/快速点击可整个落在轮询间隔里被漏掉，双击显隐就「有时不灵」；只看低位又会被别的进程调 GetAsyncKeyState 抢读，故二者互补）；**重启线程靠 `run()` 开头清 `_stop`**——stop() 置位后不再清的话，设置里关一次再打开，start() 重进 run() 立即退出，双击功能永久失效直到重启程序）
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
- **格子文件右键 = 系统外壳菜单**（`shell_context_menu`，与资源管理器逐项一致）：
  走常驻宿主 `native\zshell_host.exe --serve`（面板启动即拉起并预热壳扩展 DLL，
  每次右键只是管道写一行请求——单次起进程 + 重载壳扩展有 ~500ms 延迟）；
  请求/响应按 FIFO 配对（退出码 2 = 重命名，回调 `BoxList._rename_item`）。
  去重只对【在途】请求生效（一次物理右键可能经 TPM_RECURSE 转发与 DefWindowProc
  两条路径各来一次）——上一菜单已关闭后的同项右键是合法的重定向连击，用时间窗
  去重会把它吃掉（「首次右键不弹、第二次才行」的成因之一）。看门狗：在途 15s+
  还有新请求 = 宿主卡死（菜单开着时用户再点右键会先经 TPM_RECURSE 取消旧菜单、
  R 必然已回，故正常弹窗不可能命中），杀掉重启自愈，宿主与它弹的菜单一起消失、
  前台与输入随即释放。`_read_loop` 不在读线程清 callbacks（与 GUI 线程共享无锁，旧读线程
  会误清重启后的新回调），改由 `ensure()` 重启前在 GUI 线程清。
  宿主缺失回退 ctypes 实现（`CDefFolderMenu_Create2`，少 Defender 扫描等宿主型扩展项）。
  **为什么必须是独立 exe**：Defender 的 EPP 扩展（{09A47860-...}）检查宿主进程，在真正的
  python.exe 进程里 `QueryContextMenu` 返回成功但一项不加——已逐项排除 exe 名/路径/
  版本资源/签名/清单/加载 python312.dll，只有真 python 进程被拒，原生 exe（含改名
  python.exe 的）全部正常；逆向还发现腾讯桌面整理（Features64.dll）用的是
  `CDefFolderMenu_Create2`（shell32 序数 701）老路径，它的格子菜单同样没有这类项。
  **菜单构建契约（zshell.cpp，实测得出）**：shell32 序数 335=`SHCreateDataObject`、
  336=`SHCreateDefaultContextMenu`（Explorer 同款；DEFCONTEXTMENU 尾部可带
  IDataObject/站点字段）→ 对菜单对象 `IObjectWithSite::SetSite`（最小
  IOleWindow+IServiceProvider，QueryService 全 E_NOINTERFACE 即可）——**这是 EPP
  加项的唯一前提**，站点为 NULL 时 EPP 初始化成功但 0 项 →
  `QueryContextMenu(CMF_EXPLORE|CMF_CANRENAME)`。336 已合并 progid 动词、*\shell
  动词、IExplorerCommand 项（以 Notepad++ 编辑）与全部 shellex 扩展，**不要手工补**
  （补了就重复，任务早期按老路径写的硬编码补项已删）。
  其它坑：① 菜单图标靠 `WM_INITMENUPOPUP` 等消息转发 `IContextMenu3::HandleMenuMsg2`
  懒加载——TrackPopupMenu 属主用自建隐藏窗转发，不转发则多数项无图标；
  ② 宿主进程默认拿不到前台锁，菜单窗口收不到键盘（Esc/方向键/助记符全哑）——
  TrackPopupMenu 前 `AttachThreadInput` 挂到当前前台线程再 `SetForegroundWindow`，
  弹完还原焦点；③ 「重命名」动词没有文件夹视图不会生效——宿主以退出码 2 交回，
  Python 侧 `BoxList._rename_item` 行内编辑 + `os.rename`；④ 菜单随系统明暗 =
  uxtheme 135 序数 `SetPreferredAppMode`（深色 2 / 浅色 3）；⑤ 普通动词走 InvokeCommand，带
  `CMIC_MASK_UNICODE|CMIC_MASK_ASYNCOK`，hwnd 传格子窗口（删除确认框的属主）；
  ⑤-b **「属性」动词不能走 InvokeCommand**：壳是**另起线程**建属性框的，而那个线程要调用方
  公寓继续泵消息才建得出来，宿主弹完菜单就阻塞在 serve 的 `fgets` 上不泵消息 ⇒ 属性框一直不
  出现，直到用户下一次右键（TrackPopupMenu 内部泵消息）才补冒出来——用户实测原话「右键属性
  一直不弹，再右键格子里的别的文件，上一个属性框才弹出」。临时原生探针（属主窗分别用挂桌面带
  的窗口 / 顶层窗口 / NULL，三种都一样）实测：InvokeCommand 后不泵消息 2.5s 一个都不出；
  开始泵消息 531ms 出（属性框在**壳自己的线程**上，不在调用方线程）；改独立 STA 线程
  `ShellExecuteExW("properties")` + `SEE_MASK_ASYNCOK` 只要 79ms 出、完全不需要调用方配合。
  故宿主对 `properties` 动词特判走 `PropertiesThread`（多选时每文件一个框，放弃原来那条合并的
  「N 个项目」框，换确定性）。
  ⑤-c **cut / copy / link 动词先把文件的隐藏位摘掉**（`clear_hidden_bit` + `SHChangeNotify`）：
  格子文件是靠隐藏属性藏起来的，属性会跟着复制/剪切走——目标文件夹里那个文件也是隐藏的，
  用户会以为文件丢了。面板侧照旧记账，退出时按原值还原成同一个值，无副作用。
  回归工具 `%TEMP%\dsh_propmenu_test.py <宿主exe>`：驱动真宿主弹菜单 → 按菜单项矩形点「属性」
  → 测属性框出现时间（旧宿主：4s 不出、再弹一次菜单 0.08s 才出；新宿主：0.34s 出，宿主日志里
  有 `verb=properties -> 独立 STA 线程弹属性框`）。
  ⑥ 菜单位置自己 `GetCursorPos`（物理坐标）——Qt 传过来的 globalPos 是逻辑像素，
  多显示器/缩放下不可靠；宿主入口必须声明 DPI 感知（PM_V2），否则菜单被系统按 96 DPI 渲染再位图
  放大（字体发糊）——但 `SetProcessDpiAwarenessContext` 是 Win10 1703 才加的导出，
  **静态调用会让老 Win10（10240/10586/14393）与 Win7 在进程加载阶段就弹
  「无法定位程序输入点」整个起不来**，必须 `set_dpi_awareness()` 里 GetProcAddress
  逐级回退：1703+ SetProcessDpiAwarenessContext(PM_V2) → Win8.1/1607-
  shcore!SetProcessDpiAwareness(PER_MONITOR) → Vista/Win7 SetProcessDPIAware；TrackPopupMenu 要给
  `TPM_RECURSE`——菜单开着时在别处再点右键，系统才会先关旧菜单再把
  WM_CONTEXTMENU 转发给落点窗口（资源管理器的「右键连击」），不给则第一次右键
  只关菜单不弹新菜单；`BoxList.contextMenuEvent` 取落点用
  `mapFromGlobal(QCursor.pos())` 而不是 `e.pos()`（Qt5 对 WM_CONTEXTMENU 的
  坐标在高 DPI 下不换算，e.pos() 会错位）；pythonw 面板 Qt 侧 dpr=1.0（2560×1600
  物理坐标系），而**未声明 DPI 感知的 python/PowerShell 探测脚本拿到的窗口矩形
  与光标都是 1/1.25 虚拟化坐标**——写界面探针时先 SetProcessDpiAwarenessContext；
  ⑦ ctypes 直调 335/336 必 access violation（读 0x1），这是必须 C++ 的原因之一；
  ⑧ 回退路径（ctypes `CDefFolderMenu_Create2`）的老坑仍在：菜单对象无站点时
  InvokeCommand 一律 E_FAIL（动词改走 GetCommandString 取动词名 + 独立 STA 线程
  ShellExecuteEx + SEE_MASK_ASYNCOK）、ahKeys 不能传（替换默认合并，扩展全丢）、
  壳默认菜单不合并 HKCU progid 动词与 *\shell 静态动词（回退路径手工补到顶部，
  图标用 ExtractIconExW + SetMenuItemInfo 的 `MIIM_BITMAP=0x80`，0x20 是 MIIM_DATA）；
  ⑨ 菜单必须在【右键抬起之后、且按键状态已清零】时才弹：`TPM_RECURSE` 是右键**按下**
  就把 WM_CONTEXTMENU 转发过来，而菜单在「按键仍按着」的状态下被创建会进入 KB 65256 的
  「按下跟踪」模式（原文：只在按住期间显示，一松手就消失、并按菜单语义选中光标下那项）
  ——菜单永远弹在光标处，于是首项「打开」被直接执行（真实 bug：A 菜单开着右键 B，B 被打开）。
  两道防线，都在 `show_menu_once`：
  ① `wait_rbutton_up(1200ms)` 轮询 `GetAsyncKeyState(VK_RBUTTON)`（读的是物理按键当前状态，
     不需要消息泵；别用 GetKeyState——那是本线程队列里的状态，而 serve 正阻塞在 fgets 上）。
     **要调两次**：一次在建隐藏窗之前（等这次点击松开，菜单才出现在松手之后），一次
     **紧挨着 TrackPopupMenu**——中间那串动作（建隐藏窗 / 取坐标 / 排干队列）要十几到几十
     毫秒，用户完全可能在期间又按下去。
  ② 紧挨 TPM 处调 `clear_button_keystate()`（`GetKeyboardState`/`SetKeyboardState` 清掉
     VK_RBUTTON/VK_LBUTTON）——KB 65256 的官方 workaround，清掉后菜单**不再看**按键状态，
     这才是**确定性**的一刀（单靠等待总有残余窗口：按下可能落在等待返回之后、TPM 内部建
     菜单之前）。Win11 是否仍读这份线程键盘状态未实测，所以①留着。诊断看宿主日志的
     `wait_rbutton_up=` / `pre-tpm recheck waited=` 行。
  ⑨-b **「菜单卡住 + 后面请求排队、再一个个顶上来」的真身：右键落在菜单自身上（2026-10 定案）**
  ——用户原话：「弹出一个菜单项后，再右键点击其他项目，上一个菜单项不会消失，也不会弹出新的
  菜单项；点空白处或选它里面某一项，就会陆续自动弹出一些新的菜单项，感觉好像第一个菜单卡住了，
  后面几个都在排队等着渲染」。机制：菜单弹在第一次右键处、向右下展开，连点列表时后几次点击
  正好落在**菜单矩形内**，而 `TPM_RECURSE` **只转发菜单外**的右键 ⇒ 落在菜单内的被菜单自己吞掉，
  既不关菜单也不产生新请求 ⇒ 面板照发的请求全堵在管子里排队 ⇒ 菜单终于关掉后一个个顶上来。
  **对策（就是桌面整理/资源管理器的「右键连击重定向」）**：`MenuInputProc` 里判断右键是否落在
  **我们自己线程的菜单窗（`find_own_menu()`，class `#32768`）**矩形内——是则吃掉该按下并
  `PostMessage(ZM_ENDMENU)` 关掉菜单，随后由 `show_menu_once` 在 **TPM 之后**给调用方
  （格子列表）补发 `WM_CONTEXTMENU`，面板就会为**光标下那一项**重新弹菜单。
  ⚠️ 补发必须在 TPM 之后、主代码里做：EndMenu 让 TPM 立刻返回、钩子随即卸掉，而用户松手在那之后、
  且线程立即回到 fgets 不再取消息——钩子里永远等不到那次抬起（实测丢，重定向就没了）。
  另注：落在菜单上的**右键**本来就不会激活菜单项（TPM 未带 `TPM_RIGHTBUTTON`），
  真正会激活的是**左键**——用户为了解开卡住的菜单去点某一项，就是那次「文件夹被打开」的来源；
  点文件不动只是因为点到的不是「打开」那类动词。
  回归工具：`%TEMP%\repro_menu_click.py`（弹菜单 → 注入输入 → 读宿主日志的 `cmd` 与调用方收到的
  `WM_CONTEXTMENU` 次数），四模式：`inside`（右键落在菜单上 → **必须关掉 + 调用方收到 ≥1 次
  重定向**）/ `outside`（点菜单外 → **必须关掉**）/ `key`（注入 'O' → **cmd 必须 0、菜单关掉**）/
  `left`（左键点项 → 正常选中，阳性对照）。2026-10 定稿四项全过；`inside` 与 `key` 分别是
  「没有重定向」和「没有键盘拦截」时会挂的那两项。注意 `outside` 依赖注入点落在菜单外，
  菜单几何随光标变化，偶尔会落进菜单里而误判，别只跑一次。
  ⚠️ **别再用全局 WH_MOUSE_LL 钩子**：2026-10 试过一版（专职泵消息线程 + 400ms 延时卸钩 +
  回调里做 EnumThreadWindows/GetWindowRect/WindowFromPoint），既没修好（抬起照样漏给菜单）
  又把局部时序问题升级成全系统输入故障。对照腾讯桌面整理 Features64.dll 的做法：它用的是
  **线程级** `SetWindowsHookExW(WH_GETMESSAGE, proc, NULL, GetCurrentThreadId())`（另一处
  WH_CBT）+ `SetCapture`，句柄缓存装一次、不随菜单装卸，作用域不出本进程——要复刻「菜单内
  右键重定向」就走这条线程级路线（注意 WH_GETMESSAGE 的钩子**不能靠返回非零丢消息**，
  正规做法是把 MSG 改成 WM_NULL）。
  ⑩ TPM 前必须排干线程队列里积压的鼠标/WM_CONTEXTMENU 消息——serve 循环平时阻塞在
  fgets 不泵消息，上一次菜单经 TPM_RECURSE 转发给属主窗的右键消息一直积压，下次 TPM
  一上来就捞到它、按 TPM_RECURSE 语义立刻取消自己（实测 0ms 闪现取消、Win+D 后首次
  右键不弹的根因）；闪现取消的兜底重试**已删除**：主因由排干解决，而两条守卫候选都不
  成立（「右键是否按下」是空守卫——等待已保证键是抬起的；「管道里还有没有新请求」被
  serve 的 `fgets` 预读挡住，CRT 缓冲里的请求在管道句柄上查不到）。别再往回加盲重试。
  ⑪ **前台锁必须留着，但顺序必须是「先恢复前台、再销毁隐藏窗」**：菜单要能被「点别处」
  关掉/切换、能被 `TPM_RECURSE` 转发，靠的是它持有鼠标捕获，而**捕获只对前台线程生效**
  ——实测：完全不动前台时，点在菜单外的鼠标事件直接进了别的应用，菜单收不到、关不掉。
  所以 `show_menu_once` 保留 `AttachThreadInput + SetForegroundWindow(hhidden)`（配
  `ThreadInputAttach` 作用域守卫配对；前台线程已挂起则不 attach）+ 弹完恢复前台。
  **顺序反了会出事**（2026-10 我自己踩的）：先 `DestroyWindow(hhidden)` 再恢复 ⇒ 那一刻
  本进程已不是前台进程 ⇒ `SetForegroundWindow` 资格丢失 ⇒ 恢复必然失败 ⇒ 前台变 NULL ⇒
  下一个菜单**拿不到捕获**（没有可 attach 的前台线程）⇒ 点菜单外关不掉 ⇒ 菜单卡住、后续
  请求排队（⑨-b 那串现象）。正确顺序：**恢复前台 → 再销毁隐藏窗**。
  前台恢复失败时：`GetShellWindow()`（桌面）与任务栏 `Shell_TrayWnd` **都置不上前台**
  （实测 ok=0），别白费劲兜底；但**前台为 NULL 是可自愈的**——没人占着，下一个菜单的
  `SetForegroundWindow` 反而能成功。日志里 `restore fg to … (class=… tid=… attach=…) failed`
  会打出目标类名，方便判断当时前台是不是我们自己的桌面带窗口（那种窗口本来就不该被当作
  可恢复的前台）。面板侧授权只给宿主 pid（`AllowSetForegroundWindow(self.proc.pid)`），
  **绝不用 ASFW_ANY**。
  宿主诊断：`ZSHELL_LOG=1` 落盘 %TEMP%\zshell_host.log（每请求的 `wait_rbutton_up=` /
  `pre-tpm recheck waited=` / `tpm cmd=… elapsed=… btnR=…`）；面板 `ZBOX_DEBUG=1` 记
  `ctxmenu: R=… 用时=…s 在途=…`（按每个请求自己的发出时刻算；有请求没应答=宿主不健康）。
  排查「误激活」时 `tpm cmd≠0` 就是「有项被执行了」的判据（cmd=0 既可能是用户取消、
  也可能是正常关闭），`elapsed` 是菜单存活时长——空放很久的菜单突然返回 cmd，八成是键盘。
- 列表里 `.lnk` / `.url` 显示名去掉后缀（对齐资源管理器），UserRole 仍存完整路径，拖出/打开不受影响；`.url` 图标走 `_url_icon`：解析文件里的 `IconFile`/`IconIndex` 用 `ExtractIconExW` 取（大小两档），`QFileIconProvider` 不读 IconFile、只给空白页图标；`QtWin.fromHICON` 必须传 int 句柄，传 c_void_p 得空图；取不到回落 provider
- **双击只认左键**：`BoxList.mouseDoubleClickEvent` / `BoxWindow.mouseDoubleClickEvent` 开头都对
  非左键早退。原因：**Qt 对右键也发双击事件**（实测：同一位置两次右键、间隔 <500ms 即触发
  `itemDoubleClicked`；位移 ~40px 以上不触发），而 `BoxList` 把 `itemDoubleClicked` 直接接到了
  `open_path` ——不设防时「同一项连点两下右键」就会把它**打开**，这正是 2026-10 用户实测
  「第二次右键必然打开第二个文件」的真身（当时宿主菜单侧全程 `cmd=0`、与菜单毫无关系；
  位移阈值解释了为什么"点相邻行不一定犯、点同一项必犯"）。`BoxWindow` 同理，否则右键双击标题
  会平白收起格子。`app.py` 的 `TodoList.mouseDoubleClickEvent` 还没设防（右键双击待办会打开其
  编辑器），要动就一起加。排查这类"点了就打开"的问题，先看有多少条 `itemDoubleClicked`/
  `doubleClicked`/`mouseDoubleClickEvent` 的连接，别一上来就往菜单/钩子方向查。
- **点掉外壳菜单的那一下会穿透成一次真左键**（2026-10 定案）：菜单是宿主进程弹的，实测
  （`%TEMP%\repro_leftopen2.py` 的 C1/C2：右键第 5 行弹出菜单后，左键点**没被菜单盖住的**
  第 1 行）格子列表照样收到完整的 `press(L)/release(L)/itemClicked` ——穿透的那一下就是一次
  货真价实的左键按下。于是「右键 A 弹菜单 → 左键 B」= 第一下点掉菜单（穿到 B 上）+ 第二下
  B = 一次**合法的左键双击** ⇒ `itemDoubleClicked` ⇒ **B 被打开**（用户实测「右键 A 后左键 B
  就打开 B，基本上必现」；那次面板日志里从头到尾没有 `ctxmenu` 事件，正因为它压根不经过菜单）。
  守卫：`_menu_open_or_just_closed()`（`_HostDaemon.callbacks` 非空 = 菜单还开着；`closed_at`
  是应答回来的时刻，另留 0.25s grace 盖住「应答信号 vs 鼠标消息」的先后竞争）→
  `BoxList.mousePressEvent` 在这个窗口里落下的按下记 `_menu_press_ts`，
  `mouseDoubleClickEvent` 对 0.6s 内的双击**不打开**（日志 `★ 菜单关闭后 …s 内的双击，不打开`）。
  代价：点掉菜单后 0.6s 内想双击打开，得再点一次（菜单已关，重试必成）；换来的是一条硬保证
  ——「关菜单的那一下永远不算双击」。回归工具 `%TEMP%\verify_guard.py`：V2 阳性对照（无菜单的
  普通双击）必须 `★OPEN`，V1（复现路径）必须被守卫拦住。
  排查「谁把它打开了」先看 `open_path` 那行日志 `open: <文件名> ← <文件:行号>`（唯一出口）。
- **轮询线程里绝不调任何 Qt 方法（2026-09 真实死锁）**：`DesktopClickHook` 的轮询跑在独立线程，
  旧版 `own_hwnds()` 在其中调 `QWidget::winId()`——winId 会现场创建原生窗口，
  `flushWindowSystemEvents → QWaitCondition` 阻塞等主线程刷窗口事件，而工作线程持有 GIL、
  主线程绘制时 `PyGILState_Ensure` 又在等 GIL，两线程互等永久死锁（症状：任意左键点击后界面
  冻结；LL 钩子不返回期间系统对每个鼠标事件等超时 = 鼠标瞬间爬行）。修复：`own_hwnds` 只读主线程
  预建的 `frozenset` 快照（`_refresh_own_hwnds`，启动与格子增删时刷新、整体换引用）。
  Win32 API（WindowFromPoint / GetParent / GetClassNameW 等）跨线程调用是安全的，Qt 对象一律不碰。

### 局域网传输（`transfer.py` + `transfer_ui.py` + `transfer_selftest.py`）

参照 LocalSend Protocol v2 实现的**私有实例**：UDP 组播发现（224.0.0.168:53327）+ HTTP REST 传输
（TCP 53327，前缀 `/api/localsend/v2/`，路由 register / info / prepare-upload / upload / cancel）。
端口与组播地址都是自定义的（官方是 53317），**与官方 LocalSend 完全隔离、互不相通**——别想着去兼容；
HTTP 模式无加密，只面向可信局域网。组播失效时有 /24 子网扫描回退。



- `transfer.py` 纯标准库零 Qt，可独立测试：`DeviceInfo` / `Discovery` / `TransferServer` /
  `send_files` / `load_or_create_fingerprint`。防护全在服务端：会话状态机 + token 校验、
  sha256 校验、64KB 流式写盘、同名自动加 " (2)"、路径穿越净化、1MB JSON 上限、
  会话 TTL 10 分钟（按最后活跃刷新）。设备发现遵循 LocalSend 语义：announce 只在
  启动时发一次（另有「刷新」触发），不做 TTL 过期剔除；「刷新」= 清空列表重新宣告，
  组播宽限 3 秒内无设备才回退 /24 子网扫描（减少请求）。Android 端同语义。
- `transfer_ui.py` 是面板第三个 tab「传输」：设备列表、文件多选 + 拖拽发送、传输记录、
  接收确认弹窗（独立无边框置顶 Tool 窗，宽 sc(320)、高按内容自适应，居中于面板上滑入场；
  Esc/Alt+F4 路由到「拒绝」保证 HTTP 线程被唤醒；可选保存目录，
  默认 `%USERPROFILE%\Downloads\Zbox` 并记住，170 秒确认超时）。
  **网络回调全走 pyqtSignal 回主线程**，不跨线程动 UI。
  **传输功能默认关闭**（`cfg['transfer_enabled']`，2026-10 改）：页面照常构建但盖一层高斯模糊
  门禁层（`QGraphicsBlurEffect` 打在 `pane` 上，门禁层 `gate` 是 pane 的兄弟故不被模糊），
  中央「启用传输」+「?」说明弹窗（`TransferInfoDialog`，与设置窗的「?」共用，含 LocalSend
  致谢与 APK 下载链接）；点启用 / 设置窗勾选走 `set_enabled()`——成功才写配置并监听端口
  （防火墙提示也在这一刻才弹），失败（53327 被占）切「传输服务不可用 + 确定」形态，
  确定后回到未开启态。服务生命周期由 `TransferWidget` 自持（`enable_service` / `disable_service` /
  `shutdown_service`），启用/停用即时生效不用重启；`enabled_changed` 信号供设置窗同步勾选。
  记录行交互（`_ClickRow` + `CustomContextMenu`）：**接收完成**（`direction='down'` 且
  `state='done'`）的行手型光标提示——单击打开文件（一次收了多个文件则 `explorer /select`
  定位第一个）；右键菜单「打开文件所在文件夹 / 删除这条记录」（`_remove_record` 只删记录
  不动文件，删光后空态 `rec_empty` 重新显示）。其余状态（发送完成、等待中、失败等）一律无交互。
- `transfer_selftest.py` 是自动化协议自检：`python transfer_selftest.py`，13 用例全过打印
  `SELFTEST OK`；用动态端口、不依赖组播与 Qt，**改 `transfer.py` 后必跑**。
- Android 端在 `android/`：独立 Gradle 工程（Kotlin + Compose + OkHttp + NanoHTTPD，minSdk 26），
  与 PC 代码完全分离；指纹/别名/保存目录存 SharedPreferences，SAF 落盘，仅前台传输
  （`onStop` 即停服务）。
- `config.json` 新增键：`transfer_fingerprint` / `transfer_alias` / `transfer_dir` / `transfer_enabled`（默认 false；zviber→zbox 迁移时旧值被 `_reset_migrated_transfer` 重置为关闭，升级用户需手动启用一次）。



坑位：

- `cfg.save()` 是整体回写，会抹掉 `load_or_create_fingerprint` 直写 config.json 的指纹——
  `main.pyw` 启动时已把指纹同步进 `cfg.data`，改启动流程时别丢掉这一步。
- 未 `start()` 的 `TransferServer` 调 `stop()` 会死等：只有 `enable_service()` 成功才会置
  `_service_started`，`disable_service()` / `shutdown_service()` 只在这个标志下 stop。
- 改别名要到下次启动或点「刷新」才会重新广播（发现报文只在启动/刷新时发）。
- Windows 防火墙首次监听 53327 会弹授权框（现在发生在用户点「启用传输」那一刻），
  用户拒绝后传输静默不可用——排查先问这一步。

## Coding Style & Naming Conventions

- 每个模块首行 `# -*- coding: utf-8 -*-`，4 空格缩进
- `snake_case` 函数、`UPPER_SNAKE` 常量、单引号字符串、`%` 格式化
- 模块 docstring 与行内注释一律中文——保持这个风格
- 无 linter / formatter；保持 diff 最小、与周围代码一致
- `run.cmd` / `build.cmd` 以 GBK 保存并自带 `chcp 936`，**改完不要另存为 UTF-8**，否则双击后中文提示乱码

## Testing Guidelines

没有单元测试框架。验证 = `ZBOX_SHOT` 截图自检 + 手动检查桌面右键菜单形态切换（运行中级联 / 未运行直链）、文件夹右键项随面板启停出现/消失、开机自启。
改布局代码时要在 125% / 150% 缩放下确认。

## Commit & Pull Request Guidelines

仓库 [github.com/evachxji/zbox](https://github.com/evachxji/zbox)（public，MIT）。
提交用 `feat:` / `fix:` / `refactor:` / `docs:` 前缀 + 简短中英文摘要。
PR 需说明改了什么与为什么；视觉改动附自检截图；注明验证过的 Windows / Python 版本。

## Security & Configuration Tips

- 注册表只写 HKCU（免管理员）；「此计算机」安装写 HKLM 才需要 UAC 提权
- 网络访问仅限三个节假日数据源（timor.tech / jiejiariapi.com / cdn.jsdelivr.net，按序回退，见 `calendar_data.SOURCES`）——timor.tech 不带 User-Agent 会回 403；
  内网用户走离线 JSON 导入，这条路径必须一直可用
- 局域网传输监听 TCP/UDP 53327（自定义端口，与官方 LocalSend 53317 隔离不互通）；
  HTTP 无加密，仅限可信局域网；Windows 防火墙首次监听会弹授权，需允许
