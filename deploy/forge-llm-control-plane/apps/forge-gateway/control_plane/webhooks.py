"""HMAC webhook delivery for async jobs."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import httpx


def sign_payload(secret: str, body: bytes, ts: int | None = None) -> tuple[str, int]:
    ts = ts or int(time.time())
    msg = f"{ts}.".encode() + body
    sig = hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
    return sig, ts


async def deliver_webhook(
    url: str,
    secret: str,
    payload: dict[str, Any],
    *,
    timeout: float = 30.0,
) -> tuple[bool, str | None]:
    body = json.dumps(payload, separators=(",", ":")).encode()
    sig, ts = sign_payload(secret, body)
    headers = {
        "Content-Type": "application/json",
        "X-Forge-Webhook-Timestamp": str(ts),
        "X-Forge-Webhook-Signature": f"sha256={sig}",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, content=body, headers=headers)
            if r.status_code >= 400:
                return False, f"http_{r.status_code}"
    except httpx.RequestError as exc:
        return False, str(exc)[:200]
    return True, None


def verify_signature(secret: str, body: bytes, ts: str, signature: str) -> bool:
    expected, _ = sign_payload(secret, body, int(ts))
    provided = signature.replace("sha256=", "")
    return hmac.compare_digest(expected, provided)
