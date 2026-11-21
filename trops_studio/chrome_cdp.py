"""Minimalen Chrome DevTools Protocol (stdlib). CDP samo, če debug že teče."""

from __future__ import annotations

import base64
import json
import os
import socket
import ssl
import struct
import time
from typing import Any
from urllib import error as urlerror
from urllib import parse, request as urlrequest

# Minimax debug 9223, eDavki 9222 — ne zaganjamo Chrome.
DEBUG_PORTS = (9223, 9222)


def debug_port_open(host: str, port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _ports_from_chrome_processes() -> list[int]:
    import re
    import subprocess

    ports: list[int] = []
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_Process -Filter \"name='chrome.exe'\").CommandLine",
            ],
            capture_output=True,
            text=True,
            timeout=12,
        )
        for match in re.finditer(r"--remote-debugging-port=(\d+)", result.stdout or "", re.I):
            port = int(match.group(1))
            if port not in ports:
                ports.append(port)
    except Exception:
        return ports
    return ports


def find_debug_endpoint() -> tuple[str, int] | None:
    ports: list[int] = []
    for port in (*DEBUG_PORTS, *_ports_from_chrome_processes()):
        if port not in ports:
            ports.append(port)
    for host in ("127.0.0.1", "localhost"):
        for port in ports:
            if debug_port_open(host, port):
                return host, int(port)
    return None


def _http_json(url: str, *, method: str = "GET", timeout: float = 6.0) -> Any:
    req = urlrequest.Request(url, method=method)
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    if not raw.strip():
        return None
    return json.loads(raw)


def list_pages(host: str, port: int) -> list[dict[str, Any]]:
    try:
        data = _http_json(f"http://{host}:{int(port)}/json/list", timeout=5.0)
    except (urlerror.URLError, OSError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def activate_page(host: str, port: int, target_id: str) -> None:
    tid = str(target_id or "").strip()
    if not tid:
        return
    try:
        _http_json(f"http://{host}:{int(port)}/json/activate/{tid}", timeout=3.0)
    except (urlerror.URLError, OSError, ValueError, json.JSONDecodeError):
        return


def open_new_tab(host: str, port: int, url: str) -> dict[str, Any] | None:
    encoded = parse.quote(url, safe="")
    endpoint = f"http://{host}:{int(port)}/json/new?{encoded}"
    for method in ("PUT", "GET"):
        try:
            data = _http_json(endpoint, method=method, timeout=15.0)
        except (urlerror.URLError, OSError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("webSocketDebuggerUrl"):
            return data
    return None


class CdpSession:
    """Sync WebSocket CDP, brez zunanjih paketov."""

    def __init__(self, ws_url: str, *, timeout: float = 20.0) -> None:
        self._ws_url = ws_url
        self._timeout = timeout
        self._sock: socket.socket | None = None
        self._msg_id = 0

    def __enter__(self) -> CdpSession:
        self.connect()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def connect(self) -> None:
        parsed = parse.urlparse(self._ws_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        sock = socket.create_connection((host, port), timeout=self._timeout)
        if parsed.scheme == "wss":
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        sock.sendall(req.encode("ascii"))
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = sock.recv(4096)
            if not chunk:
                sock.close()
                raise RuntimeError("WebSocket handshake brez odgovora")
            resp += chunk
        if b"101" not in resp.split(b"\r\n", 1)[0]:
            sock.close()
            raise RuntimeError("WebSocket upgrade ni uspel")
        self._sock = sock

    def close(self) -> None:
        if self._sock is None:
            return
        try:
            self._sock.close()
        except OSError:
            pass
        self._sock = None

    def _recv_exact(self, n: int) -> bytes:
        assert self._sock is not None
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise RuntimeError("WebSocket zaprt")
            buf += chunk
        return buf

    def _send_text(self, text: str) -> None:
        assert self._sock is not None
        payload = text.encode("utf-8")
        mask = os.urandom(4)
        length = len(payload)
        header = bytearray([0x81])
        if length < 126:
            header.append(128 | length)
        elif length < 65536:
            header.append(128 | 126)
            header.extend(struct.pack(">H", length))
        else:
            header.append(128 | 127)
            header.extend(struct.pack(">Q", length))
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._sock.sendall(bytes(header) + mask + masked)

    def _recv_text(self) -> str:
        hdr = self._recv_exact(2)
        opcode = hdr[0] & 0x0F
        masked = hdr[1] & 0x80
        length = hdr[1] & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if masked else b""
        data = self._recv_exact(length) if length else b""
        if masked:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        if opcode == 8:
            raise RuntimeError("WebSocket zaprt")
        if opcode == 9:
            return self._recv_text()
        return data.decode("utf-8", errors="replace")

    def call(self, method: str, params: dict[str, Any] | None = None, *, timeout: float = 15.0) -> dict[str, Any]:
        self._msg_id += 1
        mid = self._msg_id
        msg: dict[str, Any] = {"id": mid, "method": method}
        if params:
            msg["params"] = params
        self._send_text(json.dumps(msg))
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = self._recv_text()
            try:
                resp = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if resp.get("id") == mid:
                return resp
        return {}

    def evaluate(self, expression: str, *, timeout: float = 15.0) -> Any:
        self.call("Runtime.enable", timeout=5.0)
        resp = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": False,
            },
            timeout=timeout,
        )
        if resp.get("error"):
            raise RuntimeError(str(resp["error"]))
        result = resp.get("result") or {}
        if result.get("exceptionDetails"):
            raise RuntimeError(str(result.get("exceptionDetails")))
        inner = result.get("result") or {}
        return inner.get("value")

    def navigate(self, url: str) -> None:
        self.call("Page.enable")
        self.call("Page.navigate", {"url": url}, timeout=20.0)
        time.sleep(0.8)

    def press_tab(self) -> None:
        for kind in ("keyDown", "keyUp"):
            self.call(
                "Input.dispatchKeyEvent",
                {
                    "type": kind,
                    "key": "Tab",
                    "code": "Tab",
                    "windowsVirtualKeyCode": 9,
                    "nativeVirtualKeyCode": 9,
                },
            )

    def insert_text(self, text: str) -> None:
        self.call("Input.insertText", {"text": str(text)})

    def select_all(self) -> None:
        for kind in ("keyDown", "keyUp"):
            self.call(
                "Input.dispatchKeyEvent",
                {
                    "type": kind,
                    "key": "a",
                    "code": "KeyA",
                    "windowsVirtualKeyCode": 65,
                    "nativeVirtualKeyCode": 65,
                    "modifiers": 2,
                },
            )
