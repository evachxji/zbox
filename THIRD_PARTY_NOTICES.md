# 第三方组件声明（Third-Party Notices）

Zbox 本体以 [MIT License](LICENSE) 发布。以下第三方组件按其各自的许可证分发，
本文件仅为声明与致谢，不改变各组件的许可条款。

## 运行时按需下载的组件

以下组件不在安装包内，由用户首次启用「视频解析」功能时从上游或镜像下载到本地
`tools\` 目录，作为独立子进程调用：

### yt-dlp

- 主页：https://github.com/yt-dlp/yt-dlp
- 许可证：[Unlicense](https://github.com/yt-dlp/yt-dlp/blob/master/LICENSE)（公有领域）

### FFmpeg

- 主页：https://ffmpeg.org ／ https://github.com/yt-dlp/FFmpeg-Builds
- 许可证：所下载的 `win64-gpl` 静态构建适用 [GPL v2 或更高版本](https://ffmpeg.org/legal.html)，
  对应源码见 https://github.com/yt-dlp/FFmpeg-Builds
- 说明：Zbox 仅以命令行子进程方式调用 ffmpeg.exe 合并音视频流，未与其链接；
  ffmpeg 二进制由其上游构建方分发，许可证文本与源码出处见上述链接。

## 协议参考

### LocalSend

- 主页：https://localsend.org ／ https://github.com/localsend/localsend
- 许可证：MIT
- 说明：Zbox 的局域网传输功能参照 LocalSend v2 开放协议文档独立实现，
  未包含 LocalSend 的代码。

## 开发/打包依赖

### Qt for Python（PySide6）

- 主页：https://www.qt.io/qt-for-python ／ https://doc.qt.io/qtforpython/
- 许可证：[LGPL v3](https://doc.qt.io/qtforpython/licenses.html)
- 说明：Zbox 以动态链接方式使用 PySide6，发行版以 onedir 形式分发，
  Qt 动态库位于安装目录内、可由用户替换，满足 LGPL 的重链接要求。

---

[English version](THIRD_PARTY_NOTICES.en.md)
