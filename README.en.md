<p align="center">
  <img src="assets/icon.png" width="96" alt="Zbox">
</p>

<h1 align="center">Zbox</h1>

<p align="center">
  <a href="https://github.com/evachxji/zbox/releases/latest"><img src="https://img.shields.io/github/v/release/evachxji/zbox" alt="Release"></a>
  <a href="https://github.com/evachxji/zbox/releases"><img src="https://img.shields.io/github/downloads/evachxji/zbox/total" alt="Downloads"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/platforms-Windows%2010%2F11%20%C2%B7%20Android%20%C2%B7%20HarmonyOS-blue" alt="Platforms">
</p>

<p align="center">
  <a href="README.md">简体中文</a> | <b>English</b>
</p>

A Windows desktop organizer: desktop boxes + a floating panel (calendar / todo / LAN transfer / video downloader) + screenshot tool. Windows 10 / 11.

## Features

<table>
  <tr>
    <th align="center">Desktop Boxes</th>
    <th align="center">File Transfer</th>
    <th align="center">Video Downloader</th>
  </tr>
  <tr>
    <td><a href="assets/box.png"><img src="assets/box.png" width="260" alt="Desktop boxes"></a></td>
    <td><a href="assets/transfer.png"><img src="assets/transfer.png" width="260" alt="File transfer"></a></td>
    <td><a href="assets/video.png"><img src="assets/video.png" width="260" alt="Video downloader"></a></td>
  </tr>
</table>

1. **Desktop organization**: drag into a box, auto-restore, same-edge snapping
2. **Floating panel**: calendar, todo and transfer, freely resizable
   - **Calendar**: clock countdowns, holidays, lunar calendar
   - **Todo**: checklist, due reminders, undoable delete
   - **Transfer**: LAN transfer of files and folders
3. **Screenshot**: region capture, window pick, annotations, OCR translation
4. **Video downloader**: paste a URL, multiple resolutions, resumable, with component update progress

**Languages**: the PC app and Android app support **Simplified Chinese and English**; the installer can pick the language too.

## Quick Start

👉 **[Click to download the latest Windows installer](https://github.com/evachxji/zbox/releases/latest)** (`zbox-Setup-v<version>-x64.exe`) and double-click to open it.

Upgrading: "Check for updates" in the bottom-right corner of the Settings window compares against the latest GitHub release and can download the installer and guide you through the upgrade.

Run from source: double-click `run.cmd` (it will offer to install PySide6 if missing).

## Build It Yourself

- One-click, three platforms: double-click `build.cmd` and pick 1-7 to build a single target or a combination (default 7 = everything: Windows exe installer + Android APK + HarmonyOS HAP). Artifacts (versioned file names) are collected in `dist\release\`.
  - Requirements: PC builds need PySide6 + PyInstaller (auto-install offered if missing); Android needs JDK 17 and the Android SDK; HarmonyOS needs DevEco Studio and `devecocli` (`npm i -g @deveco/deveco-cli@stable`)
  - HarmonyOS: published on AppGallery — search and install directly

## Verification

- `python -m unittest discover -s tests -v` — Python/UI regression tests
- `python transfer_selftest.py` — transfer protocol self-test (`SELFTEST OK`)
- `cd android && gradlew.bat testDebugUnitTest` — Android language-rule unit tests
- Bilingual screenshot self-check (renders every UI scene and exits):
  `set ZBOX_SHOT=designs\verify-en` + `set ZBOX_SHOT_LANG=en-US` + `python main.pyw` (use `zh-CN` for Chinese).
  Screenshot runs use an isolated IPC name, so they do not disturb a running panel.

## Compatibility

PySide6 (Qt 6.8 LTS), Python 3.10+, Windows 10 / 11.
Desktop boxes and the panel support the `WorkerW` layering used by dynamic wallpaper apps such as Wallpaper Engine, and remain visible when Win+D shows the desktop.

## Acknowledgments

The LAN transfer feature implements the v2 protocol of the open-source project [LocalSend](https://github.com/localsend/localsend) (Apache License 2.0) as a private instance (port 53327 / multicast 224.0.0.168) and is not interoperable with the official LocalSend apps.
Video downloading is powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp), with audio/video merging by [ffmpeg](https://ffmpeg.org/).

## Links

- 🌐 Website: [zbox.wzyjc.cn](https://zbox.wzyjc.cn)
- 💬 LINUX DO Community: [linux.do](https://linux.do)

## License

[MIT](LICENSE)
