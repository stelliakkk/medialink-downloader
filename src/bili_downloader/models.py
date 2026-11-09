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


@dataclass(frozen=True, slots=True)
class Part:
    number: int
    cid: int
    name: str
    seconds: int


@dataclass(frozen=True, slots=True)
class Video:
    bvid: str
    title: str
    author: str
    cover_url: str
    parts: tuple[Part, ...]

    @property
    def url(self) -> str:
        return f"https://www.bilibili.com/video/{self.bvid}/"


@dataclass(frozen=True, slots=True)
class Track:
    urls: tuple[str, ...] = field(repr=False)
    codec: str
    bitrate: int
    width: int = 0
    height: int = 0
    fps: str = ""


@dataclass(frozen=True, slots=True)
class Quality:
    code: int
    label: str
    track: Track | None


@dataclass(frozen=True, slots=True)
class Formats:
    qualities: tuple[Quality, ...]
    audio: Track

    def select(self, code: int | None) -> Quality:
        for quality in self.qualities:
            if quality.track and (code is None or quality.code == code):
                return quality
        raise UserError("这个画质当前不可用，请重新解析并选择。")


@dataclass(frozen=True, slots=True)
class Account:
    name: str
    vip: bool
