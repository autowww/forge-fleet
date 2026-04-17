"""Resolve preset telemetry query windows (UTC wall-clock)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

# GET /v1/telemetry?period=<one of these>
PERIOD_ALIASES: Final[dict[str, str]] = {
    "last_365_days": "last_year",
    "last_24h": "last_24_hours",
    "last_8h": "last_8_hours",
    "last_4h": "last_4_hours",
    "last_1h": "last_1_hour",
    "last_hour": "last_1_hour",
}

ALL_PERIODS: Final[tuple[str, ...]] = (
    "since_first",
    "last_year",
    "last_6_months",
    "last_3_months",
    "last_1_month",
    "this_year",
    "this_quarter",
    "this_month",
    "this_week",
    "today",
    "last_7_days",
    "last_3_days",
    "last_24_hours",
    "last_8_hours",
    "last_4_hours",
    "last_1_hour",
)

PERIODS_DOC: Final[str] = ", ".join(ALL_PERIODS)


def _utc_now(now: datetime | None) -> datetime:
    n = now or datetime.now(UTC)
    if n.tzinfo is None:
        return n.replace(tzinfo=UTC)
    return n.astimezone(UTC)


def _epoch(dt: datetime) -> float:
    return dt.timestamp()


def _start_of_day_utc(dt: datetime) -> datetime:
    d = _utc_now(dt)
    return d.replace(hour=0, minute=0, second=0, microsecond=0)


def _start_of_iso_week_utc(dt: datetime) -> datetime:
    d = _utc_now(dt).date()
    monday = d - timedelta(days=d.weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=UTC)


def _start_of_month_utc(dt: datetime) -> datetime:
    d = _utc_now(dt)
    return d.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _start_of_quarter_utc(dt: datetime) -> datetime:
    d = _utc_now(dt)
    q0 = (d.month - 1) // 3 * 3 + 1
    return d.replace(month=q0, day=1, hour=0, minute=0, second=0, microsecond=0)


def _start_of_year_utc(dt: datetime) -> datetime:
    d = _utc_now(dt)
    return d.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)


def resolve_period_window(
    period: str,
    *,
    now: datetime | None = None,
    first_sample_ts: float | None = None,
) -> tuple[float, float]:
    """
    Inclusive wall-time window ``[start, end]`` as Unix epoch seconds (float).

    ``since_first`` uses ``first_sample_ts`` when provided; otherwise ``end`` only (empty query upstream).
    Rolling windows (``last_*``) use fixed day counts where noted. Calendar windows use UTC boundaries.
    """
    raw = (period or "").strip()
    key = PERIOD_ALIASES.get(raw, raw)
    n = _utc_now(now)
    end = _epoch(n)

    if key == "since_first":
        if first_sample_ts is None:
            return end, end
        return float(first_sample_ts), end

    if key == "last_year":
        return _epoch(n - timedelta(days=365)), end
    if key == "last_6_months":
        return _epoch(n - timedelta(days=183)), end
    if key == "last_3_months":
        return _epoch(n - timedelta(days=92)), end
    if key == "last_1_month":
        return _epoch(n - timedelta(days=31)), end

    if key == "this_year":
        return _epoch(_start_of_year_utc(n)), end
    if key == "this_quarter":
        return _epoch(_start_of_quarter_utc(n)), end
    if key == "this_month":
        return _epoch(_start_of_month_utc(n)), end
    if key == "this_week":
        return _epoch(_start_of_iso_week_utc(n)), end
    if key == "today":
        return _epoch(_start_of_day_utc(n)), end

    if key == "last_7_days":
        return _epoch(n - timedelta(days=7)), end
    if key == "last_3_days":
        return _epoch(n - timedelta(days=3)), end
    if key == "last_24_hours":
        return _epoch(n - timedelta(hours=24)), end
    if key == "last_8_hours":
        return _epoch(n - timedelta(hours=8)), end
    if key == "last_4_hours":
        return _epoch(n - timedelta(hours=4)), end
    if key == "last_1_hour":
        return _epoch(n - timedelta(hours=1)), end

    raise ValueError(f"unknown period {period!r}; use one of: {PERIODS_DOC}")
