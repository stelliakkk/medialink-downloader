"""Read the target video's playback response from an isolated Edge guest tab."""

import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic
from urllib.parse import parse_qs, urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from websocket import WebSocketException, WebSocketTimeoutException, create_connection

from ..models import Source, UserError, check_cancelled

DETAIL = "/aweme/v1/web/aweme/detail/"


class _StartupError(UserError):
    """The isolated Edge session failed before navigation."""


def _edge_path() -> Path:
    for key in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        if base := os.environ.get(key):
            path = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if path.is_file():
                return path
    raise UserError("解析抖音需要 Microsoft Edge，请安装或修复 Edge 后重试。")


def _blank_page_id(tab: dict) -> str:
    if not isinstance(tab, dict):
        return ""
    target = tab.get("id")
    if (tab.get("type") == "page" and tab.get("url") == "about:blank"
            and isinstance(target, str) and re.fullmatch("[A-Fa-f0-9]{32}", target)):
        return target
    return ""


def _debugger(profile: Path, process, cancel: Event):
    port_file = profile / "DevToolsActivePort"
    local = build_opener(ProxyHandler({}))
    deadline = monotonic() + 12
    page = ""
    endpoint_ready = False
    while monotonic() < deadline and process.poll() is None:
        check_cancelled(cancel)
        try:
            port = int(port_file.read_text(encoding="ascii").splitlines()[0])
            if not 1 <= port <= 65535:
                raise ValueError("Invalid port")
            if not page:
                origin = f"http://127.0.0.1:{port}"
                with local.open(f"{origin}/json/list", timeout=1) as response:
                    tabs = json.load(response)
                if not isinstance(tabs, list):
                    raise ValueError("Invalid target list")
                endpoint_ready = True
                page = next((target for tab in tabs if (target := _blank_page_id(tab))), "")
                if not page:
                    # A fresh Edge profile can open its own page instead of the requested blank one.
                    check_cancelled(cancel)
                    request = Request(f"{origin}/json/new?about:blank", method="PUT")
                    with local.open(request, timeout=1) as response:
                        page = _blank_page_id(json.load(response))
            if page:
                check_cancelled(cancel)
                return create_connection(
                    f"ws://127.0.0.1:{port}/devtools/page/{page}", timeout=0.7,
                    suppress_origin=True, http_no_proxy=["127.0.0.1"],
                )
        except (OSError, ValueError, IndexError, WebSocketException):
            page = ""
        cancel.wait(0.15)
    check_cancelled(cancel)
    if process.poll() is not None:
        raise _StartupError("Edge 在解析抖音前退出。请确认 Microsoft Edge 能正常打开，再试一次。")
    if endpoint_ready:
        raise _StartupError("Edge 已启动，但未能连接抖音解析标签页，请重试。")
    raise _StartupError("未能连接 Edge 的本机调试端口。请确认 Microsoft Edge 能正常打开，再试一次。")


def _send(socket, number, method, **params):
    socket.send(json.dumps({"id": number, "method": method, "params": params}))


