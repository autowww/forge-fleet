"""host_stats CPU line parsing (stdlib)."""

from __future__ import annotations

from fleet_server.host_stats import _per_cpu_jiffies_line


def test_per_cpu_jiffies_skips_aggregate() -> None:
    assert _per_cpu_jiffies_line("cpu  1 2 3 4 5 6 7 8 9 10") is None


def test_per_cpu_jiffies_parses_cpu0() -> None:
    line = "cpu0 248 0 248 123 4 0 0 0 0 0"
    r = _per_cpu_jiffies_line(line)
    assert r is not None
    tag, idle, total = r
    assert tag == "cpu0"
    assert idle == 123 + 4
    assert total == sum([248, 0, 248, 123, 4, 0, 0])
