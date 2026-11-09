"""Use the maintained Bilibili extractor to check additional public SDR tracks."""

from yt_dlp import YoutubeDL
from yt_dlp.extractor.bilibili import BiliBiliIE
from yt_dlp.utils import DownloadError

from ..models import Part, Video


class QuietLogger:
    def debug(self, _message):
        pass

    warning = error = debug


class BiliTracksIE(BiliBiliIE):
    playback = None

    def extract_formats(self, play_info):
        # The presentation formats omit Bilibili's original backup URLs.
        if (play_info.get("dash") or {}).get("video"):
            self.playback = play_info
        return super().extract_formats(play_info)


def guest_playback(video: Video, part: Part) -> dict | None:
    options = {
        "quiet": True, "logger": QuietLogger(), "cachedir": False,
        "noplaylist": True, "socket_timeout": 8, "extractor_retries": 0,
        "retries": 0, "http_headers": {"Referer": video.url},
    }
    with YoutubeDL(options, auto_init=False) as downloader:
        extractor = BiliTracksIE()
        downloader.add_info_extractor(extractor)
        try:
            info = downloader.extract_info(
                f"{video.url}?p={part.number}", download=False,
                ie_key=extractor.ie_key(), process=False,
            )
        except DownloadError:
            return None
    if not info or info.get("id") not in {f"{video.video_id}_p{part.number}", video.video_id}:
        return None
    seconds = info.get("duration") or 0
    if seconds <= 0 or abs(part.seconds - seconds) > 3:
        return None
    return extractor.playback
