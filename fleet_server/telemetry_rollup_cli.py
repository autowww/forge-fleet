"""CLI: backfill telemetry 5m rollups into fleet.sqlite."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from fleet_server import store, telemetry_rollup


def main() -> None:
    p = argparse.ArgumentParser(
        description="Backfill Forge Fleet telemetry 5-minute rollups (telemetry_buckets_5m)."
    )
    p.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.environ.get("FLEET_DATA_DIR") or ".fleet-data").expanduser(),
        help="Fleet state directory (contains fleet.sqlite).",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Buckets per backfill batch (default 500).",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    data_dir: Path = args.data_dir.resolve()
    db_path = data_dir / "fleet.sqlite"
    if not db_path.is_file():
        print(f"fleet-telemetry-rollup: no database at {db_path}", file=sys.stderr)
        sys.exit(1)
    conn = store.connect(db_path)
    try:
        total = telemetry_rollup.run_full_backfill(conn, batch_size=max(1, int(args.batch_size)))
        state = telemetry_rollup.rollup_state_public(conn)
    finally:
        conn.close()
    if args.verbose:
        print(
            "fleet-telemetry-rollup:",
            f"wrote {total} bucket(s);",
            f"stored={state.get('bucket_count')};",
            f"gaps_remain={state.get('gaps_remain')}",
            file=sys.stderr,
        )
    if state.get("gaps_remain"):
        sys.exit(2)


if __name__ == "__main__":
    main()
