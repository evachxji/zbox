# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Zviber 桌面日历面板：PyQt5 编写的 Windows 悬浮小面板（日历 + 待办 + 局域网文件传输），兼容 Win7 / Win10 / Win11、Python 3.8+。
平铺布局、一个模块一个职责，无第三方依赖（仅 PyQt5）。同目录 `AGENTS.md` 是给其它 agent 的精简版
（模块清单 / 命令 / 风格），本文件补充架构与坑位——**改功能时 README、AGENTS.md、CLAUDE.md 三份都要同步**。

## 常用命令

```bat
pip install PyQt5            :: 唯一依赖（Win7 需 Python 3.8 + "PyQt5==5.15.*"）
pythonw main.pyw             :: 源码方式运行
python install.py            :: 源码方式开启开机自启（右键菜单只在 exe 安装后才有）
python install.py --remove   :: 移除自启，并清理旧的右键菜单

python build.py              :: 构建 exe 安装包 → dist\ZviberPanel.exe（本身即安装包）
python transfer_selftest.py  :: 传输协议自检（12 用例全过打印 SELFTEST OK）

cd android && gradlew.bat assembleDebug   :: Android 端 debug APK（独立 Gradle 工程）
```

`run.cmd` / `build.cmd` 是给最终用户双击用的入口（免命令行）。**这两个 .cmd 以 GBK 保存并自带
`chcp 936`，改完绝不能另存为 UTF-8**，否则双击后中文提示乱码；同时保持 CRLF 行尾。

