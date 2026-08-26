#!/usr/bin/env python3
"""Copy all inventoried SQLite databases into Postgres (FMH04 / H01–H02).

Market tables include ``ingest_runs``, ``http_audit``, ``broker_positions``, and the
full order from ``inventory_sqlite_databases.migration_table_order``.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from forge_market.db.postgres import PostgresStoreAdapter  # noqa: E402
from forge_market.ingest import store  # noqa: E402
import inventory_sqlite_databases as inventory  # noqa: E402

MIGRATION_TABLES: list[tuple[str, tuple[str, ...]]] = [
    (table, pk)
    for table, pk, _kind in inventory.migration_table_order({"databases": []})
]

_CONNECT_RETRY_ATTEMPTS = 6
_CONNECT_RETRY_DELAY_SEC = 3.0

# Applied after ensure_schema() so older Postgres deployments pick up SQLite columns.
_POSTGRES_COLUMN_PATCHES: tuple[str, ...] = (
    "ALTER TABLE stock_bars ADD COLUMN IF NOT EXISTS buy_volume DOUBLE PRECISION",
    "ALTER TABLE stock_bars ADD COLUMN IF NOT EXISTS sell_volume DOUBLE PRECISION",
    "ALTER TABLE stock_bars ADD COLUMN IF NOT EXISTS volume_delta DOUBLE PRECISION",
    "ALTER TABLE stock_bars ADD COLUMN IF NOT EXISTS volume_split_method TEXT",
)


def _apply_postgres_column_patches(pg_conn: Any) -> None:
    with pg_conn.cursor() as cur:
        for stmt in _POSTGRES_COLUMN_PATCHES:
            cur.execute(stmt)


def _connect_postgres(adapter: PostgresStoreAdapter) -> Any:
    """Open Postgres with brief retries when the server is at max_connections."""
    last_exc: Exception | None = None
    for attempt in range(_CONNECT_RETRY_ATTEMPTS):
        try:
            return adapter.connect()
        except Exception as exc:
            last_exc = exc
            msg = str(exc).lower()
            if "too many clients" not in msg and "remaining connection slots" not in msg:
                raise
            if attempt + 1 >= _CONNECT_RETRY_ATTEMPTS:
                break
            delay = _CONNECT_RETRY_DELAY_SEC * (attempt + 1)
            print(
                f"migrate progress — postgres busy, retry {attempt + 2}/{_CONNECT_RETRY_ATTEMPTS} in {delay:.0f}s",
                flush=True,
            )
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


def _open_sqlite(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [str(row[1]) for row in rows]


def _upsert_rows(
    pg_conn: Any,
    *,
    table: str,
    columns: list[str],
    pk_cols: tuple[str, ...],
    rows: list[sqlite3.Row],
    extra: dict[str, Any] | None = None,
) -> int:
    if not rows and not extra:
        return 0
    if not rows:
        return 0
    quoted_cols = ", ".join(columns)
    placeholders = ", ".join(f"%({col})s" for col in columns)
    conflict_cols = ", ".join(pk_cols)
    update_cols = [col for col in columns if col not in pk_cols]
    if update_cols:
        update_clause = ", ".join(f"{col} = EXCLUDED.{col}" for col in update_cols)
        sql = (
            f"INSERT INTO {table} ({quoted_cols}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict_cols}) DO UPDATE SET {update_clause}"
        )
    else:
        sql = (
            f"INSERT INTO {table} ({quoted_cols}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict_cols}) DO NOTHING"
        )
    payload = []
    for row in rows:
        item = dict(row)
        if extra:
            item.update(extra)
        payload.append(item)
    with pg_conn.cursor() as cur:
        cur.executemany(sql, payload)
    return len(payload)


def _row_mapping(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    if hasattr(row, "keys"):
        return {str(k): row[k] for k in row.keys()}
    return {}


def _ident(name: str) -> str:
    token = str(name or "")
    if not token.replace("_", "").isalnum():
        raise ValueError(f"unsafe SQL identifier: {name!r}")
    return token


def _reset_owned_sequences(pg_conn: Any) -> int:
    """Advance every table-owned SERIAL/identity sequence to MAX(column).

    SQLite copies insert explicit primary keys, so Postgres sequences stay at
    their default and the next INSERT collides. Discover sequences from the
    catalog so this does not hard-code table or column names.
    """
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.relname AS table_name,
                   a.attname AS column_name,
                   pg_get_serial_sequence(c.relname, a.attname) AS seq
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a
              ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
            WHERE c.relkind = 'r'
              AND n.nspname = 'public'
              AND pg_get_serial_sequence(c.relname, a.attname) IS NOT NULL
            """
        )
        rows = cur.fetchall()
    reset = 0
    for row in rows:
        mapping = _row_mapping(row)
        if mapping:
            table = mapping.get("table_name")
            col = mapping.get("column_name")
            seq = mapping.get("seq")
        else:
            table, col, seq = row[0], row[1], row[2]
        if not seq:
            continue
        table_sql = _ident(str(table))
        col_sql = _ident(str(col))
        with pg_conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT setval(
                    %s,
                    COALESCE((SELECT MAX({col_sql}) FROM {table_sql}), 1),
                    (SELECT MAX({col_sql}) FROM {table_sql}) IS NOT NULL
                )
                """,
                (str(seq),),
            )
        reset += 1
    return reset


def migrate_db_file(
    sqlite_path: Path,
    pg_conn: Any,
    *,
    kind: str,
    workspace_id: str | None = None,
    only_tables: set[str] | None = None,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    sqlite_conn = _open_sqlite(sqlite_path)
    try:
        for table, pk_cols, table_kind in inventory.migration_table_order({"databases": []}):
            if table_kind != kind:
                continue
            if only_tables is not None and table not in only_tables:
                continue
            columns = _table_columns(sqlite_conn, table)
            if not columns:
                counts[table] = 0
                continue
            if kind == "wiki" and workspace_id and "workspace_id" not in columns:
                columns = ["workspace_id", *columns]
            rows = sqlite_conn.execute(f"SELECT * FROM {table}").fetchall()
            extra = {"workspace_id": workspace_id} if kind == "wiki" and workspace_id else None
            counts[table] = _upsert_rows(
                pg_conn,
                table=table,
                columns=columns,
                pk_cols=pk_cols if "workspace_id" not in pk_cols else pk_cols,
                rows=rows,
                extra=extra,
            )
            if counts[table] > 0:
                print(f"migrate progress — {table}: {counts[table]:,} rows", flush=True)
    finally:
        sqlite_conn.close()
    return counts


def migrate(sqlite_path: Path, *, dsn: str | None = None) -> dict[str, int]:
    adapter = PostgresStoreAdapter(dsn)
    if not adapter.is_configured():
        raise SystemExit("FORGE_MARKET_DATABASE_URL is required for migration")
    pg_conn = _connect_postgres(adapter)
    counts: dict[str, int] = {}
    try:
        adapter.ensure_schema(pg_conn)
        _apply_postgres_column_patches(pg_conn)
        counts.update(migrate_db_file(sqlite_path, pg_conn, kind="market"))
        counts["_sequences_reset"] = _reset_owned_sequences(pg_conn)
        pg_conn.commit()
    finally:
        pg_conn.close()
    return counts


def migrate_all(
    *,
    repo_root: Path | None = None,
    dsn: str | None = None,
    only_tables: set[str] | None = None,
) -> dict[str, int]:
    adapter = PostgresStoreAdapter(dsn)
    if not adapter.is_configured():
        raise SystemExit("FORGE_MARKET_DATABASE_URL is required for migration")
    manifest = inventory.discover(repo_root=repo_root)
    pg_conn = _connect_postgres(adapter)
    totals: dict[str, int] = {}
    try:
        adapter.ensure_schema(pg_conn)
        _apply_postgres_column_patches(pg_conn)
        for db in manifest.get("databases") or []:
            path = Path(str(db["path"]))
            kind = str(db.get("kind") or "market")
            ws = db.get("workspace_id")
            part = migrate_db_file(
                path,
                pg_conn,
                kind=kind,
                workspace_id=ws,
                only_tables=only_tables,
            )
            for k, v in part.items():
                totals[k] = totals.get(k, 0) + v
        totals["_sequences_reset"] = _reset_owned_sequences(pg_conn)
        pg_conn.commit()
    finally:
        pg_conn.close()
    return totals


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", type=Path, help="Single SQLite market.db path")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Migrate all inventoried databases under repo data/",
    )
    parser.add_argument(
        "--dsn",
        default=os.environ.get("FORGE_MARKET_DATABASE_URL", "").strip(),
        help="Postgres DSN (default: FORGE_MARKET_DATABASE_URL)",
    )
    parser.add_argument(
        "--tables",
        default="",
        help="Comma-separated SQLite table names to upsert (default: all inventoried tables)",
    )
    args = parser.parse_args()
    only_tables = {part.strip() for part in str(args.tables or "").split(",") if part.strip()} or None
    if args.all:
        counts = migrate_all(dsn=args.dsn or None, only_tables=only_tables)
    else:
        sqlite_path = args.sqlite or (REPO_ROOT / "data" / "market.db")
        if not sqlite_path.is_file():
            store.init_db(sqlite_path)
        counts = migrate(sqlite_path, dsn=args.dsn or None)
    print("migrate_sqlite_to_postgres row counts:")
    for table, count in sorted(counts.items()):
        print(f"  {table}: {count}")


if __name__ == "__main__":
    main()
