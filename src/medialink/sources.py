from threading import Event

from .models import Source
from .platforms.bilibili import Bilibili
from .platforms.douyin import Douyin


def open_source(source: Source, cookies: dict[str, str], cancel: Event) -> Bilibili | Douyin:
    if source is Source.DOUYIN:
        return Douyin(cancel)
    return Bilibili(cookies)
