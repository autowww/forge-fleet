"""Helpers for Prometheus text exposition."""

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest


def metrics_response() -> tuple[bytes, str]:
    """Return (body, content_type) for GET /metrics."""
    return generate_latest(), CONTENT_TYPE_LATEST
