"""HTTP/1.1 keep-alive pool (stdlib). Keep aligned with forge-market/src/forge_market/http_pool.py."""

from __future__ import annotations

import http.client
import ssl
import threading
from urllib.parse import urlparse

_MAX_IDLE = 8
_STALE_ERRORS = (
    BrokenPipeError,
    ConnectionAbortedError,
    ConnectionResetError,
    http.client.BadStatusLine,
    http.client.CannotSendRequest,
    http.client.RemoteDisconnected,
)

_lock = threading.Lock()
_idle: dict[tuple[str, str, int], list[http.client.HTTPConnection]] = {}
_ssl_ctx: ssl.SSLContext | None = None


def reset_http_pool() -> None:
    with _lock:
        for conns in _idle.values():
            for conn in conns:
                _close_quiet(conn)
        _idle.clear()


def header_get(headers: dict[str, str], name: str, default: str = "") -> str:
    want = name.lower()
    for key, value in headers.items():
        if key.lower() == want:
            return value
    return default


def pooled_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: float = 30.0,
) -> tuple[int, dict[str, str], bytes]:
    last: BaseException | None = None
    conn: http.client.HTTPConnection | None = None
    for attempt in range(2):
        conn = None
        try:
            conn = _checkout(_origin(url), timeout)
            return _perform(conn, method, url, headers or {}, body, timeout)
        except TimeoutError:
            if conn is not None:
                _close_quiet(conn)
            raise
        except _STALE_ERRORS as exc:
            last = exc
            if conn is not None:
                _close_quiet(conn)
            if attempt == 0:
                continue
            raise
        except Exception:
            if conn is not None:
                _close_quiet(conn)
            raise
    assert last is not None
    raise last


def _ssl_context() -> ssl.SSLContext:
    global _ssl_ctx
    if _ssl_ctx is None:
        _ssl_ctx = ssl.create_default_context()
    return _ssl_ctx


def _origin(url: str) -> tuple[str, str, int]:
    parsed = urlparse(url)
    scheme = (parsed.scheme or "http").lower()
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError(f"url has no host: {url}")
    if parsed.port:
        port = int(parsed.port)
    elif scheme == "https":
        port = 443
    else:
        port = 80
    return scheme, host, port


def _target_path(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    if parsed.query:
        return f"{path}?{parsed.query}"
    return path


def _close_quiet(conn: http.client.HTTPConnection) -> None:
    try:
        conn.close()
    except Exception:
        return


def _checkout(origin: tuple[str, str, int], timeout: float) -> http.client.HTTPConnection:
    with _lock:
        idle = _idle.setdefault(origin, [])
        while idle:
            conn = idle.pop()
            if conn.sock is None:
                _close_quiet(conn)
                continue
            conn.timeout = timeout
            try:
                conn.sock.settimeout(timeout)
            except OSError:
                _close_quiet(conn)
                continue
            return conn
    scheme, host, port = origin
    if scheme == "https":
        return http.client.HTTPSConnection(host, port=port, timeout=timeout, context=_ssl_context())
    if scheme != "http":
        raise ValueError(f"unsupported URL scheme: {scheme}")
    return http.client.HTTPConnection(host, port=port, timeout=timeout)


def _checkin(origin: tuple[str, str, int], conn: http.client.HTTPConnection) -> None:
    if conn.sock is None:
        _close_quiet(conn)
        return
    with _lock:
        idle = _idle.setdefault(origin, [])
        if len(idle) >= _MAX_IDLE:
            _close_quiet(conn)
            return
        idle.append(conn)


def _perform(
    conn: http.client.HTTPConnection,
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout: float,
) -> tuple[int, dict[str, str], bytes]:
    origin = _origin(url)
    fwd: dict[str, str] = {}
    for key, value in headers.items():
        low = key.lower()
        if low in {"host", "content-length", "connection", "keep-alive", "transfer-encoding"}:
            continue
        fwd[key] = value
    conn.timeout = timeout
    if conn.sock is not None:
        conn.sock.settimeout(timeout)
    conn.request(str(method or "GET").upper(), _target_path(url), body=body, headers=fwd)
    resp = conn.getresponse()
    payload = resp.read()
    status = int(resp.status)
    out_headers = {str(key): str(value) for key, value in resp.getheaders()}
    will_close = bool(getattr(resp, "will_close", True))
    if will_close:
        _close_quiet(conn)
        return status, out_headers, payload
    _checkin(origin, conn)
    return status, out_headers, payload
