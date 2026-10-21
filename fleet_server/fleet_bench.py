"""Fleet-native benchmark suite (stdlib only)."""

from __future__ import annotations

import hashlib
import multiprocessing
import os
import tempfile
import time
import zlib
from pathlib import Path
from typing import Any

BENCH_VERSION = 1
REF_CPU_SINGLE = 2.5
REF_CPU_MULTI = 8.0
REF_MEM_MBPS = 8000.0
REF_DISK_WRITE_MBPS = 400.0
REF_DISK_READ_MBPS = 600.0

WEIGHTS = {"cpu_multi": 0.4, "cpu_single": 0.2, "memory": 0.2, "disk": 0.2}


def _cpu_mix() -> float:
    t0 = time.perf_counter()
    x = 0
    for i in range(5_000_000):
        x = (x * 1103515245 + 12345 + i) & 0x7FFFFFFF
    t1 = time.perf_counter()
    s = 0.0
    for j in range(200_000):
        s += (j * 0.001) ** 1.1
    t2 = time.perf_counter()
    data = os.urandom(8 * 1024 * 1024)
    hashlib.sha256(data).hexdigest()
    t3 = time.perf_counter()
    zlib.compress(data, 1)
    t4 = time.perf_counter()
    parts = [t1 - t0, t2 - t1, t3 - t2, t4 - t3]
    return sum(parts)


def _cpu_worker() -> float:
    return _cpu_mix()


def run_benchmark(data_dir: Path, *, disk_mb: int = 256, mem_cap_mb: int = 512) -> dict[str, Any]:
    single_t = _cpu_mix()
    cpu_single_mark = int((REF_CPU_SINGLE / max(single_t, 1e-6)) * 1000)

    procs = max(1, os.cpu_count() or 1)
    with multiprocessing.Pool(processes=procs) as pool:
        multi_ts = pool.map(_cpu_worker, [None] * procs)
    multi_t = sum(multi_ts) / len(multi_ts)
    cpu_multi_mark = int((REF_CPU_MULTI / max(multi_t, 1e-6)) * 1000)

    mem_mb = min(mem_cap_mb, 512)
    buf = bytearray(mem_mb * 1024 * 1024)
    times = []
    for _ in range(3):
        t0 = time.perf_counter()
        view = memoryview(buf)
        chunk = len(view) // 2
        view[chunk:] = view[:chunk]
        times.append(time.perf_counter() - t0)
    mem_t = sorted(times)[len(times) // 2]
    mem_mbps = (mem_mb * 2) / max(mem_t, 1e-6)
    memory_mark = int((REF_MEM_MBPS / max(mem_mbps, 1.0)) * 1000)

    disk_path = data_dir / "bench-tmp.dat"
    try:
        t0 = time.perf_counter()
        with disk_path.open("wb") as f:
            chunk = b"x" * (1024 * 1024)
            for _ in range(disk_mb):
                f.write(chunk)
            f.flush()
            os.fsync(f.fileno())
        write_t = time.perf_counter() - t0
        t0 = time.perf_counter()
        with disk_path.open("rb") as f:
            while f.read(1024 * 1024):
                pass
        read_t = time.perf_counter() - t0
        write_mbps = disk_mb / max(write_t, 1e-6)
        read_mbps = disk_mb / max(read_t, 1e-6)
        disk_mark = int(
            (
                (REF_DISK_WRITE_MBPS / max(write_mbps, 1.0)) * 0.5
                + (REF_DISK_READ_MBPS / max(read_mbps, 1.0)) * 0.5
            )
            * 1000
        )
    finally:
        disk_path.unlink(missing_ok=True)

    fleet_mark = int(
        cpu_multi_mark * WEIGHTS["cpu_multi"]
        + cpu_single_mark * WEIGHTS["cpu_single"]
        + memory_mark * WEIGHTS["memory"]
        + disk_mark * WEIGHTS["disk"]
    )
    return {
        "bench_version": BENCH_VERSION,
        "cpu_single_mark": cpu_single_mark,
        "cpu_multi_mark": cpu_multi_mark,
        "memory_mark": memory_mark,
        "disk_mark": disk_mark,
        "fleet_mark": fleet_mark,
        "timings": {
            "cpu_single_s": single_t,
            "cpu_multi_avg_s": multi_t,
            "memory_mbps": mem_mbps,
            "disk_write_mbps": write_mbps,
            "disk_read_mbps": read_mbps,
        },
        "weights": WEIGHTS,
    }
