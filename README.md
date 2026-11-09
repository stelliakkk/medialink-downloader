# MediaLink 下载器

MediaLink Downloader · Windows x64 · v3.0.0

在一个窗口下载哔哩哔哩和抖音的普通视频。支持选画质、保存带声 MP4、导出 MP3，以及共用的下载队列和历史。程序在本机解析和保存文件。请下载你有权保存的内容。

## 使用

1. 完整解压便携 ZIP，双击 `MediaLinkDownloader.exe`，并保留同目录的 `_internal` 和 `runtime`。
2. 粘贴 B 站或抖音的链接、分享文本或短链，点「解析链接」。B 站多分 P 投稿可选择单个或多个分 P。
3. 确认画质、输出和保存目录，点「开始下载」进入队列。「批量添加链接」一次最多接受 50 条，两平台可以混合粘贴。
4. 在「队列」暂停后续任务、继续、取消当前项或移除等待项。在「历史」按结果筛选，打开已保存文件或目录，将失败、中断、取消或文件缺失的任务重新入队。

抖音解析使用本机已安装的 Microsoft Edge 和独立临时游客会话。画质以网页返回的实际分辨率为准。网页要求登录、验证或无法播放时，任务会提示失败。B 站可用右上角的「B 站登录」扫码，获取账号可用的画质。

MP4 保留源画面和音轨，MP3 从音轨编码为 320 kbps。临时地址失效时会重新获取同档画质。保存前校验媒体流、分辨率和时长。重启后，在「队列」点击「继续队列」处理剩余任务。

## 数据与升级

默认保存到 `Downloads\MediaLinkDownloader`。设置、任务数据库和经 Windows DPAPI 加密的 B 站会话保存在可执行文件旁的 `data`。目录不可写时使用 `%LOCALAPPDATA%\MediaLinkDownloader`。

从旧版升级时，先关闭新旧程序，再把旧版的 `data` 复制到新版目录后启动。如果旧版使用系统回退目录，来源为 `%LOCALAPPDATA%\BiliDownloader`。新版自动给原任务和历史补上 B 站来源，保留任务 ID、分 P 和已保存文件的位置。旧版数据副本可作为回退备份。

## 开发

项目使用 Python 3.14 x64。下载 [FFmpeg 9.0.2 Essentials 的 Windows ZIP](https://github.com/GyanD/codexffmpeg/releases/tag/9.0.2)，将 `bin/ffmpeg.exe`、`bin/ffprobe.exe` 和归档里的 `LICENSE` 放到项目的 `runtime` 目录。校验值见 [第三方组件说明](THIRD_PARTY.md)。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe src\medialink_app.py
.\scripts\build.ps1
```

`src/medialink/platforms` 包含两平台的解析和 B 站扫码认证。任务调度、媒体传输、存储和界面由两平台共用。参见 [3.0 计划](docs/plans/3.0.md)、[变更记录](CHANGELOG.md) 和 [第三方组件](THIRD_PARTY.md)。

运行自动化测试：

```powershell
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
