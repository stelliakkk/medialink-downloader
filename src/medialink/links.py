import re
from urllib.parse import urlsplit

from .models import Source, UserError

BILI_VIDEO_HOSTS = frozenset(("www.bilibili.com", "bilibili.com", "m.bilibili.com"))
BILI_HOSTS = BILI_VIDEO_HOSTS | {"b23.tv"}
DOUYIN_HOSTS = frozenset(("v.douyin.com", "www.douyin.com", "douyin.com", "www.iesdouyin.com", "iesdouyin.com"))
SHARE_LINK = re.compile(
    r"(?<![\w./@-])(?:https?://)?(?:[a-z0-9-]+\.)*(?:bilibili\.com|b23\.tv|douyin\.com|iesdouyin\.com)"
    r"/[^\s<>\"()\[\]【】，、；]+",
    re.I,
)


def trusted_link(url: str, hosts: frozenset[str] | set[str]) -> bool:
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https" and parsed.hostname in hosts
            and parsed.port in (None, 443) and parsed.username is None and parsed.password is None
        )
    except ValueError:
        return False


def share_links(text: str):
    for match in SHARE_LINK.finditer(text):
        link = match[0].rstrip("。，、；！？）)]")
        if not re.match(r"https?://", link, re.I):
            link = "https://" + link
        if link.lower().startswith("http://"):
            link = "https://" + link[7:]
        if trusted_link(link, BILI_HOSTS | DOUYIN_HOSTS):
            yield link


def input_link(text: str) -> tuple[Source, str]:
    link = next(share_links(text), None)
    if link is None:
        raise UserError("请粘贴 B 站或抖音的视频链接或分享文本。")
    source = Source.DOUYIN if urlsplit(link).hostname in DOUYIN_HOSTS else Source.BILIBILI
    return source, link
