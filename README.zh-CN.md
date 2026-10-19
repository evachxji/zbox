<p align="center">
  <img src="assets/icon.png" width="96" alt="Zbox">
</p>

# Zbox 桌面格子 v0.4.1

<p align="center">
  <a href="https://github.com/evachxji/zbox/releases/latest"><img src="https://img.shields.io/github/v/release/evachxji/zbox" alt="Release"></a>
  <a href="https://github.com/evachxji/zbox/releases"><img src="https://img.shields.io/github/downloads/evachxji/zbox/total" alt="Downloads"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/platforms-Windows%2010%2F11%20%C2%B7%20Android%20%C2%B7%20HarmonyOS-blue" alt="Platforms">
</p>

<p align="center">
  <a href="README.md">English</a> | <b>简体中文</b>
</p>

Windows 桌面整理工具：桌面格子 + 悬浮面板（日历 / 待办 / 传输 / 视频解析）+ 截图。Win10 / Win11。

## 功能

<table>
  <tr>
    <th align="center">桌面格子</th>
    <th align="center">文件传输</th>
    <th align="center">视频解析</th>
  </tr>
  <tr>
    <td><a href="assets/box.png"><img src="assets/box.png" width="260" alt="桌面格子"></a></td>
    <td><a href="assets/transfer.png"><img src="assets/transfer.png" width="260" alt="文件传输"></a></td>
    <td><a href="assets/video.png"><img src="assets/video.png" width="260" alt="视频解析"></a></td>
  </tr>
</table>

1. **桌面整理**：文件拖入格子即归类，图标自动收纳还原，未入格文件的图标位置自动记忆、启动时摆回；
   拖动格子靠近其他可见格子时只吸附同边：左对左、右对右、上对上、下对下，相对的两条边不吸附；缩放格子以及移动日历卡片时规则相同，日历卡片缩放不吸附。8px 内进入吸附，移出 12px 后释放；每一条实际对齐的边都会显示一条贯穿两张卡片的蓝色辅助线；
   格子内拖到条目间的白色引导线上可自定义排序，拖到文件夹上 = 移入该文件夹，拖到程序/快捷方式上 = 用它打开；
   顶部栏右侧的收起、锁定、菜单图标默认隐藏，鼠标移入顶部栏时淡入、移出后淡出
2. **悬浮面板**：
   - **日历**：时钟倒计时、节假日农历、滚轮翻月
   - **待办**：勾选完成置灰，截止日期逾期提醒（日历点选后按「确定」保存）；有日期项在上并按日期升序排列，无日期项在下，已完成项最后；编辑和勾选不跳动列表；编辑行右侧可点勾保存；右键可编辑、复制或删除，删除后 5 秒内可撤销，连续删除的提示浮窗向上堆叠并各自带倒计时细线；新建输入框先追加到列表尾部；输入框随内容完整增高，Enter 保存、Shift+Enter 换行
   - **传输**：局域网设备互传文件/文件夹（接收端按原目录结构还原文件夹），手动确认接收（首次启用请放行 Windows 防火墙弹窗；误点「取消」导致收不到设备/文件时，传输页会自动提示并可一键修复）
   - **视频解析**：粘贴网址下载视频，多清晰度、断点续传
   - 卡片四边/四角拖拽自由缩放，大小自动记忆
3. **截图**：全局热键框选标注，支持钉图与滚动长图
4. **语言**：PC 端与 Android 端均支持**简体中文 / English**。PC 端在 **设置 → 语言** 中切换（重启生效）；
   安装向导首屏也可以直接选择安装语言。Android 端在底部「设置」tab 中切换，即时生效。

## 快速开始

到 [Releases](https://github.com/evachxji/zbox/releases) 下载 `zbox-Setup-v<版本>-x64.exe`，双击打开安装向导。
安装始终按所有用户装到 `Program Files`（Windows 会请求管理员权限），安装前会清理旧版 Zbox 程序文件，
`%APPDATA%\zbox` 里的个人数据（待办、格子、配置）一律保留。

升级：设置窗右下角「检查更新」会自动比对 GitHub 最新 release，有新版本可一键下载安装包并引导安装。

源码运行：双击 `run.cmd`（缺 PySide6 会提示自动安装）。

## 自行构建

- 一键三端：双击 `build.cmd`，启动后选 1-7 构建单端或组合（默认 7 全量：Windows exe 安装包 + Android APK + 鸿蒙 HAP），产物汇总在 `dist\release\`（文件名带版本号）
  - 依赖：PC 需 PySide6 + PyInstaller（缺了会提示自动装）；Android 需 JDK 17 与 Android SDK；鸿蒙需 DevEco Studio 与 `devecocli`（`npm i -g @deveco/deveco-cli@stable`）
  - hap 是免签名调试包，只能装模拟器/开发者调试设备；分发真机需签名或上架（见 `harmony\README.md`）

## 验证

- `python -m unittest discover -s tests -v` — Python/UI 回归测试
- `python transfer_selftest.py` — 传输协议自检（`SELFTEST OK`）
- `cd android && gradlew.bat testDebugUnitTest` — Android 语言规则单元测试
- 双语截图自检（导出全界面场景后自动退出）：
  `set ZBOX_SHOT=designs\verify-en` + `set ZBOX_SHOT_LANG=en-US` + `python main.pyw`（中文用 `zh-CN`）。
  截图进程使用独立 IPC 名，不会干扰正在运行的面板。

## 兼容性

PySide6（Qt 6.8 LTS），Python 3.10+，Win10 / Win11。

## 开源致谢

局域网传输功能参照开源项目 [LocalSend](https://github.com/localsend/localsend)（Apache License 2.0）的
v2 协议实现，为私有实例（端口 53327 / 组播 224.0.0.168），与官方 LocalSend 应用不互通。
视频解析功能由 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 驱动，音视频合并由 [ffmpeg](https://ffmpeg.org/) 完成。

## 链接

- 🌐 官网：[zbox.wzyjc.cn](https://zbox.wzyjc.cn)
- 📦 下载发布：[github.com/evachxji/zbox/releases](https://github.com/evachxji/zbox/releases)
- 🐛 问题反馈：[github.com/evachxji/zbox/issues](https://github.com/evachxji/zbox/issues)
- 💬 LINUX DO 社区：[linux.do](https://linux.do)

## License

[MIT](LICENSE)
