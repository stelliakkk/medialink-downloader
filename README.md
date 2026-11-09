# Bili 下载器

Windows x64 便携版 · v1.1.0

本仓库提供源码和本地构建说明。程序仅在本机访问 B 站和保存文件。请下载你有权保存的内容。

1. 完整解压便携 ZIP，双击 `BiliDownloader.exe`。保留同目录的 `_internal` 和 `runtime`。
2. 粘贴 B 站普通投稿链接、分享文本或 `b23.tv` 短链，点「解析链接」。有多个分 P 时可在预览卡选择。
3. 确认画质、输出格式和保存目录，点「开始下载」。仅音频可直接导出 MP3。完成后可点击「打开位置」。
4. 需要账号可用的画质时，点右上角「扫码登录」，使用手机哔哩哔哩 App 扫描并确认。退出仅移除本机保存的会话。

画质取决于投稿、账号和平台当时提供的轨道。程序只使用实际返回的媒体地址。MP4 保留源视频和 AAC 音轨，MP3 从音轨编码为 320 kbps。临时地址失败时会重新获取同档画质；保存前校验媒体流和时长。

默认保存到当前用户的 `Downloads\BiliDownloader`，可在窗口更改。程序在可执行文件旁的 `data` 保存路径和经 Windows DPAPI 加密的登录会话。目录不可写时改用 `%LOCALAPPDATA%\BiliDownloader`。当前支持单任务、普通投稿与分 P。

## 开发

项目使用 Python 3.14 x64。下载 [FFmpeg 9.0.2 Essentials 的 Windows ZIP](https://github.com/GyanD/codexffmpeg/releases/tag/9.0.2)，将 `bin/ffmpeg.exe`、`bin/ffprobe.exe` 和归档里的 `LICENSE` 放到项目的 `runtime` 目录。校验值见 [第三方组件说明](THIRD_PARTY.md)。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe src\bili_app.py
.\scripts\build.ps1
```

`src/bili_downloader` 内部分为平台解析、扫码认证、任务传输、本机存储与界面。界面在后台执行网络和媒体操作。第三方来源见 `THIRD_PARTY.md`。
