"""Thermal LLM advisory policy (tier thresholds and ``build()`` output)."""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from fleet_server import store, thermal_llm_policy
from fleet_server.main import FleetHandler


def test_classify_temp_intel() -> None:
    b = thermal_llm_policy.BAND_INTEL_CPU
    assert thermal_llm_policy.classify_temp_c(89.0, b, cap_critical=False) == "ok"
    assert thermal_llm_policy.classify_temp_c(92.0, b, cap_critical=False) == "warning"
    assert thermal_llm_policy.classify_temp_c(97.0, b, cap_critical=False) == "throttle"
    assert thermal_llm_policy.classify_temp_c(106.0, b, cap_critical=False) == "critical"


def test_classify_cap_critical() -> None:
    b = thermal_llm_policy.BAND_ARM_SOC
    assert thermal_llm_policy.classify_temp_c(106.0, b, cap_critical=True) == "throttle"


def test_build_intel_cpu_and_nvidia() -> None:
    host = {
        "machine": "x86_64",
        "thermal": {"max_c": 92.0, "source": "hwmon:coretemp:temp1_input"},
        "gpu": {
            "nvidia": {
                "available": True,
                "devices": [{"index": 0, "name": "RTX", "temperature_c": 80}],
            },
            "amdgpu_temps": {"available": False, "reason": "none"},
        },
    }
    adv = thermal_llm_policy.build(host)
    assert adv["policy_version"]
    assert adv["cpu_vendor_resolved"] == "intel"
    kinds = {c["kind"] for c in adv["components"]}
    assert "cpu_intel" in kinds
    assert "nvidia_gpu_core" in kinds
    assert adv["worst_tier"] == "warning"
    assert adv["recommended_sleep_s"] >= 15.0
    assert adv["startup_ready"] is True


def test_build_amd_gpu_hotspot_dominates() -> None:
    host = {
        "machine": "x86_64",
        "thermal": {"max_c": 50.0, "source": "hwmon:k10temp:temp1_input"},
        "gpu": {
            "nvidia": {"available": False, "reason": "none"},
            "amdgpu_temps": {
                "available": True,
                "devices": [{"card": "card0", "junction_c": 106.0}],
            },
        },
    }
    adv = thermal_llm_policy.build(host)
    assert adv["cpu_vendor_resolved"] == "amd"
    assert adv["worst_tier"] == "throttle"
    assert adv["recommended_sleep_s"] >= 45.0
    assert adv["startup_ready"] is False


def test_get_admin_snapshot_includes_thermal_llm_advisory(tmp_path: Path) -> None:
    data_dir = tmp_path / "fd"
    data_dir.mkdir()
    db = data_dir / "fleet.sqlite"
    store.connect(db).close()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FleetHandler)
    httpd.db_path = db
    httpd.fleet_data_dir = str(data_dir)
    httpd.listen_host = "127.0.0.1"
    httpd.expected_token = ""
    httpd.loopback_bind_skips_auth = True
    httpd.fleet_started_epoch = time.time()
    port = httpd.server_address[1]
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    try:
        url = f"http://127.0.0.1:{port}/v1/admin/snapshot"
        with urllib.request.urlopen(url, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    finally:
        httpd.shutdown()
        httpd.server_close()
        th.join(timeout=15)

    assert body.get("ok") is True
    host = body.get("host")
    assert isinstance(host, dict)
    adv = host.get("thermal_llm_advisory")
    assert isinstance(adv, dict)
    assert "policy_version" in adv
    assert "worst_tier" in adv
    assert "recommended_sleep_s" in adv
    assert "components" in adv