`build.py` 除生成图标外还写一份 DPI 感知清单（`--manifest`）交给 PyInstaller：**PyInstaller 默认打的 exe
没有 DPI 感知声明**，进程被系统按 unaware 虚拟化，`ui_scale()` 读到 96 DPI，界面就完全不放大
（源码运行由 Qt 运行时自己设了感知，没这个问题）。图标、清单连同 spec 与 PyInstaller 工作目录
全部收在 `dist\build\` 下——这三个 path 都是 `build.py` 显式传的绝对路径，**别把
`--workpath` / `--specpath` 删掉**，PyInstaller 默认往当前目录扔 `build\` 和 `*.spec`，根目录就乱了。
`dist\` 整个目录已被 gitignore。

自检（**改任何 UI / 主题 / 布局代码后都要跑**）：

```bat
set ZVIBER_SHOT=designs\verify && python main.pyw
```

导出两主题 × 日历/待办/双栏/传输共 8 张 PNG（`<theme>_<view>.png`）后自动退出；截图目录已 git-ignore。
另有 `ZVIBER_GRABSCREEN=<路径>`：抓取真实屏幕上面板所在区域（含系统合成效果）后退出。

**跑自检前必须先退出正在运行的实例**：单实例分支会把这次启动当成一次 `--toggle` 转发给已运行实例
（于是用户的面板被显示/隐藏了一次），本进程直接退出，一张图都不会导出，且没有任何报错提示。

无单元测试框架，验证 = 截图自检 + 手动检查托盘菜单 / 右键菜单开关 / 开机自启。
改动布局代码时需在 125% / 150% 缩放下确认。

## 架构

数据流：`main.pyw`（入口）→ 构造 `Config` / `HolidayStore` / `TodoStore` → 注入 `FloatingPanel`，
面板只通过 store 读写，所有持久化落在 `%APPDATA%\ZviberPanel\`（`config.json`、`todos.json`、
`holidays.json`、运行时生成的 `icons/`）——**绝不提交这些数据**。

### 入口与进程模型（`main.pyw` + `sysutil` + `installer`）

`main()` 的顺序是有意的，改动前先读懂：设置 excepthook → `installer.maybe_install()`
（仅 frozen exe 生效，返回 True 表示安装/卸载/取消已处理完，直接退出）→ 单实例 IPC 探测
（`QLocalSocket` 连 `sysutil.IPC_KEY`，已运行则发 `toggle` 后退出）→ 建面板 → 起 `QLocalServer`
接收 `toggle` / `quit` → 托盘。

- 单实例靠 `QLocalServer` 名称 `zviber-panel-v1`；`quit` 消息供卸载程序请求退出。
- 托盘/桌面右键菜单都用 `--toggle` 让已运行实例显隐，不新起进程。
- `installer.maybe_install()` 里 `ZVIBER_AUTO_INSTALL` 是静默安装测试钩子，`ZVIBER_SHOT` /
  `ZVIBER_GRABSCREEN` 下跳过安装向导。
- 设置窗口是**非模态**的（托盘「设置」或标题栏 ⚙），已开着就 `raise_()`，不会叠第二个；
  托盘菜单只有「显示 / 隐藏、设置、卸载 Zviber（仅已安装时）、退出」——主题 / 双栏 / 时间 / 节假日
  全部挪进了设置窗口，别再往托盘里加。

### 面板（`app.py`）

`FloatingPanel` 是无边框**不透明**顶层窗口：不用 `WA_TranslucentBackground`（分层窗口禁用
ClearType，文字发灰），圆角靠 Win11 DWM，Win7/10 降级为圆角遮罩（`round_corners`）；
也不用 `QGraphicsDropShadowEffect`（Qt5 下破坏顶层窗合成），所以 `SHADOW = 0`、无阴影留白。
（`FloatingPanel.__init__` 里那句「阴影改为 paintEvent 手绘」是旧注释，类中已无 `paintEvent`。）

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
「下载并导入」走同一条通道，只有手动路径才弹托盘气泡。

⚠️ **PyQt5 里槽函数中未捕获的异常会让进程直接 abort（qFatal），不是打个日志就完事**——实测无自定义
excepthook 时 exit 127、连输出都没有。`main()` 里那句 `sys.excepthook = _debug_excepthook` 正是挡这个的
（改成落盘 `debug_due.log`，程序继续跑）；它的注释写着「定位后移除」，但**删掉它 = 任何槽里的异常都会
静默崩掉整个面板**，要删先确认有别的兜底。反过来说，它也把这类 bug 变成静默的了：后台更新那次
`hstore.merge` 漏写实现，在应用里只会静静地不更新，是离屏脚本才把它揪出来。

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
  没有任何安装记录就清掉菜单残留（旧版 install.py 的源码安装、向导取消、半卸载）。
- `sysutil.launcher_cmd()` 区分 frozen（直接启自身）与源码（优先 `pythonw.exe` 实现无窗口静默）。
- `installer.py` 的向导与自安装**只在 frozen 时生效**；源码运行走 `install.py`。
- 卸载用延迟 `rmdir`（exe 运行中删不掉自己），只清程序与系统集成，
  `%APPDATA%\ZviberPanel` 的用户数据保留。

### 局域网传输（`transfer.py` + `transfer_ui.py` + `transfer_selftest.py`）

参照 LocalSend Protocol v2 实现的**私有实例**：UDP 组播发现（224.0.0.168:53327）+ HTTP REST 传输
（TCP 53327，前缀 `/api/localsend/v2/`，路由 register / info / prepare-upload / upload / cancel）。
端口与组播地址都是自定义的（官方是 53317），**与官方 LocalSend 完全隔离、互不相通**——别想着去兼容；
HTTP 模式无加密，只面向可信局域网。组播失效时有 /24 子网扫描回退。

- `transfer.py` 纯标准库零 Qt，可独立测试：`DeviceInfo` / `Discovery` / `TransferServer` /
  `send_files` / `load_or_create_fingerprint`。防护全在服务端：会话状态机 + token 校验、
  sha256 校验、64KB 流式写盘、同名自动加 " (2)"、路径穿越净化、1MB JSON 上限、
  会话 TTL 10 分钟（按最后活跃刷新）。
- `transfer_ui.py` 是面板第三个 tab「传输」：设备列表、文件多选 + 拖拽发送、传输记录、
  接收确认层（可选保存目录，默认 `%USERPROFILE%\Downloads\Zviber` 并记住，170 秒确认超时）。
  **网络回调全走 pyqtSignal 回主线程**，不跨线程动 UI；53327 被占用时降级为空态，不影响日历/待办。
- `transfer_selftest.py` 是自动化协议自检：`python transfer_selftest.py`，12 用例全过打印
  `SELFTEST OK`；用动态端口、不依赖组播与 Qt，**改 `transfer.py` 后必跑**。
- Android 端在 `android/`：独立 Gradle 工程（Kotlin + Compose + OkHttp + NanoHTTPD，minSdk 26），
  与 PC 代码完全分离；指纹/别名/保存目录存 SharedPreferences，SAF 落盘，仅前台传输
  （`onStop` 即停服务）。
- `config.json` 新增键：`transfer_fingerprint` / `transfer_alias` / `transfer_dir`。

坑位：

- `cfg.save()` 是整体回写，会抹掉 `load_or_create_fingerprint` 直写 config.json 的指纹——
  `main.pyw` 启动时已把指纹同步进 `cfg.data`，改启动流程时别丢掉这一步。
- 未 `start()` 的 `TransferServer` 调 `stop()` 会死等，退出路径靠 `transfer_started` 标志守卫。
- 改别名要重启才会重新广播（发现报文只在启动时发）。
- Windows 防火墙首次监听 53327 会弹授权框，用户拒绝后传输静默不可用——排查先问这一步。

## 代码风格

- 每个模块首行 `# -*- coding: utf-8 -*-`，4 空格缩进
- `snake_case` 函数 / `UPPER_SNAKE` 常量 / 单引号字符串 / `%` 格式化
- 模块 docstring 与行内注释一律中文，保持这个风格
- 无 linter / formatter，保持 diff 最小、与周围代码一致

## 提交与 PR

仓库 [github.com/evachxji/zviber](https://github.com/evachxji/zviber)（public，MIT）。
用 `feat:` / `fix:` / `refactor:` 前缀 + 简短中英文摘要。
PR 需说明改了什么与为什么；视觉改动附自检截图；注明验证过的 Windows / Python 版本。
