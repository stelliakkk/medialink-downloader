# MediaLink 下载器

MediaLink Downloader · Windows x64 · v3.0.6

在一个窗口下载哔哩哔哩和抖音的普通视频及抖音图文。支持选画质、保存 MP4、导出 MP3、分开保存图文素材，以及共用的下载队列和历史。程序在本机解析和保存文件。请下载你有权保存的内容。

[下载最新完整便携版](https://github.com/stelliakkk/medialink-downloader/releases/latest) · [v3.0.6 更新说明](docs/releases/v3.0.6.md)。首次使用请选择 `win-x64.zip`；单独 EXE 需要完整目录中的运行库，不能独立启动。

## 使用

1. 完整解压便携 ZIP，双击 `MediaLinkDownloader.exe`，并保留同目录的 `_internal` 和 `runtime`。
2. 粘贴 B 站或抖音的链接、分享文本或短链，点「解析链接」。B 站多分 P 投稿可选择单个或多个分 P。
3. 确认画质、输出和保存目录，点「开始下载」进入队列。「批量添加链接」一次最多接受 50 条，两平台可以混合粘贴。
4. 在「队列」暂停后续任务、继续、取消当前项或移除等待项。在「历史」按结果筛选，打开已保存文件或目录，将失败、中断、取消或文件缺失的任务重新入队。

抖音解析使用本机已安装的 Microsoft Edge 和独立临时游客会话。画质以网页返回的实际分辨率为准。网页要求登录、验证或无法播放时，任务会提示失败。B 站可用右上角的「B 站登录」扫码，获取账号可用的画质。

普通视频的 MP4 保留源画面和音轨。抖音静态图文可以合成 MP4，也可以选择「分开保存素材」，按顺序保存图片、可用的独立视频片段和配乐。图片格式默认 PNG，也可选择原始格式。普通视频片段的封面默认另存，也可取消勾选。实况照片分别保存静帧和独立短片，文件名共用序号。图片中的 GIF 和动画 WebP 保留原格式，避免丢失动画。只有可用配乐的作品才可单独导出 MP3。重启后，在「队列」点击「继续队列」处理剩余任务。

图文素材在保存前会逐帧解码校验，较长的视频片段需要额外处理时间，期间可以取消。素材模式的配乐保留原格式；选择「仅音频 MP3」才会转为 MP3。

「最高可用」在执行时重新获取画质；去重时会参考当前解析出的最高档位，已有低画质文件不会阻止保存新获得的高画质。如果当前分 P 的最高档位尚未查询，程序不会用旧的已完成记录拦截该任务；等待或运行中的相同任务仍会去重。

## 数据与升级

默认保存到 `Downloads\MediaLinkDownloader`。设置、任务数据库和经 Windows DPAPI 加密的 B 站会话保存在可执行文件旁的 `data`。目录不可写时使用 `%LOCALAPPDATA%\MediaLinkDownloader`。

未分类错误会显示 `ML-` 开头的错误编号。本机 `data\diagnostics.log` 仅记录编号、操作阶段、异常类型和代码位置，不记录异常正文、签名媒体链接、二维码票据或 cookies；日志自动轮换，最多保留三个 256 KB 文件。

从旧版升级时，先关闭新旧程序，再把旧版的 `data` 复制到新版目录后启动。如果旧版使用系统回退目录，MediaLink 的数据在 `%LOCALAPPDATA%\MediaLinkDownloader`，更早的 B 站下载器数据在 `%LOCALAPPDATA%\BiliDownloader`。新版自动给原任务和历史补上 B 站来源，保留任务 ID、分 P 和已保存文件的位置。旧版数据副本可作为回退备份。

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

下载与转码回归测试需要完整的 `runtime`。构建脚本在打包前运行测试，并在结束或失败时恢复终端的环境变量与工作目录。审查和修复记录见 [v3.0.5 审查报告](docs/reviews/v3.0.5-code-review.md) 与 [v3.0.6 修复验收](docs/reviews/v3.0.6-fixes.md)。

公开发布时使用 `requirements-release.lock` 固定完整依赖，运行 `scripts/release_sources.py` 收集上游源码；提交版本后运行 `scripts/package_release.py`，生成源码 ZIP、第三方源码 ZIP、附带许可文件的便携 ZIP 和 `SHA256SUMS.txt`。打包时排除本机 `data`、下载、日志及备份。
