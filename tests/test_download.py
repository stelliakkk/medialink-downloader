from dataclasses import replace
from io import BytesIO
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import Mock, patch

from medialink.download import MediaUnavailable, _probe, _publish, _transfer, save_media
from medialink.models import AssetOptions, Formats, ImageFormat, Output, Part, Quality, Slide, Source, Track, Video
from medialink.storage import ROOT


def response(payload: bytes, status=200, headers=None):
    result = Mock()
    result.status_code = status
    result.headers = headers if headers is not None else {"Content-Length": str(len(payload))}
    result.raw = BytesIO(payload)
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    return result


class TransferTests(unittest.TestCase):
    def test_incomplete_range_tries_backup_and_does_not_append_partial_bytes(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "media"
            replies = [response(b"bad", 206, {"Content-Range": "bytes 0-2/9"}), response(b"complete")]
            with patch("medialink.download.requests.get", side_effect=replies):
                _transfer(Track(("https://example.invalid/a", "https://example.invalid/b"), "", 0),
                          target, "", Event(), lambda *args: None, "测试", 0, 100)
            self.assertEqual(target.read_bytes(), b"complete")

    def test_publish_preserves_existing_names_and_rolls_back_partial_pair(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            existing = folder / "video.mp4"
            existing.write_bytes(b"existing")
            pending = folder / "pending.mp4"
            pending.write_bytes(b"new")
            saved = _publish(folder, [(pending, "video")], Event())
            self.assertEqual(saved[0].name, "video (2).mp4")
            self.assertEqual(existing.read_bytes(), b"existing")
            first, second = folder / "a.mp4", folder / "b.mp3"
            first.touch()
            second.touch()
            rename = Path.rename
            def fail_second(source, dest):
                if source == second:
                    raise PermissionError("test publication failure")
                return rename(source, dest)
            with patch.object(Path, "rename", fail_second), self.assertRaises(PermissionError):
                _publish(folder, [(first, "paired"), (second, "paired")], Event())
            self.assertTrue(first.exists() and second.exists())
            self.assertFalse((folder / "paired.mp4").exists())


@unittest.skipUnless((ROOT / "runtime/ffmpeg.exe").is_file() and (ROOT / "runtime/ffprobe.exe").is_file(),
                     "FFmpeg runtime is required for media regression tests")
class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.fixtures = Path(cls.temp.name)
        cls.ffmpeg = str(ROOT / "runtime/ffmpeg.exe")
        cls.ffprobe = str(ROOT / "runtime/ffprobe.exe")
        def make(name, args):
            target = cls.fixtures / name
            subprocess.run([cls.ffmpeg, "-nostdin", "-v", "error", *args, str(target)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True,
                           timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
            return target.read_bytes()
        cls.clip = make("clip.mp4", ["-f", "lavfi", "-i", "testsrc2=size=128x128:rate=20",
                                     "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "2",
                                     "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart"])
        cls.picture = make("image.webp", ["-f", "lavfi", "-i", "color=c=red:size=64x64",
                                          "-frames:v", "1", "-c:v", "libwebp"])
        cls.music = make("music.mp3", ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "2", "-c:a", "libmp3lame"])
        cls.gif = make("animation.gif", ["-i", str(cls.fixtures / "clip.mp4"), "-vf", "fps=3,scale=32:32"])
        cls.animated_webp = make("animation.webp", ["-i", str(cls.fixtures / "clip.mp4"), "-vf", "fps=3,scale=32:32",
                                                   "-c:v", "libwebp_anim", "-loop", "0"])

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name)
        self.part = Part(1, 0, "测试素材", 2)
        self.video = Video("7700000000000000000", "测试素材", "作者", "", (self.part,), Source.DOUYIN, True)
        self.image = Track(("https://example.invalid/image",), "", 0, 64, 64)
        self.clip_track = Track(("https://example.invalid/clip",), "h264", 1000, 128, 128, combined=True)
        self.audio = Track(("https://example.invalid/audio",), "mp3", 128000)
        self.payloads = {"image": self.picture, "clip": self.clip, "audio": self.music}

    def get(self, url, **kwargs):
        return response(self.payloads[url.rsplit("/", 1)[-1]])

    def save(self, formats, options=AssetOptions(ImageFormat.PNG), *, output=Output.ASSETS, video=None):
        return save_media(formats, video or self.video, self.part, None, output, self.folder,
                          Event(), lambda *args: None, asset_options=options)

    def test_mixed_live_assets_convert_png_and_preserve_matching_motion_and_music(self):
        formats = Formats((), self.audio, (Slide(self.image, self.clip_track, is_live=True), Slide(self.image)))
        with patch("medialink.download.requests.get", side_effect=self.get):
            saved = self.save(lambda *args: formats)
        names = {p.name for p in saved.files}
        self.assertEqual(names, {"01-实况静帧.png", "01-实况片段.mp4", "02-图片.png", "配乐.mp3"})
        for file in saved.files:
            if file.suffix == ".png":
                self.assertEqual(file.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertTrue(saved.exists)

    def test_clip_cover_can_be_omitted_without_losing_clip(self):
        formats = Formats((), None, (Slide(self.image, self.clip_track),))
        with patch("medialink.download.requests.get", side_effect=self.get):
            saved = self.save(lambda *args: formats, AssetOptions(ImageFormat.PNG, False))
        self.assertEqual([p.name for p in saved.files], ["01-片段.mp4"])

    def test_original_picture_and_clip_cover_keep_original_format_and_order(self):
        formats = Formats((), None, (Slide(self.image, self.clip_track), Slide(self.image)))
        with patch("medialink.download.requests.get", side_effect=self.get):
            saved = self.save(lambda *args: formats, AssetOptions(ImageFormat.ORIGINAL, True))
        self.assertEqual([p.name for p in saved.files], ["01-封面.webp", "01-片段.mp4", "02-图片.webp"])
        self.assertEqual(saved.files[0].read_bytes(), self.picture)

    def test_truncated_clip_with_readable_index_is_rejected_and_not_published(self):
        self.payloads["clip"] = self.clip[:len(self.clip)//2]
        broken = self.folder / "broken.mp4"
        broken.write_bytes(self.payloads["clip"])
        self.assertGreater(float(_probe(self.ffprobe, broken, Event())["format"]["duration"]), 0)
        broken.unlink()
        formats = Mock(return_value=Formats((), None, (Slide(None, self.clip_track),)))
        with patch("medialink.download.requests.get", side_effect=self.get), self.assertRaises(MediaUnavailable):
            self.save(formats)
        self.assertEqual(formats.call_count, 2)
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_integrity_failure_refreshes_urls_and_can_succeed_on_second_attempt(self):
        replies = [response(self.clip[:len(self.clip)//2]), response(self.clip)]
        formats = Mock(return_value=Formats((), None, (Slide(None, self.clip_track),)))
        with patch("medialink.download.requests.get", side_effect=replies):
            saved = self.save(formats)
        self.assertEqual(formats.call_count, 2)
        self.assertEqual(saved.files[0].read_bytes(), self.clip)

    def test_invalid_picture_is_not_published(self):
        self.payloads["image"] = self.picture[:16]
        with patch("medialink.download.requests.get", side_effect=self.get), self.assertRaises(MediaUnavailable):
            self.save(lambda *args: Formats((), None, (Slide(self.image),)))
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_gif_animation_is_retained_when_png_is_selected(self):
        self.payloads["image"] = self.gif
        with patch("medialink.download.requests.get", side_effect=self.get):
            saved = self.save(lambda *args: Formats((), None, (Slide(self.image),)))
        self.assertEqual(saved.files[0].suffix, ".gif")
        self.assertEqual(saved.files[0].read_bytes(), self.gif)

    def test_animated_webp_is_retained_when_png_is_selected(self):
        self.payloads["image"] = self.animated_webp
        with patch("medialink.download.requests.get", side_effect=self.get):
            saved = self.save(lambda *args: Formats((), None, (Slide(self.image),)))
        self.assertEqual(saved.files[0].suffix, ".webp")
        self.assertEqual(saved.files[0].read_bytes(), self.animated_webp)

    def test_ordinary_video_outputs_are_real_mp4_and_mp3(self):
        formats = Formats((Quality(128, "128P", self.clip_track),), None)
        video = replace(self.video, is_note=False)
        for output, expected in [(Output.VIDEO, {".mp4"}), (Output.AUDIO, {".mp3"}), (Output.BOTH, {".mp4", ".mp3"})]:
            with self.subTest(output=output), patch("medialink.download.requests.get", side_effect=self.get):
                saved = self.save(lambda *args: formats, output=output, video=video)
                self.assertEqual({p.suffix for p in saved.files}, expected)
                for file in saved.files:
                    self.assertGreater(float(_probe(self.ffprobe, file, Event())["format"]["duration"]), 0)
