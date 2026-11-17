from contextlib import nullcontext
import json
from threading import Event
import unittest
from unittest.mock import Mock, patch

from medialink.links import input_link, share_links
from medialink.models import Cancelled, Source, UserError
from medialink.platforms.douyin import parse_note, parse_playback
from medialink.platforms.edge import _StartupError, _note_document, _read_detail, playback_detail


VIDEO_ID = "7705856425225932082"


class DouyinTests(unittest.TestCase):
    def test_mixed_share_text_and_markdown_links(self):
        links = list(share_links(
            "【B 站】 http://b23.tv/BV1eknB6DE37，抖音 "
            "[https://v.douyin.com/MhBcFeo1pJ8/](https://v.douyin.com/MhBcFeo1pJ8/)"
        ))
        self.assertEqual(links[:2], ["https://b23.tv/BV1eknB6DE37", "https://v.douyin.com/MhBcFeo1pJ8/"])
        self.assertEqual([input_link(link)[0] for link in links], [Source.BILIBILI, Source.DOUYIN, Source.DOUYIN])
        self.assertEqual(list(share_links("https://fake.douyin.com/video/123 https://douyin.com.evil.test/video/123")), [])

    def test_portrait_formats_and_pure_audio_from_cdn(self):
        def track(width, height, bitrate, suffix):
            return {"bit_rate": bitrate, "play_addr": {"width": width, "height": height, "url_list": [
                "https://v26-web.douyinvod.com/media/" + suffix,
                "https://douyinvod.com.evil.test/file.mp4",
            ]}}
        item = {"aweme_id": VIDEO_ID, "desc": "示例", "author": {"nickname": "作者"}, "video": {
            "duration": 233567,
            "bit_rate": [track(720, 1280, 900_000, "low.mp4"),
                         track(1080, 1920, 2_000_000, "media-video-avc1/"),
                         track(1080, 1920, 1_000_000, "lower.mp4")],
            "bit_rate_audio": [{"audio_meta": {"bitrate": 96_000, "url_list": {
                "main_url": "https://v26-web.douyinvod.com/audio.m4a",
            }}}],
        }}
        data = parse_playback(item, VIDEO_ID)
        self.assertEqual((data.video.source, data.part.seconds), (Source.DOUYIN, 234))
        self.assertEqual([quality.code for quality in data.formats.qualities], [1080, 720])
        self.assertEqual(data.formats.select(1080).track.height, 1920)
        self.assertFalse(data.formats.select(1080).track.combined)
        self.assertEqual(len(data.formats.select(1080).track.urls), 1)
        self.assertEqual(data.formats.audio.bitrate, 96_000)

    def test_rejects_wrong_video_and_photo_posts(self):
        for item in ({"aweme_id": "other"}, {"aweme_id": VIDEO_ID, "images": [{}]}):
            with self.assertRaises(UserError):
                parse_playback(item, VIDEO_ID)

    def test_note_uses_matching_page_data_and_preserves_image_order(self):
        images = ["https://p3.douyinpic.com/second.jpg", "https://p9.douyinpic.com/first.jpg"]
        music = "https://lf26-music-east.douyinstatic.com/music.mp3"
        item = {
            "awemeId": VIDEO_ID, "desc": "测试图文",
            "images": [{"urlList": [url], "width": 1536, "height": 2048} for url in images],
            "music": {"duration": 19, "playUrl": {"urlList": [music]}},
        }
        results = [{"awemeId": "other", "images": [{"urlList": [images[0]]}]}, {"aweme": item}]
        payload = json.dumps([1, f"7:{json.dumps(results)}\n"])
        document = f"<html><script>self.__pace_f.push({payload})</script></html>"
        self.assertIsNone(_note_document(document, "1234567890"))
        note = parse_note(_note_document(document, VIDEO_ID), VIDEO_ID)
        self.assertEqual(note.video.url, f"https://www.douyin.com/note/{VIDEO_ID}")
        self.assertEqual([slide.image.urls[0] for slide in note.formats.slides], images)
        self.assertEqual(note.formats.audio.urls, (music,))
        self.assertEqual(note.part.seconds, 19)

    def test_note_share_link_with_escaped_colon(self):
        self.assertEqual(input_link(r"分享 https\://v.douyin.com/Example/ 复制"),
                         (Source.DOUYIN, "https://v.douyin.com/Example/"))

    def test_mixed_note_retains_clip_with_its_own_image(self):
        photo = "https://p3.douyinpic.com/img.webp"
        clip = "https://v26.douyinvod.com/clip.mp4"
        result = parse_note({"awemeId": VIDEO_ID, "images": [
            {"urlList": [photo], "clipType": 2},
            {"urlList": [photo], "clipType": 3, "video": {"playAddr": [{"src": clip}]}},
            {"urlList": [photo], "clipType": 4, "video": {"playAddr": [{"src": clip}]}},
            {"urlList": [photo], "video": {"duration": 1400}},
        ]}, VIDEO_ID)
        first, live, video, unavailable = result.formats.slides
        self.assertIsNone(first.clip)
        self.assertEqual(live.clip.urls, (clip,))
        self.assertEqual(live.image.urls, (photo,))
        self.assertTrue(live.is_live)
        self.assertFalse(live.is_clip_cover)
        self.assertTrue(video.is_clip_cover)
        self.assertFalse(video.is_live)
        self.assertTrue(unavailable.motion_unavailable)
        self.assertTrue(result.formats.has_motion)

    def test_browser_reads_only_matching_video_response(self):
        def response(video, request):
            return {"method": "Network.responseReceived", "params": {"requestId": request, "response": {
                "url": f"https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id={video}", "status": 200,
            }}}
        def finished(request):
            return {"method": "Network.loadingFinished", "params": {"requestId": request}}
        socket = Mock()
        item = {"aweme_id": VIDEO_ID}
        socket.recv.side_effect = [json.dumps(message) for message in (
            response("123", "other"), finished("other"), response(VIDEO_ID, "target"), finished("target"),
            {"id": 10, "result": {"body": json.dumps({"aweme_detail": item})}},
        )]
        self.assertEqual(_read_detail(socket, VIDEO_ID, Event()), item)
        reads = [json.loads(call.args[0]) for call in socket.send.call_args_list]
        self.assertEqual([call["params"]["requestId"] for call in reads
                          if call["method"] == "Network.getResponseBody"], ["target"])

    @patch("medialink.platforms.edge._guest_tab")
    def test_retries_startup_failure_but_not_playback_failure(self, guest_tab):
        socket = Mock()
        guest_tab.side_effect = [_StartupError("startup failed"), nullcontext(socket)]
        with patch("medialink.platforms.edge._read_detail", side_effect=UserError("no playback")) as read:
            with self.assertRaisesRegex(UserError, "no playback"):
                playback_detail(VIDEO_ID, Event())
        self.assertEqual(guest_tab.call_count, 2)
        read.assert_called_once()

    @patch("medialink.platforms.edge._guest_tab")
    def test_cancelling_during_failed_startup_skips_retry(self, guest_tab):
        cancel = Event()

        def abort(_cancel):
            cancel.set()
            raise _StartupError("startup failed")

        guest_tab.side_effect = abort
        with self.assertRaises(Cancelled):
            playback_detail(VIDEO_ID, cancel)
        guest_tab.assert_called_once()


if __name__ == "__main__":
    unittest.main()
