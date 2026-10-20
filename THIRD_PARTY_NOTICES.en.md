# Third-Party Notices

Zbox itself is released under the [MIT License](LICENSE). The third-party
components listed below are distributed under their own licenses; this file is
for attribution and compliance purposes only and does not change their terms.

## Components downloaded on demand at runtime

The following components are not bundled in the installer. They are downloaded
from upstream sources or mirrors into the local `tools\` directory when the user
first enables the "Video Download" feature, and are invoked as standalone
subprocesses:

### yt-dlp

- Homepage: https://github.com/yt-dlp/yt-dlp
- License: [Unlicense](https://github.com/yt-dlp/yt-dlp/blob/master/LICENSE)
  (public domain)

### FFmpeg

- Homepage: https://ffmpeg.org / https://github.com/yt-dlp/FFmpeg-Builds
- License: the downloaded `win64-gpl` static build is licensed under
  [GPL v2 or later](https://ffmpeg.org/legal.html); corresponding source code
  is available at https://github.com/yt-dlp/FFmpeg-Builds
- Note: Zbox only invokes ffmpeg.exe as a command-line subprocess to mux audio
  and video streams; it is not linked against FFmpeg. The FFmpeg binary is
  distributed by its upstream builder; license texts and source availability
  are provided at the links above.

## Protocol reference

### LocalSend

- Homepage: https://localsend.org / https://github.com/localsend/localsend
- License: MIT
- Note: Zbox's LAN file transfer is an independent implementation based on the
  open LocalSend v2 protocol documentation and contains no LocalSend code.

## Build / packaging dependency

### Qt for Python (PySide6)

- Homepage: https://www.qt.io/qt-for-python / https://doc.qt.io/qtforpython/
- License: [LGPL v3](https://doc.qt.io/qtforpython/licenses.html)
- Note: Zbox uses PySide6 via dynamic linking and ships in onedir form, with
  Qt shared libraries present in the installation directory and replaceable by
  the user, satisfying the LGPL relinking requirement.

---

[中文版 Third-Party Notices](THIRD_PARTY_NOTICES.md)
