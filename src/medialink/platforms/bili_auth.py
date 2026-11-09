"""Web QR login. The login ticket and refresh token never reach disk or the UI."""

from collections.abc import Callable
from threading import Event
from time import monotonic
from urllib.parse import parse_qs, urljoin, urlsplit

import requests

from ..links import trusted_link
from ..models import Account, UserError, check_cancelled
from .bilibili import (
    Bilibili, PASSPORT, WEB_COOKIES, json_response, request_session, response_data,
    web_get,
)

PASSPORT_QR = PASSPORT + "/x/passport-login/web/qrcode/"
TICKET_HOSTS = {"passport.biligame.com", "passport.bilibili.com"}
STATES = {
    86101: "请用手机哔哩哔哩 App 扫码",
    86090: "已扫码，请在手机上确认",
}


def _login_cookies(session: requests.Session, response: requests.Response, data: dict) -> dict[str, str]:
    url = data.get("url") or ""
    cookies = {cookie.name: cookie.value for cookie in response.cookies if cookie.name in WEB_COOKIES}
    if trusted_link(url, TICKET_HOSTS):
        query = parse_qs(urlsplit(url).query)
        for name in WEB_COOKIES:
            if name in query:
                cookies.setdefault(name, query[name][0])
        for _ in range(3):
            if cookies.get("SESSDATA") or urlsplit(url).path != "/x/passport-login/web/crossDomain":
                break
            with web_get(session, url, stream=True) as ticket:
                cookies.update({c.name: c.value for c in ticket.cookies if c.name in WEB_COOKIES})
                url = urljoin(url, ticket.headers.get("Location", ""))
                if not ticket.is_redirect or not trusted_link(url, TICKET_HOSTS):
                    break
    if not cookies.get("SESSDATA"):
        raise UserError("扫码已确认，但 B 站没有返回可用会话。请刷新二维码重试。")
    return cookies


def login(
    cancel: Event, show_code: Callable[[str], None], show_status: Callable[[str], None],
) -> tuple[Account, dict[str, str]]:
    with request_session() as session:
        with web_get(session, PASSPORT_QR + "generate") as response:
            qr = response_data(json_response(response))
        if not qr.get("qrcode_key") or not trusted_link(
            qr.get("url", ""), {"passport.bilibili.com", "account.bilibili.com", "www.bilibili.com"},
        ):
            raise UserError("B 站没有返回有效二维码，请刷新重试。")
        check_cancelled(cancel)
        show_code(qr["url"])
        deadline = monotonic() + 180
        last_status = None
        while monotonic() < deadline and not cancel.wait(1.6):
            with web_get(session, PASSPORT_QR + "poll", params={"qrcode_key": qr["qrcode_key"]}) as response:
                data = response_data(json_response(response))
                status = data.get("code")
                check_cancelled(cancel)
                if status == 0:
                    cookies = _login_cookies(session, response, data)
                    with Bilibili(cookies) as client:
                        account = client.account()
                    if account is None:
                        raise UserError("B 站未能验证这次登录，请重新扫码。")
                    check_cancelled(cancel)
                    return account, cookies
            if status not in STATES:
                if status == 86038:
                    break
                raise UserError("二维码无法继续使用，请刷新后重试。")
            if status != last_status:
                show_status(STATES[status])
                last_status = status
        check_cancelled(cancel)
    raise UserError("二维码已过期，请刷新后重试。")
