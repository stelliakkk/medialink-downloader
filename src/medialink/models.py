from dataclasses import dataclass, field
from enum import Enum
from threading import Event


class UserError(Exception):
    """An error that is safe to show without exposing request details."""


class Cancelled(Exception):
    pass


def check_cancelled(cancel: Event) -> None:
    if cancel.is_set():
        raise Cancelled()


class Output(Enum):
    VIDEO = "MP4"
    AUDIO = "MP3"
    BOTH = "MP4 + MP3"


class Source(Enum):
    BILIBILI = "bilibili"
    DOUYIN = "douyin"

    @property
    def label(self) -> str:
        return "B 站" if self is Source.BILIBILI else "抖音"

    def url(self, video_id: str, page: int | None = None) -> str:
        if self is Source.DOUYIN:
            return f"https://www.douyin.com/video/{video_id}"
        return f"https://www.bilibili.com/video/{video_id}/" + (f"?p={page}" if page is not None else "")


@dataclass(frozen=True, slots=True)
class Part:
    number: int
    cid: int
    name: str
    seconds: int


@dataclass(frozen=True, slots=True)
class Video:
    video_id: str
    title: str
    author: str
    cover_url: str
    parts: tuple[Part, ...]
    source: Source = Source.BILIBILI

    @property
    def url(self) -> str:
        return self.source.url(self.video_id)


@dataclass(frozen=True, slots=True)
class Track:
    urls: tuple[str, ...] = field(repr=False)
    codec: str
    bitrate: int
    width: int = 0
    height: int = 0
    fps: str = ""
    combined: bool | None = False


@dataclass(frozen=True, slots=True)
class Quality:
    code: int
    label: str
    track: Track | None


@dataclass(frozen=True, slots=True)
class Formats:
    qualities: tuple[Quality, ...]
    audio: Track | None

    def select(self, code: int | None) -> Quality:
        for quality in self.qualities:
            if quality.track and (code is None or quality.code == code):
                return quality
        raise UserError("这个画质当前不可用，请重新解析并选择。")


@dataclass(frozen=True, slots=True)
class Account:
    name: str
    vip: bool
