#!/usr/bin/env python3
"""Write the Venus MLflow auth-gate env file. Does not print secrets."""
from __future__ import annotations

import secrets
from pathlib import Path

DEST = Path.home() / ".config/forge-auth-gate/gate.env"


def main() -> None:
    DEST.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_hex(32)
    if DEST.is_file():
        for line in DEST.read_text(encoding="utf-8").splitlines():
            if line.startswith("FORGE_AUTH_GATE_SECRET=") and len(line.split("=", 1)[1]) >= 16:
                secret = line.split("=", 1)[1]
                break
    text = "\n".join(
        [
            f"FORGE_AUTH_GATE_SECRET={secret}",
            "FORGE_AUTH_GATE_PUBLIC_ORIGIN=https://mlflow.forgedc.net",
            "FORGE_AUTH_GATE_UPSTREAM=http://127.0.0.1:5050",
            "FORGE_AUTH_GATE_LOGIN_ORIGIN=https://login.forgedc.net",
            "FORGE_AUTH_GATE_REDEEM_URL=https://login.forgedc.net/gateway/auth/redeem",
            "FORGE_AUTH_GATE_MODE=mlflow",
            "FORGE_AUTH_GATE_HOST=127.0.0.1",
            "FORGE_AUTH_GATE_PORT=5051",
            "FORGE_AUTH_GATE_TRUSTED_EMAIL_HEADER=X-Forwarded-Email",
            f"FORGE_AUTH_GATE_MLFLOW_HMAC_SECRET={secret}",
            "",
        ]
    )
    DEST.write_text(text, encoding="utf-8")
    DEST.chmod(0o600)
    print(f"gate_env {DEST} ready")


if __name__ == "__main__":
    main()
