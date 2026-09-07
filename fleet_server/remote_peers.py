"""Remote Fleet peer registry and HTTP proxy (stdlib only)."""

from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

_PEER_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_PROXY_TIMEOUT_S = 30.0


def peers_file(data_dir: Path) -> Path:
    return data_dir / "etc" / "remote-peers.json"


def _normalize_base(url: str) -> str:
    u = (url or "").strip().rstrip("/")
    if u.endswith("/v1"):
        u = u[:-3]
    return u


def _load_doc(data_dir: Path) -> dict[str, Any]:
    path = peers_file(data_dir)
    if not path.is_file():
        return {"peers": []}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"peers": []}
    if not isinstance(doc, dict):
        return {"peers": []}
    peers = doc.get("peers")
    if not isinstance(peers, list):
        peers = []
    return {"peers": [p for p in peers if isinstance(p, dict)]}


def _save_doc(data_dir: Path, doc: dict[str, Any]) -> None:
    path = peers_file(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _public_row(peer: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(peer.get("id") or ""),
        "label": str(peer.get("label") or peer.get("id") or ""),
        "base_url": str(peer.get("base_url") or ""),
        "bearer_configured": bool(str(peer.get("bearer_token") or "").strip()),
        "updated_at": peer.get("updated_at"),
    }


def list_peers(data_dir: Path) -> dict[str, Any]:
    doc = _load_doc(data_dir)
    return {"ok": True, "peers": [_public_row(p) for p in doc.get("peers", [])]}


def get_peer(data_dir: Path, peer_id: str) -> dict[str, Any] | None:
    for p in _load_doc(data_dir).get("peers", []):
        if str(p.get("id") or "") == peer_id:
            return p
    return None


def upsert_peer(
    data_dir: Path,
    peer_id: str,
    *,
    label: str,
    base_url: str,
    bearer_token: str,
) -> dict[str, Any]:
    pid = (peer_id or "").strip().lower()
    if not _PEER_ID_RE.match(pid):
        return {"ok": False, "error": "invalid_peer_id"}
    base = _normalize_base(base_url)
    if not base.startswith("http://") and not base.startswith("https://"):
        return {"ok": False, "error": "invalid_base_url"}
    token = (bearer_token or "").strip()
    if not token:
        return {"ok": False, "error": "bearer_token_required"}

    import time

    doc = _load_doc(data_dir)
    peers: list[dict[str, Any]] = list(doc.get("peers", []))
    row = {
        "id": pid,
        "label": (label or pid).strip() or pid,
        "base_url": base,
        "bearer_token": token,
        "updated_at": time.time(),
    }
    replaced = False
    for i, p in enumerate(peers):
        if str(p.get("id") or "") == pid:
            peers[i] = row
            replaced = True
            break
    if not replaced:
        peers.append(row)
    _save_doc(data_dir, {"peers": peers})
    return {"ok": True, "peer": _public_row(row), "created": not replaced}


def delete_peer(data_dir: Path, peer_id: str) -> dict[str, Any]:
    doc = _load_doc(data_dir)
    peers = [p for p in doc.get("peers", []) if str(p.get("id") or "") != peer_id]
    if len(peers) == len(doc.get("peers", [])):
        return {"ok": False, "error": "not_found"}
    _save_doc(data_dir, {"peers": peers})
    return {"ok": True, "id": peer_id}


def _request_peer(
    peer: dict[str, Any],
    path: str,
    *,
    query: str = "",
) -> tuple[int, bytes, str]:
    base = _normalize_base(str(peer.get("base_url") or ""))
    token = str(peer.get("bearer_token") or "").strip()
    url = f"{base}{path}"
    if query:
        url = f"{url}?{query.lstrip('?')}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="GET",
    )
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=_PROXY_TIMEOUT_S, context=ctx) as resp:
            body = resp.read()
            ctype = str(resp.headers.get("Content-Type") or "application/json")
            return int(resp.status), body, ctype
    except urllib.error.HTTPError as exc:
        body = exc.read() if exc.fp else b""
        ctype = str(exc.headers.get("Content-Type") or "application/json") if exc.headers else "application/json"
        return int(exc.code), body, ctype
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        err = json.dumps({"ok": False, "error": "upstream_unreachable", "detail": str(exc)[:500]}).encode("utf-8")
        return 502, err, "application/json"


def probe_peer(data_dir: Path, peer_id: str) -> dict[str, Any]:
    peer = get_peer(data_dir, peer_id)
    if peer is None:
        return {"ok": False, "error": "not_found"}
    code, body, _ctype = _request_peer(peer, "/v1/health")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {"raw": body.decode("utf-8", errors="replace")[:500]}
    ok = 200 <= code < 300 and isinstance(payload, dict) and payload.get("ok") is True
    return {
        "ok": ok,
        "http_status": code,
        "health": payload if isinstance(payload, dict) else None,
        "peer_id": peer_id,
    }


def proxy_get(
    data_dir: Path,
    peer_id: str,
    upstream_path: str,
    *,
    query: str = "",
) -> tuple[int, bytes, str]:
    peer = get_peer(data_dir, peer_id)
    if peer is None:
        body = json.dumps({"ok": False, "error": "not_found"}).encode("utf-8")
        return 404, body, "application/json"
    return _request_peer(peer, upstream_path, query=query)
