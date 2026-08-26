#!/usr/bin/env python3
"""Discover SQLite databases and tables for Postgres migration (A01)."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from forge_market.paths import data_dir  # noqa: E402


def _pragma_pk(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    pks = [str(r[1]) for r in rows if int(r[5] or 0) > 0]
    if pks:
        return pks
    return [str(rows[0][1])] if rows else []


def _inventory_db(path: Path, *, kind: str, workspace_id: str | None = None) -> dict[str, Any]:
    conn = sqlite3.connect(str(path))
    try:
        tables = [
            str(r[0])
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        table_rows: list[dict[str, Any]] = []
        for table in tables:
            count = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            cols = [str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            table_rows.append(
                {
                    "name": table,
                    "columns": cols,
                    "primary_key": _pragma_pk(conn, table),
                    "row_count": count,
                }
            )
        return {
            "path": str(path.resolve()),
            "kind": kind,
            "workspace_id": workspace_id,
            "tables": table_rows,
        }
    finally:
        conn.close()


def discover(*, repo_root: Path | None = None) -> dict[str, Any]:
    data = Path(repo_root).resolve() / "data" if repo_root is not None else data_dir()
    dbs: list[dict[str, Any]] = []
    market = data / "market.db"
    if market.is_file():
        dbs.append(_inventory_db(market, kind="market"))
    broker = data / "broker.db"
    if broker.is_file():
        dbs.append(_inventory_db(broker, kind="broker"))
    wiki_roots = [data / "wiki_workspaces", data / "wiki"]
    for wiki_root in wiki_roots:
        if not wiki_root.is_dir():
            continue
        for ws_dir in sorted(wiki_root.iterdir()):
            if not ws_dir.is_dir():
                continue
            wiki_db = ws_dir / "wiki.db"
            if wiki_db.is_file():
                dbs.append(_inventory_db(wiki_db, kind="wiki", workspace_id=ws_dir.name))
    legacy_wiki = data / "wiki.db"
    if legacy_wiki.is_file():
        dbs.append(_inventory_db(legacy_wiki, kind="wiki", workspace_id="default"))
    return {"databases": dbs}


def migration_table_order(manifest: dict[str, Any]) -> list[tuple[str, tuple[str, ...], str]]:
    """Return (table, pk_cols, db_kind) in FK-safe order for market tables."""
    order: list[tuple[str, tuple[str, ...], str]] = []
    market_order = [
        ("issuers", ("cik",)),
        ("filings", ("accession_number",)),
        ("issuer_facts", ("cik", "fact_key")),
        ("ingest_runs", ("run_id",)),
        ("http_audit", ("id",)),
        ("issuer_ingest_config", ("cik",)),
        ("observations", ("id",)),
        ("analysis_runs", ("run_id",)),
        ("filing_analysis_state", ("accession_number",)),
        ("narrative_observations", ("id",)),
        ("stock_prices", ("ticker", "date")),
        ("stock_bars", ("ticker", "interval", "bar_time")),
        ("price_harvest_jobs", ("job_id",)),
        ("event_harvest_jobs", ("job_id",)),
        ("open_data_sync_jobs", ("job_id",)),
        ("analyst_actions", ("id",)),
        ("research_views", ("view_id",)),
        ("universe_screens", ("screen_id",)),
        ("research_annotations", ("id",)),
        ("watch_alerts", ("alert_id",)),
        ("corporate_events", ("event_id",)),
        ("market_news", ("news_id",)),
        ("ticker_reference", ("ticker",)),
        ("macro_series", ("series_id",)),
        ("ticker_screen_metrics", ("ticker", "metric_key", "as_of_date")),
        ("ticker_fiscal_metrics", ("ticker", "period_end", "metric_key")),
        ("screen_metrics_runs", ("run_id",)),
        ("kpi_runs", ("run_id",)),
        (
            "kpi_observations",
            (
                "entity_type",
                "entity_id",
                "metric_id",
                "definition_version",
                "as_of_date",
                "period_end",
                "period_type",
                "calculation_mode",
                "formula_hash",
            ),
        ),
        ("pipeline_source_overrides", ("source_id",)),
        ("canonical_params", ("entity_type", "entity_id", "param_key", "granularity", "effective_at", "available_at")),
        ("param_coverage", ("entity_type", "entity_id", "param_key")),
        ("materialize_runs", ("run_id",)),
        ("data_revisions", ("scope",)),
        ("storage_inventory_snapshots", ("snapshot_id",)),
    ]
    for table, pk in market_order:
        order.append((table, pk, "market"))
    broker_order = [
        ("broker_account_snapshots", ("account",)),
        ("broker_positions", ("account", "symbol")),
        ("broker_sync_runs", ("id",)),
    ]
    for table, pk in broker_order:
        order.append((table, pk, "broker"))
    return order


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="Write JSON manifest path")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args()
    manifest = discover(repo_root=args.repo_root)
    text = json.dumps(manifest, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
