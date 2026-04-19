"""Record host telemetry to SQLite without running the Fleet HTTP server.

Used by systemd ``forge-fleet-telemetry.service`` (timer) alongside or instead of
``/v1/health`` / ``/v1/admin/snapshot`` sampling. Throttling is enforced in
``store.maybe_record_telemetry_sample`` (``FLEET_TELEMETRY_INTERVAL_S``).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from fleet_server import host_stats, store


def _interval_s() -> float:
    try:
        v = float(os.environ.get("FLEET_TELEMETRY_INTERVAL_S") or "60")
    except ValueError:
        return 60.0
    return max(5.0, v)


def sample_once(db_path: Path, *, verbose: bool = False) -> bool:
    snap = host_stats.snapshot()
    conn = store.connect(db_path)
    try:
        written = store.maybe_record_telemetry_sample(conn, db_path, snap)
    finally:
        conn.close()
    if verbose:
        print(
            "fleet-telemetry-sample:",
            "written" if written else "skipped (interval)",
            "cpu_usage_pct=",
            snap.get("cpu_usage_pct"),
            file=sys.stderr,
        )
    return written


def main() -> None:
    p = argparse.ArgumentParser(
        description="Record one Forge Fleet telemetry sample into fleet.sqlite (telemetry_samples)."
    )
    p.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.environ.get("FLEET_DATA_DIR") or ".fleet-data").expanduser(),
        help="Fleet state directory (contains fleet.sqlite). Same as fleet-server --data-dir.",
    )
    p.add_argument(
        "--daemon",
        action="store_true",
        help="Loop forever, sleeping FLEET_TELEMETRY_INTERVAL_S after each attempt.",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Log each attempt to stderr.")
    args = p.parse_args()
    data_dir: Path = args.data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "fleet.sqlite"
    interval = _interval_s()
    while True:
        try:
            sample_once(db_path, verbose=args.verbose)
        except KeyboardInterrupt:
            raise
        except Exception as ex:
            print("fleet-telemetry-sample:", ex, file=sys.stderr)
            if not args.daemon:
                sys.exit(1)
            time.sleep(interval)
            continue
        if not args.daemon:
            break
        time.sleep(interval)


if __name__ == "__main__":
    main()
