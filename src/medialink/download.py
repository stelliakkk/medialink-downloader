"""Fetch a fresh pair of tracks, then validate and publish the requested files."""

from collections.abc import Callable
import json
from math import ceil
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic

import requests
from urllib3.exceptions import HTTPError

from .models import AssetOptions, Formats, ImageFormat, Output, Part, Track, UserError, Video, check_cancelled
from .platforms.bilibili import UA
from .storage import ROOT
from .tasks import SavedMedia

Progress = Callable[[str, int | None, str], None]


class MediaUnavailable(UserError):
    pass


def _transfer(
    track: Track, target: Path, referer: str, cancel: Event,
    progress: Progress, phase: str, start: int, weight: int,
) -> None:
    for url in track.urls[:4]:
        check_cancelled(cancel)
        try:
            headers = {
                "User-Agent": UA, "Referer": referer, "Accept-Encoding": "identity", "Range": "bytes=0-",
            }
            with requests.get(url, headers=headers, stream=True, timeout=(6, 8)) as response:
                if response.status_code not in (200, 206):
                    continue
                total = int(response.headers.get("Content-Length") or 0)
                if response.status_code == 206:
                    match = re.fullmatch(r"bytes 0-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                    if not match or int(match[1]) + 1 != int(match[2]):
                        continue
                    total = int(match[2])
                seen = 0
                last_update = monotonic()
                progress(phase, start, "正在连接媒体服务器")
                with target.open("wb") as file:
                    while block := response.raw.read1(256 * 1024):
                        check_cancelled(cancel)
                        file.write(block)
                        seen += len(block)
                        if monotonic() - last_update >= 0.12:
                            detail = f"{seen / 1048576:.1f} MB"
                            if total:
                                detail += f" / {total / 1048576:.1f} MB"
                            progress(phase, start + int(weight * min(1, seen / total)) if total else None, detail)
                            last_update = monotonic()
                if seen and (not total or seen == total):
                    progress(phase, start + weight, f"{seen / 1048576:.1f} MB")
                    return
        except (requests.RequestException, HTTPError):
            continue
    raise MediaUnavailable(f"{phase}失败，媒体地址过期或网络暂时不可用。")


def _run(args: list[str], cancel: Event) -> bytes:
    check_cancelled(cancel)
    with subprocess.Popen(
        args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW,
    ) as process:
        try:
            while True:
                check_cancelled(cancel)
                try:
                    stdout, _ = process.communicate(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
        if process.returncode:
            raise UserError("媒体处理失败。请尝试重新下载，或选择其他画质。")
        return stdout


def _probe(tool: str, file: Path, cancel: Event) -> dict:
    return json.loads(_run([tool, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(file)], cancel))


def _verify(info: dict, kind: str, expected_seconds: int | float, track: Track | None = None,
            *, audio_required: bool = True) -> None:
    by_type = {stream["codec_type"]: stream for stream in info["streams"]}
    audio = by_type.get("audio")
    if (kind == "mp3" or audio_required) and not audio:
        raise UserError("文件缺少音轨，下载未保存。")
    if kind == "mp4":
        video = by_type.get("video", {})
        if track is None or (video.get("width"), video.get("height")) != (track.width, track.height):
            raise UserError("视频尺寸与所选档位不一致，下载未保存。")
    elif audio.get("codec_name") != "mp3":
        raise UserError("音频格式与所选格式不一致，下载未保存。")
    streams = [by_type["video"]] if kind == "mp4" else []
    if audio:
        streams.append(audio)
    duration = float(info["format"].get("duration") or 0)
    for stream in streams:
        seconds = float(stream.get("duration") or duration)
        if seconds <= 0 or (expected_seconds > 0 and abs(expected_seconds - seconds) > 3):
            raise UserError("媒体时长与视频信息不一致，可能下载不完整。")


def _filename(video: Video, part: Part, quality: str) -> str:
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", video.title).strip(" .")
    title = title[:70].strip(" .") or video.source.label
    segment = f" · P{part.number}" if len(video.parts) > 1 else ""
    safe_quality = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", quality)[:24].strip(" .")
    suffix = f" · {safe_quality}" if safe_quality else ""
    return f"{title}{segment} [{video.video_id}]{suffix}"


def _publish(folder: Path, pending: list[tuple[Path, str]], cancel: Event) -> tuple[Path, ...]:
    for number in range(1, 1000):
        check_cancelled(cancel)
        extra = f" ({number})" if number > 1 else ""
        destinations = [folder / (name + extra + source.suffix) for source, name in pending]
        if any(path.exists() for path in destinations):
            continue
        moved: list[tuple[Path, Path]] = []
        try:
            for (source, _), dest in zip(pending, destinations, strict=True):
                source.rename(dest)  # On Windows rename fails when the destination exists.
                moved.append((source, dest))
        except OSError as exc:
            for source, dest in reversed(moved):
                dest.rename(source)
            if isinstance(exc, FileExistsError):
                continue
            raise
        return tuple(destinations)
    raise UserError("保存目录中存在太多同名文件，请更换目录。")


def _export_mp3(base: list[str], audio: Path, target: Path, ffprobe: str,
                seconds: int | float, cancel: Event, progress: Progress) -> None:
    progress("转换 MP3", 95, "正在将音轨编码为 MP3")
    _run(base + ["-i", str(audio), "-map", "0:a:0", "-c:a", "libmp3lame", "-b:a", "320k", str(target)], cancel)
    _verify(_probe(ffprobe, target, cancel), "mp3", seconds)


def _slide_canvas(image: Track) -> Track:
    width, height = (image.width, image.height) if image.width and image.height else (1080, 1920)
    scale = min(1, 1920 / max(width, height), 1080 / min(width, height))
    return Track((), "h264", 0, max(2, round(width * scale / 2) * 2),
                 max(2, round(height * scale / 2) * 2))


def _asset_suffix(info: dict, kind: str) -> str:
    streams = {stream["codec_type"]: stream["codec_name"] for stream in info["streams"]}
    container = info["format"]["format_name"]
    if kind == "图片":
        suffix = {
            "mjpeg": "jpg", "png": "png", "apng": "png", "webp": "webp", "gif": "gif",
            "bmp": "bmp", "tiff": "tif", "jpeg2000": "jp2", "av1": "avif",
        }.get(streams.get("video")) if container.endswith("_pipe") or container in ("apng", "gif", "avif") else None
    elif kind == "片段":
        suffix = "mp4" if "mp4" in container.split(",") else {
            "matroska,webm": "webm", "mpegts": "ts",
        }.get(container)
        if "video" not in streams:
            suffix = None
    else:
        suffix = "m4a" if "mp4" in container.split(",") else {
            "mp3": "mp3", "aac": "aac", "flac": "flac", "wav": "wav", "ogg": "ogg",
        }.get(container)
        if "audio" not in streams:
            suffix = None
    if not suffix:
        raise UserError(f"抖音返回了无法识别的{kind}格式。")
    return "." + suffix


def _convert_picture(raw: Path, suffix: str, ffmpeg: str, cancel: Event) -> tuple[Path, str]:
    if suffix in (".png", ".gif"):
        return raw, suffix
    if suffix == ".webp":
        with raw.open("rb") as file:
            header = file.read(21)
        if len(header) == 21 and header[12:16] == b"VP8X" and header[20] & 0x02:
            return raw, suffix  # An animated WebP must keep its frames.
    destination = raw.with_suffix(".png")
    _run([ffmpeg, "-nostdin", "-v", "error", "-y", "-i", str(raw),
          "-map", "0:v:0", "-frames:v", "1", "-c:v", "png", "-update", "1", str(destination)], cancel)
    return destination, ".png"


def _save_note_assets(resolve_formats: Callable[[Video, Part], Formats], video: Video, part: Part,
                      folder: Path, temp: Path, ffmpeg: str, ffprobe: str, options: AssetOptions,
                      cancel: Event, progress: Progress) -> SavedMedia:
    target = temp / "assets"
    target.mkdir()
    for attempt in range(2):
        progress("获取下载地址", 0, "正在查询可单独保存的图文素材")
        formats = resolve_formats(video, part)
        assets = []
        for index, slide in enumerate(formats.slides, 1):
            if slide.image and (options.include_clip_covers or not slide.is_clip_cover):
                name = "图片"
                if slide.is_live:
                    name = "实况静帧"
                elif slide.is_clip_cover or slide.motion_unavailable:
                    name = "封面"
                assets.append((f"{index:02d}-{name}", "图片", slide.image))
            if slide.clip:
                name = "实况片段" if slide.is_live else "片段"
                assets.append((f"{index:02d}-{name}", "片段", slide.clip))
        if formats.audio:
            assets.append(("配乐", "音频", formats.audio))
        if not assets:
            raise UserError("抖音没有返回可单独保存的素材。")
        filenames = []
        try:
            for index, (name, kind, track) in enumerate(assets):
                raw = temp / "asset.media"
                start, end = 95 * index // len(assets), 95 * (index + 1) // len(assets)
                _transfer(track, raw, video.url, cancel, progress, f"下载{kind}", start, end - start)
                suffix = _asset_suffix(_probe(ffprobe, raw, cancel), kind)
                if kind == "图片" and options.image_format is ImageFormat.PNG and suffix not in (".png", ".gif"):
                    progress("转换图片", end, f"正在处理 {name}")
                    raw, suffix = _convert_picture(raw, suffix, ffmpeg, cancel)
                filename = name + suffix
                raw.replace(target / filename)
                filenames.append(filename)
            break
        except MediaUnavailable:
            if attempt:
                raise
            for filename in filenames:
                (target / filename).unlink()
            progress("刷新媒体地址", None, "正在重新获取图文素材")
    progress("保存文件", 98, "正在写入素材文件夹")
    (published,) = _publish(folder, [(target, _filename(video, part, "图文素材"))], cancel)
    notice = " · 有片段未提供独立地址" if any(s.motion_unavailable for s in formats.slides) else ""
    progress("下载完成", 100, f"已保存 {len(filenames)} 个文件{notice}")
    return SavedMedia(tuple(published / filename for filename in filenames), label="图文素材" + notice)


def _save_note(resolve_formats: Callable[[Video, Part], Formats], video: Video, part: Part,
               output: Output, folder: Path, temp: Path, ffmpeg: str, ffprobe: str,
               cancel: Event, progress: Progress) -> SavedMedia:
    audio = temp / "music.media"
    for attempt in range(2):
        check_cancelled(cancel)
        progress("获取下载地址", 0, "正在查询图文图片和配乐")
        formats = resolve_formats(video, part)
        if output is not Output.AUDIO and formats.has_motion:
            raise UserError("这条图文含视频片段，请选择「分开保存素材」。")
        if output is not Output.VIDEO and formats.audio is None:
            raise UserError("这条图文没有可导出的配乐，请选择视频 MP4。")
        images = []
        try:
            if output is not Output.AUDIO:
                count = len(formats.slides)
                for index, slide in enumerate(formats.slides):
                    file = temp / f"image-{index}.media"
                    start, end = 60 * index // count, 60 * (index + 1) // count
                    _transfer(slide.image, file, video.url, cancel, progress, f"下载图片 {index + 1}/{count}", start, end - start)
                    images.append(file)
            if formats.audio:
                start = 60 if images else 0
                _transfer(formats.audio, audio, video.url, cancel, progress, "下载配乐", start, 80 - start)
            break
        except MediaUnavailable:
            if attempt:
                raise
            progress("刷新媒体地址", None, "正在重新获取图文素材")

    seconds = len(images) * 3.0
    if formats.audio:
        info = _probe(ffprobe, audio, cancel)
        seconds = float(info["format"].get("duration") or 0)
        if seconds <= 0:
            raise UserError("无法读取图文配乐的时长。")

    pending = []
    base = [ffmpeg, "-nostdin", "-v", "error"]
    if images:
        canvas = _slide_canvas(formats.slides[0].image)
        size = f"{canvas.width}:{canvas.height}"
        filters = (f"scale={size}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
                   f"pad={size}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
                   "loop=loop=-1:size=1:start=0,setpts=N/(30*TB),fps=30")
        frame_count = max(ceil(seconds * 30), len(images))
        segments = []
        for index, image in enumerate(images):
            progress("合成图文视频", 81 + 10 * index // len(images), f"正在处理第 {index + 1} / {len(images)} 张")
            segment = temp / f"slide-{index}.mp4"
            frames = frame_count * (index + 1) // len(images) - frame_count * index // len(images)
            _run(base + ["-i", str(image), "-map", "0:v:0", "-vf", filters, "-frames:v", str(frames),
                         "-an", "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p", str(segment)], cancel)
            segments.append(segment)
        playlist = temp / "slides.txt"
        playlist.write_text("".join(f"file '{file.name}'\n" for file in segments), encoding="ascii")
        mp4 = temp / "output.mp4"
        inputs = ["-f", "concat", "-safe", "1", "-i", str(playlist)]
        args = ["-map", "0:v:0", "-c:v", "copy"]
        if formats.audio:
            inputs += ["-i", str(audio)]
            args += ["-map", "1:a:0", "-c:a", "aac", "-b:a", "192k"]
        _run(base + inputs + args + ["-movflags", "+faststart", str(mp4)], cancel)
        _verify(_probe(ffprobe, mp4, cancel), "mp4", seconds, canvas, audio_required=bool(formats.audio))
        pending.append((mp4, _filename(video, part, "图文")))
    if output is not Output.VIDEO:
        mp3 = temp / "output.mp3"
        _export_mp3(base, audio, mp3, ffprobe, seconds, cancel, progress)
        pending.append((mp3, _filename(video, part, "图文配乐")))
    progress("保存文件", 98, "正在写入最终文件名")
    files = _publish(folder, pending, cancel)
    progress("下载完成", 100, " · ".join(file.suffix[1:].upper() for file in files))
    return SavedMedia(files, label="图文合成" if images else "")


def save_media(
    resolve_formats: Callable[[Video, Part], Formats], video: Video, part: Part, quality_code: int | None,
    output: Output, folder: Path, cancel: Event, progress: Progress, *, asset_options: AssetOptions = AssetOptions(),
) -> SavedMedia:
    ffmpeg, ffprobe = (str(ROOT / "runtime" / exe) for exe in ("ffmpeg.exe", "ffprobe.exe"))
    if not all(Path(tool).is_file() for tool in (ffmpeg, ffprobe)):
        raise UserError("缺少随包的 FFmpeg 工具。请完整解压便携包后再启动。")
    folder.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".medialink-", dir=folder) as temporary:
        temp = Path(temporary)
        if output is Output.ASSETS:
            if not video.is_note:
                raise UserError("「分开保存素材」适用于抖音图文。")
            return _save_note_assets(resolve_formats, video, part, folder, temp, ffmpeg, ffprobe,
                                     asset_options, cancel, progress)
        if video.is_note:
            return _save_note(resolve_formats, video, part, output, folder, temp, ffmpeg, ffprobe, cancel, progress)
        video_path = temp / "video.m4s"
        audio_path = temp / "audio.m4s"
        selected_code = quality_code
        quality = None
        for attempt in range(2):
            check_cancelled(cancel)
            progress("获取下载地址", 0, "正在查询当前可用的媒体轨道")
            formats = resolve_formats(video, part)
            if output is not Output.AUDIO:
                quality = formats.select(selected_code)
                selected_code = quality.code
            track = quality.track if quality else (formats.select(None).track if formats.audio is None else None)
            audio_input = audio_path
            try:
                if track:
                    _transfer(track, video_path, video.url, cancel, progress, "下载画面", 0, 76)
                    combined = track.combined
                    if combined is None:
                        combined = any(stream["codec_type"] == "audio"
                                       for stream in _probe(ffprobe, video_path, cancel)["streams"])
                    if combined:
                        audio_input = video_path
                if audio_input == audio_path:
                    if formats.audio is None:
                        raise UserError("网页未提供可导出的音轨。")
                    start = 76 if track else 0
                    _transfer(formats.audio, audio_path, video.url, cancel, progress, "下载音轨", start, 90 - start)
                break
            except MediaUnavailable:
                if attempt:
                    raise
                progress("刷新媒体地址", None, "正在保留原画质重新尝试")

        pending = []
        base = [ffmpeg, "-nostdin", "-v", "error"]
        if quality and quality.track:
            progress("合并 MP4", 92, "保留原始画面与音轨")
            mp4 = temp / "output.mp4"
            inputs = ["-i", str(video_path)]
            if audio_input != video_path:
                inputs += ["-i", str(audio_input)]
            audio_map = "0:a:0" if audio_input == video_path else "1:a:0"
            _run(base + inputs + ["-map", "0:v:0", "-map", audio_map,
                         "-c", "copy", "-movflags", "+faststart", str(mp4)], cancel)
            _verify(_probe(ffprobe, mp4, cancel), "mp4", part.seconds, quality.track)
            pending.append((mp4, _filename(video, part, quality.label)))
        if output is not Output.VIDEO:
            mp3 = temp / "output.mp3"
            _export_mp3(base, audio_input, mp3, ffprobe, part.seconds, cancel, progress)
            pending.append((mp3, _filename(video, part, "")))
        progress("保存文件", 98, "正在写入最终文件名")
        files = _publish(folder, pending, cancel)
        progress("下载完成", 100, " · ".join(file.suffix[1:].upper() for file in files))
        return SavedMedia(files, quality.code if quality else None, quality.label if quality else "")
