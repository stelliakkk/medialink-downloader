# Bili 下载器

Windows x64 便携版 · v2.0.0

本仓库提供源码和本地构建说明。程序仅在本机访问 B 站和保存文件。请下载你有权保存的内容。

1. 完整解压便携 ZIP，双击 `BiliDownloader.exe`。保留同目录的 `_internal` 和 `runtime`。
2. 粘贴 B 站普通投稿链接、分享文本或 `b23.tv` 短链，点「解析链接」。有多个分 P 时可在预览卡选择。
3. 确认画质、输出格式和保存目录，点「开始下载」进入队列。可以用「批量添加链接」一次粘贴最多 50 条，或用「多选分 P」勾选同一投稿的多个片段。
4. 需要账号可用的画质时，点右上角「扫码登录」，使用手机哔哩哔哩 App 扫描并确认。退出仅移除本机保存的会话。

画质取决于投稿、账号和平台当时提供的轨道。程序只使用实际返回的媒体地址。MP4 保留源视频和 AAC 音轨，MP3 从音轨编码为 320 kbps。临时地址失败时会重新获取同档画质；保存前校验媒体流和时长。

「队列」逐条下载。可以暂停后续任务、继续、取消当前下载或移除等待项。重启后点击「继续队列」开始处理剩余任务。「历史」可按结果筛选，打开文件或目录，并将失败、取消、中断或文件缺失的任务重新入队。

默认保存到当前用户的 `Downloads\BiliDownloader`，可在窗口更改。程序在可执行文件旁的 `data` 保存设置、任务数据库和经 Windows DPAPI 加密的登录会话。目录不可写时改用 `%LOCALAPPDATA%\BiliDownloader`。如果解压升级到新目录并需要沿用设置，请先关闭新旧程序，再把旧版的 `data` 复制到新版本目录。

## 开发

项目使用 Python 3.14 x64。下载 [FFmpeg 9.0.2 Essentials 的 Windows ZIP](https://github.com/GyanD/codexffmpeg/releases/tag/9.0.2)，将 `bin/ffmpeg.exe`、`bin/ffprobe.exe` 和归档里的 `LICENSE` 放到项目的 `runtime` 目录。校验值见 [第三方组件说明](THIRD_PARTY.md)。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe src\bili_app.py
.\scripts\build.ps1
```

`src/bili_downloader` 内部分为平台解析、扫码认证、任务调度、媒体传输、本机存储与界面。界面在后台执行网络和媒体操作。2.0 的设计与验收范围见 [开发计划](PLAN-2.0.md)，依赖来源见 [第三方组件](THIRD_PARTY.md)。

运行自动化测试：

```powershell
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
