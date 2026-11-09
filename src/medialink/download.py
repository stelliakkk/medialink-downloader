"""Fetch a fresh pair of tracks, then validate and publish the requested files."""

from collections.abc import Callable
import json
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic

import requests
from urllib3.exceptions import HTTPError

from .models import Formats, Output, Part, Track, UserError, Video, check_cancelled
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


def _verify(info: dict, kind: str, expected_seconds: int, track: Track | None = None) -> None:
    by_type = {stream["codec_type"]: stream for stream in info["streams"]}
    audio = by_type.get("audio")
    if not audio:
        raise UserError("文件缺少音轨，下载未保存。")
    if kind == "mp4":
        video = by_type.get("video", {})
        if track is None or (video.get("width"), video.get("height")) != (track.width, track.height):
            raise UserError("视频尺寸与所选档位不一致，下载未保存。")
    elif audio.get("codec_name") != "mp3":
        raise UserError("音频格式与所选格式不一致，下载未保存。")
    streams = (audio, by_type["video"]) if kind == "mp4" else (audio,)
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


def save_media(
    resolve_formats: Callable[[Video, Part], Formats], video: Video, part: Part, quality_code: int | None,
    output: Output, folder: Path, cancel: Event, progress: Progress,
) -> SavedMedia:
    ffmpeg, ffprobe = (str(ROOT / "runtime" / exe) for exe in ("ffmpeg.exe", "ffprobe.exe"))
    if not all(Path(tool).is_file() for tool in (ffmpeg, ffprobe)):
        raise UserError("缺少随包的 FFmpeg 工具。请完整解压便携包后再启动。")
    folder.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".medialink-", dir=folder) as temporary:
        temp = Path(temporary)
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
            progress("转换 MP3", 95, "正在将原音轨编码为 MP3")
            mp3 = temp / "output.mp3"
            _run(base + ["-i", str(audio_input), "-map", "0:a:0", "-c:a", "libmp3lame", "-b:a", "320k", str(mp3)], cancel)
            _verify(_probe(ffprobe, mp3, cancel), "mp3", part.seconds)
            pending.append((mp3, _filename(video, part, "")))
        progress("保存文件", 98, "正在写入最终文件名")
        files = _publish(folder, pending, cancel)
        progress("下载完成", 100, " · ".join(file.suffix[1:].upper() for file in files))
        return SavedMedia(files, quality.code if quality else None, quality.label if quality else "")
