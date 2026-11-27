"""Ecosystem gate status is a file the runner writes. Enqueue appends a ticker."""

from __future__ import annotations

import json
import os

from fleet_server import ecosystem_gates, route_registry


def test_status_and_enqueue(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ECOSYSTEM_GATE_BASE", str(tmp_path))
    (tmp_path / "status.json").write_text(json.dumps({"gates_passed": 2, "tickers": []}), encoding="utf-8")
    assert ecosystem_gates.status()["gates_passed"] == 2
    queued = ecosystem_gates.enqueue({"ticker": "intc"})
    assert queued["ok"] is True and queued["ticker"] == "INTC"
    line = (tmp_path / "enqueue.jsonl").read_text(encoding="utf-8").strip()
    assert json.loads(line)["ticker"] == "INTC"
    os.environ.pop("ECOSYSTEM_GATE_BASE", None)


def test_routes_are_registered() -> None:
    assert route_registry.match_route("/v1/admin/ecosystem-gates", "GET") is not None
    assert route_registry.match_route("/v1/admin/ecosystem-gates", "POST") is not None
    assert route_registry.match_route("/v1/remote-peers/mercury/admin/ecosystem-gates", "GET") is not None
    assert route_registry.match_route("/v1/remote-peers/mercury/admin/ecosystem-gates", "POST") is not None
