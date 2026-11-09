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
from urllib.request import ProxyHandler, build_opener

from websocket import WebSocketException, WebSocketTimeoutException, create_connection

from ..models import UserError, check_cancelled

DETAIL = "/aweme/v1/web/aweme/detail/"


def _edge_path() -> Path:
    for key in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        if base := os.environ.get(key):
            path = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if path.is_file():
                return path
    raise UserError("解析抖音需要 Microsoft Edge，请安装或修复 Edge 后重试。")


def _debugger(profile: Path, process, cancel: Event):
    port_file = profile / "DevToolsActivePort"
    local = build_opener(ProxyHandler({}))
    deadline = monotonic() + 12
    while monotonic() < deadline and process.poll() is None:
        check_cancelled(cancel)
        try:
            port = int(port_file.read_text(encoding="ascii").splitlines()[0])
            if not 1 <= port <= 65535:
                raise ValueError("Invalid port")
            with local.open(f"http://127.0.0.1:{port}/json/list", timeout=1) as response:
                tabs = json.load(response)
            tab = next((tab["id"] for tab in tabs if tab["type"] == "page" and tab["url"] == "about:blank"), "")
            if re.fullmatch("[A-Fa-f0-9]{32}", tab):
                return create_connection(
                    f"ws://127.0.0.1:{port}/devtools/page/{tab}", timeout=0.7,
                    suppress_origin=True, http_no_proxy=["127.0.0.1"],
                )
        except (OSError, ValueError, IndexError, WebSocketException):
            pass
        cancel.wait(0.15)
    check_cancelled(cancel)
    raise UserError("无法启动 Edge 的抖音解析会话，请重试。")


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


def _read_detail(socket, video_id: str, cancel: Event) -> dict:
    _send(socket, 1, "Network.enable", maxTotalBufferSize=20_000_000, maxResourceBufferSize=5_000_000)
    _send(socket, 2, "Page.navigate", url=f"https://www.douyin.com/video/{video_id}")
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
            if (url.scheme == "https" and url.hostname == "www.douyin.com"
                    and url.path == DETAIL and response["status"] == 200
                    and parse_qs(url.query).get("aweme_id") == [video_id]):
                requests.add(params["requestId"])
        elif event == "Network.loadingFinished" and params["requestId"] in requests:
            requests.remove(params["requestId"])
            _send(socket, command, "Network.getResponseBody", requestId=params["requestId"])
            reads.add(command)
            command += 1
        elif message.get("id") in reads:
            reads.remove(message["id"])
            result = message.get("result") or {}
            body = result.get("body") or "{}"
            data = json.loads(base64.b64decode(body) if result.get("base64Encoded") else body)
            item = data.get("aweme_detail") or {}
            if str(item.get("aweme_id")) == video_id:
                return item
            if data.get("status_code") not in (0, None):
                break
    raise UserError("抖音网页未返回这个视频的播放数据。请检查链接及网页能否正常播放。")


def playback_detail(video_id: str, cancel: Event) -> dict:
    try:
        with _guest_tab(cancel) as socket:
            return _read_detail(socket, video_id, cancel)
    except (OSError, ValueError, WebSocketException):
        check_cancelled(cancel)
        raise UserError("抖音网页解析会话中断，请重试。") from None
