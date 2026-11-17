from dataclasses import dataclass
import re
from threading import Event
from urllib.parse import urljoin, urlsplit

import requests
from urllib3.exceptions import HTTPError

from ..links import DOUYIN_HOSTS, input_link, trusted_link
from ..models import Formats, Part, Quality, Slide, Source, Track, UserError, Video, check_cancelled
from .edge import playback_detail

POST_PATH = re.compile(r"/(?:share/)?(video|note|slides)/([0-9]{10,24})/?")


def _number(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _asset_urls(values, *domains: str) -> tuple[str, ...]:
    if isinstance(values, str):
        values = (values,)
    if isinstance(values, dict):
        values = tuple(values.values())
    if not isinstance(values, (list, tuple)):
        return ()
    result = []
    for url in values or ():
        if isinstance(url, dict):
            url = url.get("src")
        if not isinstance(url, str):
            continue
        try:
            parsed = urlsplit(url)
            host = parsed.hostname or ""
            if (parsed.scheme == "https"
                    and any(host == domain or host.endswith("." + domain) for domain in domains)
                    and parsed.port in (None, 443) and parsed.username is None and parsed.password is None):
                result.append(url)
        except ValueError:
            continue
    return tuple(dict.fromkeys(result))


def _video_track(address: dict, variant: dict) -> Track | None:
    urls = _asset_urls(address.get("url_list"), "douyinvod.com")
    width, height = _number(address.get("width")), _number(address.get("height"))
    if not urls or not width or not height:
        return None
    # DASH video tracks have no sound. Inspect the container for progressive addresses.
    separate = all("/media-video-" in urlsplit(url).path for url in urls)
    return Track(urls, "hevc" if variant.get("is_h265") else "h264",
                 _number(variant.get("bit_rate")), width, height,
                 str(variant.get("FPS") or ""), False if separate else None)


def _formats(media: dict) -> Formats:
    audios = []
    for variant in media.get("bit_rate_audio") or ():
        meta = variant.get("audio_meta") or {}
        if urls := _asset_urls(meta.get("url_list"), "douyinvod.com"):
            audios.append(Track(urls, str(meta.get("codec_type") or ""), _number(meta.get("bitrate"))))
    audio = max(audios, key=lambda track: track.bitrate, default=None)

    groups: dict[int, Track] = {}
    variants = list(media.get("bit_rate") or ())
    # Some public videos expose a single progressive address and no bitrate list.
    if not variants:
        address = media.get("play_addr_h264") or media.get("play_addr") or {}
        variants = [{"play_addr": address, "is_h265": media.get("is_h265")}]
    for variant in variants:
        track = _video_track(variant.get("play_addr") or {}, variant)
        if track is None or (track.combined is False and audio is None):
            continue
        resolution = min(track.width, track.height)
        current = groups.get(resolution)
        if current is None or track.bitrate > current.bitrate:
            groups[resolution] = track
    if not groups:
        raise UserError("抖音网页未提供可下载的完整视频与音轨。")
    return Formats(tuple(Quality(code, f"{code}P", groups[code]) for code in sorted(groups, reverse=True)), audio)


@dataclass(frozen=True, slots=True)
class Playback:
    video: Video
    part: Part
    formats: Formats


def parse_playback(item: dict, video_id: str) -> Playback:
    if str(item.get("aweme_id")) != video_id or item.get("images"):
        raise UserError("该链接没有指向可下载的抖音普通视频。")
    media = item.get("video") or {}
    duration = _number(media.get("duration") or item.get("duration"))
    if duration <= 0:
        raise UserError("抖音未返回完整视频的时长。")
    title = str(item.get("desc") or "抖音视频").strip() or "抖音视频"
    author = str((item.get("author") or {}).get("nickname") or "抖音作者")
    covers = _asset_urls((media.get("cover") or {}).get("url_list"), "douyinpic.com")
    part = Part(1, 0, title, max(1, round(duration / 1000)))
    return Playback(Video(video_id, title, author, covers[0] if covers else "", (part,), Source.DOUYIN),
                    part, _formats(media))


def parse_note(item: dict, note_id: str) -> Playback:
    images = item.get("images") or []
    if item.get("awemeId") != note_id or not images:
        raise UserError("抖音图文没有返回可用图片。")
    slides = []
    for image in images:
        urls = _asset_urls(image.get("urlList") or image.get("url_list"), "douyinpic.com")
        photo = Track(urls, "", 0, _number(image.get("width")), _number(image.get("height"))) if urls else None
        motion = image.get("video")
        if not isinstance(motion, dict):
            motion = {}
        address = motion.get("playAddr") or motion.get("play_addr") or ()
        if isinstance(address, dict):
            address = address.get("urlList") or address.get("url_list") or ()
        clip_urls = _asset_urls(address, "douyinvod.com")
        if not clip_urls:
            clip_urls = _asset_urls(motion.get("playAddrH265"), "douyinvod.com")
        clip = Track(clip_urls, "", 0) if clip_urls else None
        if not photo and not clip:
            raise UserError("抖音没有提供这条图文的全部画面素材。")
        clip_type = _number(image.get("clipType"))
        is_live = clip_type == 3
        has_motion = bool(motion) or clip_type in (3, 4)
        slides.append(Slide(photo, clip, motion_unavailable=has_motion and clip is None, is_live=is_live))
    music = item.get("music") or {}
    address = music.get("playUrl") or {}
    urls = ()
    if music.get("canNotPlay") is not True:
        urls = _asset_urls(address.get("urlList"), "douyinstatic.com", "douyinvod.com")
    audio = Track(urls, "", 0) if urls else None
    title = next((text.strip() for text in (item.get("desc"), item.get("itemTitle"))
                  if isinstance(text, str) and text.strip()), "抖音图文")
    author = str((item.get("authorInfo") or {}).get("nickname") or "抖音作者")
    seconds = _number(music.get("duration")) if audio else (len(slides) * 3 if not any(s.clip for s in slides) else 0)
    part = Part(1, 0, title, seconds)
    cover = next((slide.image.urls[0] for slide in slides if slide.image), "")
    video = Video(note_id, title, author, cover, (part,), Source.DOUYIN, is_note=True)
    return Playback(video, part, Formats((), audio, tuple(slides)))


class Douyin:
    def __init__(self, cancel: Event):
        self.cancel = cancel
        self.session = requests.Session()
        self.initial: Playback | None = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.session.close()

    def _resolve_post(self, text: str) -> tuple[str, bool]:
        source, link = input_link(text)
        if source is not Source.DOUYIN:
            raise UserError("请粘贴抖音视频或图文链接。")
        for _ in range(5):
            check_cancelled(self.cancel)
            parsed = urlsplit(link)
            if parsed.hostname != "v.douyin.com":
                if match := POST_PATH.fullmatch(parsed.path):
                    return match[2], match[1] != "video"
                break
            try:
                with self.session.get(link, allow_redirects=False, stream=True, timeout=(5, 8)) as response:
                    target = urljoin(link, response.headers.get("Location", ""))
                    if not response.is_redirect or not trusted_link(target, DOUYIN_HOSTS):
                        break
                    link = target
            except requests.RequestException:
                raise UserError("连接抖音分享链接失败，请检查网络后重试。") from None
        raise UserError("抖音链接已失效，或没有指向普通视频或图文作品。")

    def _playback(self, video_id: str, is_note: bool) -> Playback:
        item = playback_detail(video_id, self.cancel, is_note=is_note)
        return parse_note(item, video_id) if is_note else parse_playback(item, video_id)

    def resolve(self, text: str) -> tuple[Video, Part]:
        video_id, is_note = self._resolve_post(text)
        self.initial = self._playback(video_id, is_note)
        return self.initial.video, self.initial.part

    def formats(self, video: Video, _part: Part) -> Formats:
        initial, self.initial = self.initial, None
        if initial and initial.video.video_id == video.video_id and initial.video.is_note == video.is_note:
            return initial.formats
        return self._playback(video.video_id, video.is_note).formats

    def cover(self, video: Video) -> bytes:
        if not video.cover_url:
            return b""
        try:
            with self.session.get(video.cover_url, timeout=(5, 8), stream=True, allow_redirects=False) as response:
                if response.status_code == 200:
                    return response.raw.read(2 * 1024 * 1024, decode_content=True)
        except (OSError, requests.RequestException, HTTPError):
            pass
        return b""
