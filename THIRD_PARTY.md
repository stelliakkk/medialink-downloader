# 第三方组件

窗口使用 PySide6 Essentials 和 Qt Widgets。二维码由 qrcode 绘制，HTTP 请求由 Requests 处理。备用 B 站解析使用 yt-dlp。Windows 可执行程序由 PyInstaller 打包。依赖的原有许可见便携目录的组件许可文件和各包元数据。

抖音解析通过 websocket-client 连接本机 Edge 的临时调试会话。Edge 由系统安装。

- [PySide6 与 Qt](https://doc.qt.io/qtforpython-6/licenses.html)
- [Requests](https://github.com/psf/requests) · [qrcode](https://github.com/lincolnloop/python-qrcode) · [yt-dlp](https://github.com/yt-dlp/yt-dlp) · [PyInstaller](https://github.com/pyinstaller/pyinstaller)
- [websocket-client](https://github.com/websocket-client/websocket-client) · [Microsoft Edge DevTools Protocol](https://learn.microsoft.com/en-us/microsoft-edge/devtools/protocol/)
- FFmpeg 和 FFprobe 9.0.2 作为独立程序调用，来自 [Gyan 的 Windows Essentials 构建](https://www.gyan.dev/ffmpeg/builds/)。构建包许可和说明在 `runtime` 中，FFmpeg [对应源码](https://github.com/FFmpeg/FFmpeg/commit/946fcce07b)由上游提供。验收使用的 Essentials ZIP 的 SHA-256 为 `60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba`。

公开发行的完整便携包包含 `licenses`、`SOURCE.txt`、对应提交的项目源码和第三方源码清单。同一 GitHub Release 提供 `MediaLinkDownloader-v3.0.6-third-party-sources.zip`，收录 Python、Qt/PySide、Python 依赖、FFmpeg 和部分外部编解码组件的版本化源码归档。归档的上游地址、SHA-256 和大小见清单；FFmpeg 的构建配置及外部组件版本见附件和 `runtime/README.txt`。各组件保留自己的许可证。
