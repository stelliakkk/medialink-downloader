"""Bilibili's web interfaces. Keep playback and login traffic separate from file transfers."""

from hashlib import md5
from dataclasses import replace
import re
import time
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

import requests

from .extractor import guest_playback
from .models import Account, Formats, Part, Quality, Track, UserError, Video

HOME = "https://www.bilibili.com/"
API = "https://api.bilibili.com"
PASSPORT = "https://passport.bilibili.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
TIMEOUT = (6, 9)
WEB_COOKIES = frozenset(("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "buvid3"))
VIDEO_HOSTS = frozenset(("www.bilibili.com", "bilibili.com", "m.bilibili.com"))
LINK_HOSTS = VIDEO_HOSTS | {"b23.tv"}
VIDEO_PATH = re.compile(r"/video/(BV[A-Za-z0-9]{10}|av[1-9][0-9]*)/?")
SHARE_LINK = re.compile(r"(?:https?://)?(?:[\w.-]+\.)?(?:bilibili\.com|b23\.tv)/[^\s<>\"【】]+", re.I)
WBI_ORDER = (
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61,
    26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36,
    20, 34, 44, 52,
)
QUALITY_NAMES = {
    127: "8K 超高清", 126: "杜比视界", 125: "HDR 真彩", 120: "4K 超高清",
    116: "1080P 60 帧", 112: "1080P 高码率", 80: "1080P 高清",
    74: "720P 60 帧", 64: "720P 准高清", 32: "480P 标清", 16: "360P 流畅",
}


class ApiError(UserError):
    def __init__(self, message: str, code: int):
        super().__init__(message)
        self.code = code


def json_response(response: requests.Response) -> dict:
    if response.status_code != 200:
        raise UserError(f"B 站服务暂时不可用（HTTP {response.status_code}），请稍后重试。")
    try:
        result = response.json()
    except ValueError:
        raise UserError("B 站返回了无法读取的响应，请稍后重试。") from None
    if not isinstance(result, dict):
        raise UserError("B 站返回了无法读取的响应，请稍后重试。")
    return result


def response_data(result: dict) -> dict:
    code = result.get("code")
    if code == -101:
        raise ApiError("B 站登录已失效，请重新扫码登录。", code)
    if code in (-352, -412, -509):
        raise ApiError("B 站暂时限制了访问，请稍后重试。", code)
    if code in (-403, -404, 62002, 62004, 62012):
        raise ApiError("该视频不存在、已下架，或当前账号无法访问。", code)
    if code != 0 or not isinstance(result.get("data"), dict):
        raise UserError("B 站没有返回所需信息，请稍后重试。")
    return result["data"]


def web_get(session: requests.Session, url: str, **options) -> requests.Response:
    try:
        return session.get(url, timeout=TIMEOUT, allow_redirects=False, **options)
    except requests.RequestException:
        raise UserError("连接 B 站失败，请检查网络后重试。") from None


def trusted_link(url: str, hosts: frozenset[str] | set[str]) -> bool:
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https" and parsed.hostname in hosts
            and parsed.port in (None, 443) and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        return False


def request_session(cookies: dict[str, str] | None = None) -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Referer": HOME, "Origin": HOME.rstrip("/")})
    for name, value in (cookies or {}).items():
        if name in WEB_COOKIES:
            session.cookies.set(name, value, domain=".bilibili.com", path="/", secure=True)
    return session


def share_links(text: str):
    for match in SHARE_LINK.finditer(text):
        yield match[0].rstrip("。，、；！？）)]")


def normalize_link(text: str, session: requests.Session) -> tuple[str, int]:
    link = next(share_links(text), None)
    if link is None:
        raise UserError("请粘贴 B 站普通视频链接或 b23.tv 分享链接。")
    if not re.match(r"https?://", link, re.I):
        link = "https://" + link
    if link.lower().startswith("http://"):
        link = "https://" + link[7:]
    if not trusted_link(link, LINK_HOSTS):
        raise UserError("链接需要来自 bilibili.com 或 b23.tv。")
    original_page = parse_qs(urlsplit(link).query).get("p", ["1"])[0]
    for _ in range(5):
        parsed = urlsplit(link)
        if parsed.hostname in VIDEO_HOSTS:
            video_id = VIDEO_PATH.fullmatch(parsed.path)
            if not video_id:
                break
            page = parse_qs(parsed.query).get("p", [original_page])[0]
            if not re.fullmatch(r"[0-9]{1,6}", page) or int(page) < 1:
                raise UserError("链接中的分 P 编号无效。")
            return video_id[1], int(page)
        with web_get(session, link, stream=True) as response:
            target = urljoin(link, response.headers.get("Location", ""))
            if not response.is_redirect or not trusted_link(target, LINK_HOSTS):
                break
            link = target
    raise UserError("这个链接没有指向普通投稿视频。")


def _track(data: dict) -> Track | None:
    primary = data.get("baseUrl") or data.get("base_url")
    backups = data.get("backupUrl") or data.get("backup_url") or []
    urls = tuple(dict.fromkeys(
        url for url in (primary, *backups)
        if isinstance(url, str) and url.startswith("https://")
    ))
    if not urls:
        return None
    # Bilibili also returns peer CDN endpoints. Prefer its conventional CDN
    # when the same track has an official backup there.
    ordered = tuple(sorted(urls, key=lambda url: not (urlsplit(url).hostname or "").startswith("upos-")))
    return Track(
        ordered, str(data.get("codecs", "")), int(data.get("bandwidth") or 0),
        int(data.get("width") or 0), int(data.get("height") or 0),
        str(data.get("frameRate") or data.get("frame_rate") or ""),
    )


def parse_formats(data: dict, seconds: int) -> Formats:
    if data.get("is_preview") or (
        seconds >= 10 and 0 < int(data.get("timelength") or 0) < (seconds - 3) * 1000
    ):
        raise UserError("B 站当前只提供试看片段，无法下载完整视频。")
    dash = data.get("dash") or {}
    tracks: dict[int, list[Track]] = {}
    for stream in dash.get("video") or []:
        track = _track(stream)
        if track and track.height > 0:
            tracks.setdefault(int(stream["id"]), []).append(track)
    # Prefer H.264 within the same SDR tier for Windows playback compatibility.
    def rank(track: Track):
        return track.codec.startswith("avc"), track.bitrate

    advertised = {
        int(item["quality"]): (item.get("new_description") or item.get("display_desc"))
        for item in data.get("support_formats") or [] if "quality" in item
    }
    qualities = tuple(
        Quality(
            code,
            QUALITY_NAMES.get(code) or advertised.get(code) or f"画质 {code}",
            max(tracks[code], key=rank) if code in tracks else None,
        )
        for code in sorted(advertised.keys() | tracks.keys(), reverse=True)
    )
    # AAC can be copied into MP4 and provides a broadly playable default.
    audio = [track for stream in dash.get("audio") or [] if (track := _track(stream))]
    if not audio:
        raise UserError("B 站没有返回完整音轨。请登录后重试，或检查视频是否可播放。")
    return Formats(qualities, max(audio, key=lambda track: track.bitrate))


class Bilibili:
    def __init__(self, cookies: dict[str, str] | None = None):
        self.session = request_session(cookies)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.session.close()

    def account(self) -> Account | None:
        with web_get(self.session, API + "/x/web-interface/nav") as response:
            result = json_response(response)
        if result.get("code") == -101:
            return None
        data = response_data(result)
        if not data.get("isLogin"):
            return None
        vip = data.get("vip") or {}
        return Account(str(data.get("uname") or "B 站账号"), vip.get("status", data.get("vipStatus")) == 1)

    def resolve(self, text: str) -> tuple[Video, Part]:
        video_id, number = normalize_link(text, self.session)
        params = {"aid": video_id[2:]} if video_id.startswith("av") else {"bvid": video_id}
        with web_get(self.session, API + "/x/web-interface/view", params=params) as response:
            data = response_data(json_response(response))
        if (data.get("rights") or {}).get("is_stein_gate"):
            raise UserError("第一版暂不支持互动视频。")
        parts = tuple(
            Part(int(page["page"]), int(page["cid"]), str(page.get("part") or ""), int(page["duration"]))
            for page in data.get("pages") or [] if page.get("from", "vupload") == "vupload"
        )
        if not parts:
            raise UserError("该投稿没有可用的普通视频分 P。")
        part = next((item for item in parts if item.number == number), None)
        if part is None:
            raise UserError(f"这个视频没有第 {number} P，请检查链接。")
        video = Video(
            data["bvid"], data["title"], (data.get("owner") or {}).get("name") or "未知 UP 主",
            (data.get("pic") or "").replace("http://", "https://", 1), parts,
        )
        return video, part

    def formats(self, video: Video, part: Part) -> Formats:
        params = {"bvid": video.bvid, "cid": part.cid, "qn": 127, "fnval": 4048, "fourk": 1}
        with web_get(
            self.session, API + "/x/player/playurl", params=params, headers={"Referer": video.url},
        ) as response:
            data = response_data(json_response(response))
        if self.session.cookies.get("SESSDATA", domain=".bilibili.com"):
            with web_get(self.session, API + "/x/web-interface/nav") as response:
                keys = (json_response(response).get("data") or {}).get("wbi_img") or {}
            raw_key = "".join(urlsplit(keys.get(name, "")).path.rsplit("/", 1)[-1].split(".")[0]
                              for name in ("img_url", "sub_url"))
            if len(raw_key) == len(WBI_ORDER):
                params["wts"] = int(time.time())
                query = urlencode(sorted(params.items()))
                key = "".join(raw_key[index] for index in WBI_ORDER)[:32]
                params["w_rid"] = md5((query + key).encode()).hexdigest()
                try:
                    with web_get(self.session, API + "/x/player/wbi/playurl", params=params,
                                 headers={"Referer": video.url}) as response:
                        signed = response_data(json_response(response))
                    if signed.get("dash", {}).get("video"):
                        data = signed
                except UserError:
                    # The legacy Web endpoint already returned a valid response.
                    pass
        formats = parse_formats(data, part.seconds)
        if self.session.cookies.get("SESSDATA", domain=".bilibili.com"):
            return formats
        if not any(item.track is None and item.code in (64, 80) for item in formats.qualities):
            return formats
        playback = guest_playback(video, part)
        if playback is None:
            return formats
        try:
            public = {item.code: item.track for item in parse_formats(playback, part.seconds).qualities
                      if item.track and item.code in (16, 32, 64, 80)}
        except UserError:
            return formats
        return Formats(
            tuple(replace(item, track=public[item.code]) if item.track is None and item.code in public else item
                  for item in formats.qualities),
            formats.audio,
        )

    def cover(self, video: Video) -> bytes:
        url = video.cover_url
        if not re.fullmatch(r"i[0-9]+\.hdslb\.com", urlsplit(url).hostname or ""):
            return b""
        try:
            with web_get(self.session, url, stream=True) as response:
                if response.status_code == 200:
                    return response.raw.read(2 * 1024 * 1024 + 1, decode_content=True)[:2 * 1024 * 1024]
        except (UserError, OSError, requests.RequestException):
            pass
        return b""
