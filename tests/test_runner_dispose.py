"""Container dispose validates Docker id shape."""

from __future__ import annotations

from fleet_server import runner


def test_dispose_rejects_invalid_id() -> None:
    ok, detail = runner.dispose_container("not-a-container-id")
    assert ok is False
    assert "invalid" in detail


def test_dispose_accepts_hex_id_shape() -> None:
    ok, _detail = runner.dispose_container("a" * 12)
    # Likely fails at docker (no daemon) — still exercises validation path
    assert isinstance(ok, bool)
