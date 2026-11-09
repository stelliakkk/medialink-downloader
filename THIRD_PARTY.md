# 第三方组件

窗口使用 PySide6 Essentials 和 Qt Widgets。二维码由 qrcode 绘制，HTTP 请求由 Requests 处理。备用 B 站解析使用 yt-dlp。Windows 可执行程序由 PyInstaller 打包。依赖的原有许可见便携目录的组件许可文件和各包元数据。

抖音解析通过 websocket-client 连接本机 Edge 的临时调试会话。Edge 由系统安装。

- [PySide6 与 Qt](https://doc.qt.io/qtforpython-6/licenses.html)
- [Requests](https://github.com/psf/requests) · [qrcode](https://github.com/lincolnloop/python-qrcode) · [yt-dlp](https://github.com/yt-dlp/yt-dlp) · [PyInstaller](https://github.com/pyinstaller/pyinstaller)
- [websocket-client](https://github.com/websocket-client/websocket-client) · [Microsoft Edge DevTools Protocol](https://learn.microsoft.com/en-us/microsoft-edge/devtools/protocol/)
- FFmpeg 和 FFprobe 9.0.2 作为独立程序调用，来自 [Gyan 的 Windows Essentials 构建](https://www.gyan.dev/ffmpeg/builds/)。构建包许可和说明在 `runtime` 中，FFmpeg [对应源码](https://github.com/FFmpeg/FFmpeg/commit/946fcce07b)由上游提供。验收使用的 Essentials ZIP 的 SHA-256 为 `60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba`。

当前便携包用于本机验收。向他人转发或公开提供便携包前，需按组件的许可条款准备并提供对应源码与许可证材料。
