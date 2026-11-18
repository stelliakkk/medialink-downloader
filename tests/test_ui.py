from dataclasses import replace
import io
import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from medialink.diagnostics import LOGGER
from medialink.models import Account, Formats, Output, Part, Quality, Track, UserError, Video
from medialink.platforms.bilibili import Bilibili
from medialink.storage import Storage
from medialink.tasks import SavedMedia, State
from medialink.ui.window import MainWindow
from medialink.workers import Worker


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.storage = Storage(Path(self.temp.name))
        self.window = MainWindow(self.storage)
        self.addCleanup(self.close_window)
        self.part = Part(1, 123, "测试", 2)
        self.video = Video("BV1eknB6DE37", "测试", "作者", "", (self.part,))
        self.track = Track((), "avc1", 1000, 1920, 1080)

    def wait(self):
        deadline = monotonic() + 5
        while self.window.worker or self.window.queue.worker:
            self.app.processEvents()
            if monotonic() > deadline:
                self.fail("Worker did not finish")
            sleep(.005)
        self.app.processEvents()

    def close_window(self):
        self.window.close()
        self.wait()

    def test_expired_account_is_cleared_even_when_resolve_fails(self):
        self.storage.save_cookies({"SESSDATA": "not-a-real-cookie"})
        self.window.cookies = self.storage.load_cookies()
        self.window.account = Account("测试账号", False)
        self.window._account_display()
        self.window.url.setText(self.video.url)
        with patch.object(Bilibili, "account", return_value=None), patch.object(Bilibili, "resolve", side_effect=UserError("视频不可用")):
            self.window._resolve()
            self.wait()
        self.assertEqual(self.window.account_state.full_text, "B 站未登录")
        self.assertEqual(self.window.cookies, {})
        self.assertFalse(self.storage.credential.exists())

    def test_network_verification_failure_does_not_erase_session(self):
        self.storage.save_cookies({"SESSDATA": "not-a-real-cookie"})
        self.window.cookies = self.storage.load_cookies()
        with patch.object(Bilibili, "account", side_effect=UserError("网络不可用")):
            self.window._check_account()
            self.wait()
        self.assertEqual(self.window.account_state.full_text, "B 站登录待验证")
        self.assertTrue(self.window.cookies)
        self.assertTrue(self.storage.credential.exists())

    def test_highest_quality_snapshot_prevents_false_duplicate(self):
        w = self.window
        w.queue.paused = True
        w.video, w.part = self.video, self.part
        w.url.setText(self.video.url)
        w.parsed_link = w.url.text()
        w.formats = Formats((Quality(80, "1080P", self.track),), self.track)
        w._render_video()
        request = w._request(self.part)
        w.store.enqueue([request])
        active = w.store.claim()
        file = self.storage.directory / "old.mp4"
        file.touch()
        w.store.finish(active.id, State.DONE, SavedMedia((file,), 80), "")
        w.formats = Formats((Quality(120, "4K", replace(self.track, width=3840, height=2160)),), self.track)
        w._render_formats()
        newer = w._request(self.part)
        self.assertIsNone(newer.quality)
        self.assertEqual(newer.best_quality, 120)
        self.assertEqual(w.store.enqueue([newer]).added, 1)
        # A different P must not inherit the current P's known highest tier.
        self.assertIsNone(w._request(replace(self.part, number=2)).best_quality)

    def test_unexpected_error_has_safe_identifier_without_secret_message(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        LOGGER.addHandler(handler)
        self.addCleanup(LOGGER.removeHandler, handler)
        messages = []
        def operation(task):
            raise RuntimeError("SESSDATA=secret https://example.invalid/?signed=secret")
        worker = Worker(operation, None, context="抖音解析")
        worker.failed.connect(messages.append)
        worker.run()
        self.assertRegex(messages[0], r"抖音解析未完成.*ML-[A-F0-9]{10}")
        self.assertNotIn("B 站", messages[0])
        self.assertIn("RuntimeError", stream.getvalue())
        self.assertNotIn("secret", stream.getvalue() + messages[0])
        self.assertNotIn(str(Path.cwd()), stream.getvalue())
