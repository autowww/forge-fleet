"""Fleet Docker job specs — container class hierarchy for argv builders."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _probe_script_host_path() -> Path:
    """Resolve probe script on the Fleet host (optional ``FLEET_LENSES_REPO_ROOT`` override, else bundled copy)."""
    env = str(os.environ.get("FLEET_LENSES_REPO_ROOT") or "").strip()
    if env:
        p = Path(env).resolve() / "lenses" / "sandbox" / "host_cpu_probe.py"
        if p.is_file():
            return p
    here = Path(__file__).resolve().parent
    return here / "host_cpu_probe.py"


@dataclass
class FleetContainerSpec(ABC):
    """Base type so Forge Fleet can classify ``docker_argv`` jobs (``meta.container_class``)."""

    container_class: str = "abstract"
    labels: dict[str, str] = field(default_factory=dict)

    @abstractmethod
    def build_argv(self) -> list[str]:
        raise NotImplementedError

    def meta(self) -> dict[str, Any]:
        return {"container_class": self.container_class, **self.labels}


@dataclass
class EmptyFleetContainer(FleetContainerSpec):
    """Minimal no-op container (hierarchy anchor / unit tests).

    Not queued via ``POST /v1/jobs`` (blocked) and not exposed in Fleet admin.
    """

    image: str = field(default_factory=lambda: str(os.environ.get("FLEET_EMPTY_CONTAINER_IMAGE") or "alpine:3.20"))

    def __post_init__(self) -> None:
        self.container_class = "empty"

    def build_argv(self) -> list[str]:
        return ["docker", "run", "--rm", self.image, "true"]


@dataclass
class HostCpuProbeFleetContainer(FleetContainerSpec):
    """Short-lived container that samples **host** CPU via mounted ``/proc``."""

    slot: int = 0
    image: str = field(default_factory=lambda: str(os.environ.get("FLEET_TEST_CONTAINER_IMAGE") or "python:3.12-slim"))

    def __post_init__(self) -> None:
        self.container_class = "host_cpu_probe"
        self.labels = {"fleet_slot": str(int(self.slot))}

    def build_argv(self) -> list[str]:
        script = _probe_script_host_path()
        if not script.is_file():
            raise FileNotFoundError(f"host_cpu_probe.py missing (expected {script})")
        return [
            "docker",
            "run",
            "--rm",
            "-v",
            "/proc:/host/proc:ro",
            "-v",
            f"{script.resolve()}:/probe/host_cpu_probe.py:ro",
            "-e",
            "HOST_PROC_ROOT=/host/proc",
            "-e",
            f"FLEET_SLOT={int(self.slot)}",
            self.image,
            "python",
            "/probe/host_cpu_probe.py",
        ]
