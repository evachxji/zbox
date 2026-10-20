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

1. **Desktop organization**: drag files into a box to tidy them away — icons are hidden and restored automatically, and the positions of icons that never entered a box are remembered and put back on launch.
   Drag a box near another visible box to snap matching edges: left-to-left, right-to-right, top-to-top, or bottom-to-bottom. Opposite edges never snap. The same rule applies while resizing a box and when moving the calendar panel; calendar resizing stays freely resizable. The snap engages within 8 px, releases after 12 px, and blue guides span both cards for every aligned edge.
   Inside a box, drop onto the white guide line between items for a custom order, onto a folder to move files into it, or onto an app/shortcut to open the dragged files with it.
   The collapse, lock, and menu icons stay hidden until the pointer enters the title bar, then fade in and fade out after it leaves.
2. **Floating panel**:
   - **Calendar**: clock with countdowns, public holidays and an optional lunar calendar, scroll to flip months
   - **Todo**: check items off (grayed out), overdue reminders (pick a date, then confirm), dated items first and sorted by due date, undated items after them, and completed items last; editing or checking does not jump the list, and the editor has a check button to save. Right-click to edit/copy/delete with stacked 5-second undo toasts, each with its own countdown; new inputs start at the list tail, and the editor grows to show all content (Enter saves, Shift+Enter adds a line)
   - **Transfer**: send files and folders between devices on the LAN (folders arrive as a recreated directory tree on the receiver), with manual accept on the receiver (allow the Windows Firewall prompt when first enabling it; if you clicked "Cancel" by mistake and devices/files stop arriving, the transfer tab detects it and offers a one-click repair)
   - **Video downloader**: paste a URL to download videos, multiple resolutions, resumable downloads
   - Freely resize the card by dragging its edges/corners; the size is remembered
3. **Screenshot**: global hotkey region capture with window-aware selection — hover an app window to outline it, click to select the full window, or double-click to copy and exit; also supports rectangles, ellipses, QQ-style arrows, sequential number markers with auto-growing multiline dark labels and text, pin-to-screen and scrolling long capture; marker labels stay single-line until they reach the capture boundary or the user presses Enter, then wrap while keeping the number visible; per-tool size sliders are remembered across captures, labels can be dragged and reopened for editing, and clicking or dragging a pinned image opens its fixed bottom toolbar tray for annotation, saving and copying; click elsewhere to dismiss it. The toolbar **Translate** button recognizes text with local OCR and translates it via Doubao (first use shows a two-step setup guide: install the local OCR component from public PyPI mirrors (e.g. Tsinghua TUNA) and sign in to Doubao in a system Microsoft Edge window; only the recognized text is sent, the screenshot never leaves the device), painting the translation over the original text (which gets pixelated); click again to toggle back to the original, and copy/save/pin flattens the final image
4. **Languages**: the PC app and Android app support **Simplified Chinese and English**. On PC, use the compact language selector directly below **Video downloader** in Settings (a restart applies it); the installer's first page also lets you pick the installation language. On Android, switch it in the **Settings** tab at the bottom; it applies immediately.

## Quick Start

👉 **[Click to download the latest Windows installer](https://github.com/evachxji/zbox/releases/latest)** (`zbox-Setup-v<version>-x64.exe`) and double-click to open it.

Upgrading: "Check for updates" in the bottom-right corner of the Settings window compares against the latest GitHub release and can download the installer and guide you through the upgrade.

Run from source: double-click `run.cmd` (it will offer to install PySide6 if missing).

## Build It Yourself

- One-click, three platforms: double-click `build.cmd` and pick 1-7 to build a single target or a combination (default 7 = everything: Windows exe installer + Android APK + HarmonyOS HAP). Artifacts (versioned file names) are collected in `dist\release\`.
  - Requirements: PC builds need PySide6 + PyInstaller (auto-install offered if missing); Android needs JDK 17 and the Android SDK; HarmonyOS needs DevEco Studio and `devecocli` (`npm i -g @deveco/deveco-cli@stable`)
  - The HAP is an unsigned debug package that only installs on emulators / developer debug devices; distributing to real devices requires signing or AppGallery release (see `harmony\README.md`)

## Verification

- `python -m unittest discover -s tests -v` — Python/UI regression tests
- `python transfer_selftest.py` — transfer protocol self-test (`SELFTEST OK`)
- `cd android && gradlew.bat testDebugUnitTest` — Android language-rule unit tests
- Bilingual screenshot self-check (renders every UI scene and exits):
  `set ZBOX_SHOT=designs\verify-en` + `set ZBOX_SHOT_LANG=en-US` + `python main.pyw` (use `zh-CN` for Chinese).
  Screenshot runs use an isolated IPC name, so they do not disturb a running panel.

## Compatibility

PySide6 (Qt 6.8 LTS), Python 3.10+, Windows 10 / 11.

## Acknowledgments

The LAN transfer feature implements the v2 protocol of the open-source project [LocalSend](https://github.com/localsend/localsend) (Apache License 2.0) as a private instance (port 53327 / multicast 224.0.0.168) and is not interoperable with the official LocalSend apps.
Video downloading is powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp), with audio/video merging by [ffmpeg](https://ffmpeg.org/).

## Links

- 🌐 Website: [zbox.wzyjc.cn](https://zbox.wzyjc.cn)
- 📦 Releases: [github.com/evachxji/zbox/releases](https://github.com/evachxji/zbox/releases)
- 🐛 Issues: [github.com/evachxji/zbox/issues](https://github.com/evachxji/zbox/issues)
- 💬 LINUX DO Community: [linux.do](https://linux.do)

## License

[MIT](LICENSE)
