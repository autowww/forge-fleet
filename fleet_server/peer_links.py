"""Peer link RTT and throughput sampling."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from fleet_server import remote_peers, security_store

_PROBE_SIZE = 1024 * 1024
_started = False


def record_sample(
    conn: sqlite3.Connection,
    peer_id: str,
    *,
    ok: bool,
    rtt_ms: float | None = None,
    throughput_mbps: float | None = None,
    error: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO peer_link_samples (peer_id, ts, ok, rtt_ms, throughput_mbps, error)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (peer_id, time.time(), 1 if ok else 0, rtt_ms, throughput_mbps, error),
    )
    conn.commit()


def probe_peer(data_dir: Path, peer_id: str, bearer: str) -> dict[str, Any]:
    listed = remote_peers.list_peers(data_dir)
    peer = remote_peers.get_peer(data_dir, peer_id)
    if not peer:
        return {"ok": False, "error": "peer_not_found"}
    base = str(peer.get("base_url") or "").rstrip("/")
    tok = bearer or str(peer.get("bearer_token") or "")
    headers = {"Authorization": f"Bearer {tok}"} if tok else {}
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(f"{base}/v1/health", headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
        rtt_ms = (time.perf_counter() - t0) * 1000.0
    except (urllib.error.URLError, OSError, TimeoutError) as ex:
        return {"ok": False, "error": str(ex)[:200]}
    t1 = time.perf_counter()
    try:
        req = urllib.request.Request(f"{base}/v1/host/link-probe", headers=headers)
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        elapsed = max(time.perf_counter() - t1, 1e-6)
        mbps = (len(data) * 8) / (elapsed * 1_000_000)
        return {"ok": True, "rtt_ms": rtt_ms, "throughput_mbps": mbps}
    except (urllib.error.URLError, OSError, TimeoutError) as ex:
        return {"ok": False, "rtt_ms": rtt_ms, "error": str(ex)[:200]}


def mesh_links_payload(db_path: Path, data_dir: Path) -> dict[str, Any]:
    from fleet_server import store

    conn = store.connect(db_path)
    try:
        now = time.time()
        edges = []
        for peer in remote_peers.list_peers(data_dir).get("peers") or []:
            pid = str(peer.get("id") or "")
            rows = conn.execute(
                """
                SELECT ts, ok, rtt_ms, throughput_mbps, error FROM peer_link_samples
                WHERE peer_id = ? AND ts >= ? ORDER BY ts DESC LIMIT 48
                """,
                (pid, now - 86400),
            ).fetchall()
            samples = [
                {
                    "ts": float(r["ts"]),
                    "ok": bool(r["ok"]),
                    "rtt_ms": r["rtt_ms"],
                    "throughput_mbps": r["throughput_mbps"],
                    "error": r["error"],
                }
                for r in rows
            ]
            hour = [s for s in samples if s["ts"] >= now - 3600 and s["ok"]]
            edges.append(
                {
                    "peer_id": pid,
                    "label": peer.get("label") or pid,
                    "samples": samples[:10],
                    "stats_1h": _stats(hour),
                    "stats_24h": _stats([s for s in samples if s["ok"]]),
                }
            )
    finally:
        conn.close()
    return {"ok": True, "observed_at": time.time(), "edges": edges}


def _stats(samples: list[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
        return {}
    rtts = [float(s["rtt_ms"]) for s in samples if s.get("rtt_ms") is not None]
    mbps = [float(s["throughput_mbps"]) for s in samples if s.get("throughput_mbps") is not None]
    out: dict[str, Any] = {}
    if rtts:
        out["rtt_ms_min"] = min(rtts)
        out["rtt_ms_max"] = max(rtts)
        out["rtt_ms_avg"] = sum(rtts) / len(rtts)
    if mbps:
        out["throughput_mbps_min"] = min(mbps)
        out["throughput_mbps_max"] = max(mbps)
        out["throughput_mbps_avg"] = sum(mbps) / len(mbps)
    return out


def start_hourly_probes(db_path: Path, data_dir: Path, bearer: str) -> None:
    global _started
    if _started:
        return
    _started = True

    def _loop() -> None:
        from fleet_server import store

        while True:
            time.sleep(3600)
            conn = store.connect(db_path)
            try:
                for peer in remote_peers.list_peers(data_dir).get("peers") or []:
                    pid = str(peer.get("id") or "")
                    res = probe_peer(data_dir, pid, bearer)
                    record_sample(
                        conn,
                        pid,
                        ok=bool(res.get("ok")),
                        rtt_ms=res.get("rtt_ms"),
                        throughput_mbps=res.get("throughput_mbps"),
                        error=res.get("error"),
                    )
            finally:
                conn.close()

    threading.Thread(target=_loop, name="fleet-peer-link-probes", daemon=True).start()
