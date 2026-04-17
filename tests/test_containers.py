"""Fleet container argv builders."""

from __future__ import annotations

from fleet_server.containers import EmptyFleetContainer, HostCpuProbeFleetContainer


def test_empty_container_argv() -> None:
    argv = EmptyFleetContainer(image="alpine:3.20").build_argv()
    assert argv[:3] == ["docker", "run", "--rm"]
    assert argv[-2:] == ["alpine:3.20", "true"]


def test_host_cpu_probe_meta_and_argv_shape() -> None:
    spec = HostCpuProbeFleetContainer(slot=2)
    meta = spec.meta()
    assert meta["container_class"] == "host_cpu_probe"
    assert meta["fleet_slot"] == "2"
    argv = spec.build_argv()
    assert argv[0] == "docker"
    assert "/proc:/host/proc:ro" in argv
    assert "HOST_PROC_ROOT=/host/proc" in argv
    assert "FLEET_SLOT=2" in argv
    assert argv[-2:] == ["python", "/probe/host_cpu_probe.py"]
