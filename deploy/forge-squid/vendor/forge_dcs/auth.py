"""Single fixed principal (P01–P04).

- Exactly one bearer token maps to exactly one tenant (``DCS_BEARER_TOKEN`` → ``DCS_TENANT_ID``).
- No anonymous default: if the token is not configured the service refuses with 503.
- A body-supplied ``tenant_id`` must equal the authenticated principal or the request is 403.
- Tokens are never logged or echoed in error bodies.
"""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass

from forge_dcs import errors

ENV_TOKEN = "DCS_BEARER_TOKEN"
ENV_TENANT = "DCS_TENANT_ID"
MIN_TOKEN_LEN = 16


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    subject: str = "operator"


@dataclass(frozen=True)
class AuthConfig:
    token: str | None
    tenant_id: str | None

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "AuthConfig":
        e = env if env is not None else os.environ
        tok = (e.get(ENV_TOKEN) or "").strip() or None
        ten = (e.get(ENV_TENANT) or "").strip() or None
        return cls(token=tok, tenant_id=ten)

    def ensure_configured(self) -> None:
        if not self.token or not self.tenant_id or len(self.token) < MIN_TOKEN_LEN:
            raise errors.DcsError(
                errors.AUTH_NOT_CONFIGURED,
                "service principal is not configured (DCS_BEARER_TOKEN / DCS_TENANT_ID)",
                http_status=503,
            )


def authenticate(authorization: str | None, cfg: AuthConfig) -> Principal:
    cfg.ensure_configured()
    if not authorization:
        raise errors.DcsError(errors.AUTH_REQUIRED, "missing Authorization header", http_status=401)
    scheme, _, presented = authorization.partition(" ")
    if scheme.lower() != "bearer" or not presented:
        raise errors.DcsError(errors.AUTH_INVALID, "invalid Authorization scheme", http_status=401)
    assert cfg.token is not None and cfg.tenant_id is not None
    if not hmac.compare_digest(presented.strip().encode(), cfg.token.encode()):
        raise errors.DcsError(errors.AUTH_INVALID, "invalid bearer token", http_status=401)
    return Principal(tenant_id=cfg.tenant_id)


def local_principal(cfg: AuthConfig) -> Principal:
    """CLI principal: same single-tenant mapping; no token presented over the wire."""
    cfg.ensure_configured()
    assert cfg.tenant_id is not None
    return Principal(tenant_id=cfg.tenant_id, subject="cli")


def resolve_tenant(principal: Principal, body_tenant: str | None) -> str:
    if body_tenant is not None and body_tenant != principal.tenant_id:
        raise errors.DcsError(
            errors.TENANT_MISMATCH,
            "tenant_id in request body does not match authenticated principal",
            http_status=403,
        )
    return principal.tenant_id
