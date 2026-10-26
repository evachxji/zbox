<p align="center">
  <img src="assets/icon.png" width="96" alt="Zbox">
</p>

<h1 align="center">Zbox 桌面格子</h1>

<p align="center">
  <a href="https://github.com/evachxji/zbox/releases/latest"><img src="https://img.shields.io/github/v/release/evachxji/zbox" alt="Release"></a>
  <a href="https://github.com/evachxji/zbox/releases"><img src="https://img.shields.io/github/downloads/evachxji/zbox/total" alt="Downloads"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/platforms-Windows%2010%2F11%20%C2%B7%20Android%20%C2%B7%20HarmonyOS-blue" alt="Platforms">
</p>

<p align="center">
  <b>简体中文</b> | <a href="README.en.md">English</a>
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

1. **桌面整理**：拖入格子自动收纳，拖动同边吸附
2. **悬浮面板**：日历、待办、传输，卡片可自由缩放
   - **日历**：时钟倒计时、节假日、农历
   - **待办**：清单、到期提醒、删除可撤销
   - **传输**：局域网互传文件与文件夹
3. **截图**：框选、程序窗口套选、标注与 OCR 翻译
4. **视频解析**：粘贴网址下载，多清晰度续传，组件更新显示下载进度

**语言**：PC 端与 Android 端均支持**简体中文 / English**，安装向导首屏也可选择安装语言。

## 快速开始

👉 **[点击下载最新版 Windows 安装包](https://github.com/evachxji/zbox/releases/latest)**（`zbox-Setup-v<版本>-x64.exe`），双击打开安装向导。

升级：设置窗右下角「检查更新」会自动比对 GitHub 最新 release，有新版本可一键下载安装包并引导安装。

源码运行：双击 `run.cmd`（缺 PySide6 会提示自动安装）。

## 自行构建

- 一键三端：双击 `build.cmd`，启动后选 1-7 构建单端或组合（默认 7 全量：Windows exe 安装包 + Android APK + 鸿蒙 HAP），产物汇总在 `dist\release\`（文件名带版本号）
  - 依赖：PC 需 PySide6 + PyInstaller（缺了会提示自动装）；Android 需 JDK 17 与 Android SDK；鸿蒙需 DevEco Studio 与 `devecocli`（`npm i -g @deveco/deveco-cli@stable`）
  - 鸿蒙端已上架应用市场（AppGallery），可直接搜索安装

## 验证

- `python -m unittest discover -s tests -v` — Python/UI 回归测试
- `python transfer_selftest.py` — 传输协议自检（`SELFTEST OK`）
- `cd android && gradlew.bat testDebugUnitTest` — Android 语言规则单元测试
- 双语截图自检（导出全界面场景后自动退出）：
  `set ZBOX_SHOT=designs\verify-en` + `set ZBOX_SHOT_LANG=en-US` + `python main.pyw`（中文用 `zh-CN`）。
  截图进程使用独立 IPC 名，不会干扰正在运行的面板。

## 兼容性

PySide6（Qt 6.8 LTS），Python 3.10+，Win10 / Win11。
桌面格子与面板兼容 Wallpaper Engine 等动态壁纸的 `WorkerW` 分层结构，按 Win+D 显示桌面时保持可见。

## 开源致谢

局域网传输功能参照开源项目 [LocalSend](https://github.com/localsend/localsend)（Apache License 2.0）的
v2 协议实现，为私有实例（端口 53327 / 组播 224.0.0.168），与官方 LocalSend 应用不互通。
视频解析功能由 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 驱动，音视频合并由 [ffmpeg](https://ffmpeg.org/) 完成。

## 链接

- 🌐 官网：[zbox.wzyjc.cn](https://zbox.wzyjc.cn)
- 💬 LINUX DO 社区：[linux.do](https://linux.do)

## License

[MIT](LICENSE)