@contextmanager
def _guest_tab(cancel: Event):
    executable = _edge_path()
    check_cancelled(cancel)
    with TemporaryDirectory(prefix="medialink-edge-", ignore_cleanup_errors=True) as folder:
        profile = Path(folder)
        try:
            process = subprocess.Popen(
                [str(executable), "--headless=new", "--no-first-run", "--no-default-browser-check",
                 "--disable-background-mode", "--mute-audio", "--remote-debugging-port=0",
                 "--remote-debugging-address=127.0.0.1", f"--user-data-dir={profile}", "about:blank"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except OSError:
            raise UserError("无法运行 Microsoft Edge，请检查安装后重试。") from None
        socket = None
        try:
            socket = _debugger(profile, process, cancel)
            yield socket
        finally:
            if socket is not None:
                try:
                    _send(socket, 99999, "Browser.close")
                except (OSError, WebSocketException):
                    pass
                try:
                    socket.close(timeout=0.5)
                except (OSError, WebSocketException):
                    pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                # The browser owns renderer processes. Limit forced cleanup to this new process tree.
                try:
                    subprocess.run(
                        [str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"),
                         "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW, timeout=4,
                    )
                except (OSError, subprocess.TimeoutExpired):
                    pass
                if process.poll() is None:
                    process.kill()
                process.wait()


def _find_note(value, note_id: str) -> dict | None:
    if isinstance(value, dict):
        if value.get("awemeId") == note_id and value.get("images"):
            return value
        children = value.values()
    elif isinstance(value, list):
        children = value
    else:
        return None
    for child in children:
        if match := _find_note(child, note_id):
            return match
    return None


def _note_document(html: str, note_id: str) -> dict | None:
    prefix = "self.__pace_f.push("
    for script in re.finditer(r"<script\b[^>]*>(.*?)</script\s*>", html, re.S | re.I):
        content = script[1].strip().removesuffix(";")
        if not content.startswith(prefix) or not content.endswith(")") or note_id not in content:
            continue
        try:
            chunk = json.loads(content[len(prefix):-1])
        except ValueError:
            continue
        if not isinstance(chunk, list) or len(chunk) != 2 or chunk[0] != 1 or not isinstance(chunk[1], str):
            continue
        for line in chunk[1].splitlines():
            key, _, payload = line.partition(":")
            if not re.fullmatch(r"[0-9a-f]+", key) or note_id not in payload:
                continue
            try:
                item = _find_note(json.loads(payload), note_id)
            except (ValueError, RecursionError):
                continue
            if item:
                return item
    return None


def _read_detail(socket, video_id: str, cancel: Event, *, is_note: bool = False) -> dict:
    target = Source.DOUYIN.url(video_id, is_note=is_note)
    path = urlsplit(target).path
    _send(socket, 1, "Network.enable", maxTotalBufferSize=20_000_000, maxResourceBufferSize=5_000_000)
    _send(socket, 2, "Page.navigate", url=target)
    deadline = monotonic() + 26
    requests, reads = set(), set()
    command = 10
    while monotonic() < deadline:
        check_cancelled(cancel)
        try:
            message = json.loads(socket.recv())
        except WebSocketTimeoutException:
            continue
        event = message.get("method")
        params = message.get("params", {})
        if event == "Network.responseReceived":
            response = params["response"]
            url = urlsplit(response["url"])
            if url.scheme != "https" or url.hostname != "www.douyin.com" or response["status"] != 200:
                continue
            is_document = is_note and params.get("type") == "Document" and url.path.rstrip("/") == path
            is_video_detail = (not is_note and url.path == DETAIL
                               and parse_qs(url.query).get("aweme_id") == [video_id])
            if is_document or is_video_detail:
                requests.add(params["requestId"])
        elif event == "Network.loadingFinished" and params["requestId"] in requests:
            requests.remove(params["requestId"])
            _send(socket, command, "Network.getResponseBody", requestId=params["requestId"])
            reads.add(command)
            command += 1
        elif message.get("id") in reads:
            reads.remove(message["id"])
            result = message.get("result") or {}
            body = result.get("body") or ""
            if result.get("base64Encoded"):
                body = base64.b64decode(body).decode("utf-8")
            if is_note:
                if item := _note_document(body, video_id):
                    return item
                continue
            data = json.loads(body or "{}")
            item = data.get("aweme_detail") or {}
            if str(item.get("aweme_id")) == video_id:
                return item
            if data.get("status_code") not in (0, None):
                break
    if is_note:
        raise UserError("抖音网页未返回这条图文的图片数据。请检查该作品能否在网页中查看。")
    raise UserError("抖音网页未返回这个视频的播放数据。请检查链接及网页能否正常播放。")


def playback_detail(video_id: str, cancel: Event, *, is_note: bool = False) -> dict:
    for attempt in range(2):
        try:
            with _guest_tab(cancel) as socket:
                return _read_detail(socket, video_id, cancel, is_note=is_note)
        except _StartupError:
            check_cancelled(cancel)
            if attempt:
                raise
        except (OSError, ValueError, WebSocketException):
            check_cancelled(cancel)
            raise UserError("抖音网页解析会话中断，请重试。") from None
