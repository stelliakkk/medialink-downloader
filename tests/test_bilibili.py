from threading import Event
import unittest
from unittest.mock import Mock, patch

from urllib3.exceptions import ProtocolError
from yt_dlp.extractor.common import InfoExtractor

from medialink.models import Cancelled, Part, Source, Video
from medialink.platforms.bilibili import Bilibili, normalize_link, web_get
from medialink.platforms.bili_extractor import BiliTracksIE, guest_playback
from medialink.sources import open_source


class BilibiliTests(unittest.TestCase):
    def setUp(self):
        self.cancel = Event()
        self.part = Part(1, 123, "测试", 2)
        self.video = Video("BV1eknB6DE37", "测试", "作者", "https://i0.hdslb.com/test.jpg", (self.part,))

    def test_cancelling_first_playback_call_prevents_following_requests(self):
        with open_source(Source.BILIBILI, {"SESSDATA": "not-a-real-cookie"}, self.cancel) as api:
            response = Mock()
            def cancelled_response(*args, **kwargs):
                self.cancel.set()
                return response
            with patch.object(api.session, "get", side_effect=cancelled_response) as get:
                with self.assertRaises(Cancelled):
                    api.formats(self.video, self.part)
            self.assertEqual(get.call_count, 1)
            response.close.assert_called_once()

    def test_pre_cancelled_account_does_not_connect(self):
        self.cancel.set()
        with Bilibili(cancel=self.cancel) as api, patch.object(api.session, "get") as get:
            with self.assertRaises(Cancelled):
                api.account()
            get.assert_not_called()

    def test_short_link_cancellation_does_not_follow_redirect(self):
        session, response = Mock(), Mock()
        def redirect(*args, **kwargs):
            self.cancel.set()
            return response
        session.get.side_effect = redirect
        with self.assertRaises(Cancelled):
            normalize_link("https://b23.tv/test", session, self.cancel)
        session.get.assert_called_once()

    def test_cover_protocol_failure_is_optional(self):
        response = Mock()
        response.status_code = 200
        response.raw.read.side_effect = ProtocolError("interrupted thumbnail")
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with Bilibili() as api, patch.object(api.session, "get", return_value=response):
            self.assertEqual(api.cover(self.video), b"")

    def test_cover_cancellation_is_not_swallowed(self):
        self.cancel.set()
        with Bilibili(cancel=self.cancel) as api:
            with self.assertRaises(Cancelled):
                api.cover(self.video)

    def test_guest_extractor_stops_before_next_network_operation(self):
        extractor = BiliTracksIE(self.cancel)
        with patch.object(InfoExtractor, "_request_webpage", side_effect=lambda *a, **kw: self.cancel.set()) as get:
            with self.assertRaises(Cancelled):
                extractor._request_webpage("https://www.bilibili.com/", "test")
            with self.assertRaises(Cancelled):
                extractor._request_webpage("https://www.bilibili.com/", "test")
            get.assert_called_once()

    def test_pre_cancelled_guest_skips_extractor_creation(self):
        self.cancel.set()
        with patch("medialink.platforms.bili_extractor.YoutubeDL") as downloader:
            with self.assertRaises(Cancelled):
                guest_playback(self.video, self.part, self.cancel)
            downloader.assert_not_called()

    def test_auth_request_checks_cancellation_before_connecting(self):
        self.cancel.set()
        session = Mock()
        with self.assertRaises(Cancelled):
            web_get(session, "https://passport.bilibili.com/", cancel=self.cancel)
        session.get.assert_not_called()
