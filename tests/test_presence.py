"""Presence heartbeats, TTL, gzip aggregate, and the node-by-purpose matrix."""

from __future__ import annotations

import json
from pathlib import Path

from fleet_server import presence, store


def _conn(tmp_path: Path):
    return store.connect(tmp_path / "presence.sqlite")


def test_upsert_ttl_and_matrix(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_NODE_ID", "laptop")
    conn = _conn(tmp_path)
    try:
        item = presence.normalize_item(
            {
                "id": "mlx",
                "k": "integration",
                "p": "experiments",
                "l": "Forge MLX",
                "s": "running",
                "a": "bearer",
                "d": "API bearer; browser uses Google session via gate",
            }
        )
        presence.upsert_local(conn, item, now=1_000.0)
        conn.commit()
        view = presence.matrix(conn, now=1_010.0)
        assert view["nodes"][0]["id"] == "laptop"
        assert view["purposes"] == ["experiments"]
        inst = view["cells"][0]["instances"][0]
        assert inst["kind"] == "integration"
        assert inst["auth_label"] == "bearer"
        assert inst["status"] == "running"
        gone = presence.matrix(conn, now=1_000.0 + 46)
        assert gone["cells"] == []
    finally:
        conn.close()


def test_gzip_aggregate_merge_and_own_node_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_NODE_ID", "granite")
    conn = _conn(tmp_path)
    try:
        payload = presence.encode_aggregate(
            "laptop",
            [
                {
                    "id": "market",
                    "kind": "service",
                    "purpose": "market",
                    "label": "Market Studio",
                    "status": "running",
                    "auth": "loopback",
                }
            ],
        )
        doc = presence.decode_aggregate(payload, gzipped=True)
        assert doc["node_id"] == "laptop"
        raw = json.loads(__import__("gzip").decompress(payload))
        assert "items" in raw
        out = presence.replace_aggregate(conn, doc["node_id"], doc["items"], now=2_000.0)
        conn.commit()
        assert out["stored"] == 1
        view = presence.matrix(conn, now=2_010.0)
        assert view["nodes"][0]["id"] == "granite" or view["cells"][0]["node_id"] == "laptop"
        assert any(c["node_id"] == "laptop" and c["purpose"] == "market" for c in view["cells"])
        try:
            presence.replace_aggregate(conn, "granite", doc["items"])
            raised = False
        except ValueError:
            raised = True
        assert raised
    finally:
        conn.close()


def test_worker_row_removed_when_job_ends(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_NODE_ID", "laptop")
    monkeypatch.delenv("FLEET_BEARER_TOKEN", raising=False)
    conn = _conn(tmp_path)
    try:
        jid = store.insert_job(conn, kind="agentic-dev", argv=["echo"], session_id="t", meta={})
        store.update_job(conn, jid, status="running")
        view = presence.matrix(conn)
        workers = [
            inst
            for cell in view["cells"]
            for inst in cell["instances"]
            if inst["kind"] == "worker"
        ]
        assert workers and workers[0]["id"] == f"job:{jid}"
        assert cell_purpose(view, f"job:{jid}") == "agentic-dev"
        store.update_job(conn, jid, status="succeeded", exit_code=0)
        view = presence.matrix(conn)
        assert all(inst["kind"] != "worker" for cell in view["cells"] for inst in cell["instances"])
    finally:
        conn.close()


def cell_purpose(view: dict, instance_id: str) -> str:
    for cell in view["cells"]:
        for inst in cell["instances"]:
            if inst["id"] == instance_id:
                return cell["purpose"]
    return ""
