<p align="center">
  <img src="assets/icon.png" width="96" alt="Zviber">
</p>

# Zviber 桌面格子

Windows 桌面整理格子工具：把堆在桌面的文件拖进格子即归类，附带日历 + 待办 + 局域网传输悬浮小面板。Win7 / Win10 / Win11 通用。

## 功能

![功能一览](assets/features.png)

**桌面整理格子**（核心）：

- **空白格子**：拖入即归类——文件**留在桌面原路径不动**（右键「属性」里的位置就是桌面），只是把桌面上的图标收起来、显示在格子里；关闭程序 / 解散格子 / 隐藏格子时图标自动回到桌面，绝不吞文件
- **文件夹映射格子**：实时映射任意已有目录，点左上角图标直达所在文件夹；资源管理器里右键任意文件夹选「添加到zviber桌面格子」一键建格（面板运行中才会出现该项，重复添加同一文件夹只闪烁提示已有格子）
- 格子可拖动 / 缩放 / 收起 / 锁定，双击标题原地重命名；文件右键弹出与资源管理器逐项一致的系统右键菜单（独立原生宿主进程实现，含 Defender 扫描等扩展项）
- 磨砂半透明贴桌面、免疫 Win+D；双击桌面空白处显隐全部格子与面板

**悬浮面板**（附带）：

- **日历**：顶部时钟 + 三档倒计时（距午休 / 距上班 / 距下班）；周一起始月视图，法定节假日「休」/ 调休「班」角标、农历与节日副标题；滚轮平移翻月
- **待办**：双击空白新建，勾选完成置灰沉底；截止日期 tag（逾期标红 / 今天 / 还剩 N 天）；长文本自动折行
- **传输**：局域网内 PC ↔ Android 互传文件（参照 LocalSend 协议的私有实现，与官方 LocalSend 不互通）。**默认关闭（不监听任何端口）**，在传输页点「启用传输」或设置窗勾选后开启：自动发现同网设备，文件多选 + 拖拽发送；接收需手动确认，可选保存目录（默认「下载\Zviber」）；发送方在等待确认与传输中可随时取消；接收完成的记录单击即可打开文件，右键可打开所在文件夹或删除记录
- **主题切换**：深色 / 浅色 / 跟随系统三档，设置窗口一键切换，自动记忆
- 鼠标移入面板顶部滑出标题栏（日历 / 待办 / 传输切换），最右「—」最小化一键收起面板

## 快速开始

到 [Releases](https://github.com/evachxji/zviber/releases) 下载 `zviber-Setup-v<版本>-x64.exe`，双击打开安装向导即可（仅当前用户安装免管理员）。

源码运行：双击 `run.cmd`（缺 PyQt5 会提示自动安装）。

## exe 安装包（自行构建）

双击 `build.cmd`（或 `python build.py`），产物为单个安装包 `dist\zviber-Setup-v<版本>-<架构>.exe`（架构跟随打包用的 Python，如 x64）：双击即安装向导，安装范围、安装位置、桌面右键菜单、开机自启均可选；安装出来是 onedir 目录（`zviber\zviber.exe` + 一堆依赖文件），常驻启动免解压更快；卸载走 Windows「设置 → 应用」列表，弹出与安装同风格的卸载向导（带进度）：默认保留用户数据（`%APPDATA%\zviber\`，重装后自动恢复），勾选「同时删除个人数据」则连同待办、格子与配置一并删除。

完整右键菜单（含 Defender 扫描等扩展项）依赖 `native\zshell_host.exe`，已随仓库提交；改动 `native\zshell.cpp` 后需先跑 `native\build_native.cmd` 重新编译（需 MSVC Build Tools）。

## 局域网传输（PC ↔ Android）

两端连**同一 WiFi** 即可互传文件，不走公网、无需账号：

- PC 端：面板第三个 tab「传输」。**功能默认关闭**（不监听端口）：首次使用点传输页中央的
  「启用传输」（或在「设置 → 传输」勾选）后才开始监听端口 53327，**启用那一刻 Windows 防火墙可能弹授权提示，需允许**，
  否则设备互相搜不到；之后在设置里可随时关闭。开启后自动发现同网设备；接收文件需手动确认，可选保存目录
  （默认「下载\Zviber」，记住选择）；等待确认与传输中，发送方都能点「取消」中断（半成品文件自动清理）。
- Android 端：`android/` 是独立 Gradle 工程（Android 8.0 / minSdk 26 起）。构建前置：本机需有 JDK 17
  与 Android SDK——装 Android Studio，或只用 cmdline-tools 装 `platforms;android-36` 与
  `build-tools;36.0.0` 即可（无需整个 Studio）。SDK 位置用环境变量 `ANDROID_HOME`、或
  `android/local.properties` 里的 `sdk.dir=<SDK路径>` 告诉 Gradle（该文件已 gitignore，各机器各写各的；
  Windows 用户名含中文时建议把 SDK 装到纯英文路径）。构建 debug 包：

```bat
cd android && gradlew.bat assembleDebug
```

产物在 `android\app\build\outputs\apk\debug\`，拷贝到手机安装即可。仅前台传输，
App 退到后台即停止服务。

实现参照 LocalSend Protocol v2，但端口与组播地址为自定义，**与官方 LocalSend 不互通**；
HTTP 无加密，请只在可信局域网使用。

## 兼容性

PyQt5（Qt 5.15），Win7 / Win10 / Win11 通用；Win7 需 Python 3.8 + `PyQt5==5.15.*`。

## 自检

```bat
set ZVIBER_SHOT=designs\verify && python main.pyw
```
导出两主题 × 日历/待办/传输共 6 张截图到指定目录后自动退出。

## 开源致谢

局域网传输功能参照开源项目 [LocalSend](https://github.com/localsend/localsend)（Apache License 2.0）的
v2 协议实现，为私有实例（端口 53327 / 组播 224.0.0.168），与官方 LocalSend 应用不互通。

## License

[MIT](LICENSE)
