#!/usr/bin/env python3
"""Write MLflow basic_auth.ini from deploy/mlflow/.env. Does not print secrets."""
from __future__ import annotations

import os
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[1]
ENV_FILE = DEPLOY / ".env"
ROOT = Path(os.environ.get("FORGE_MLFLOW_STATE", Path.home() / ".local/share/forge-mlflow"))


def load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        chunk = line.strip()
        if not chunk or chunk.startswith("#") or "=" not in chunk:
            continue
        key, _, val = chunk.partition("=")
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def main() -> None:
    env = load_env(ENV_FILE)
    admin = env.get("MLFLOW_ADMIN_USERNAME") or "admin"
    password = env.get("MLFLOW_ADMIN_PASSWORD") or ""
    if not password:
        raise SystemExit("MLFLOW_ADMIN_PASSWORD is empty in .env")
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "artifacts").mkdir(exist_ok=True)
    db = ROOT / "basic_auth.db"
    ini = ROOT / "basic_auth.ini"
    ini.write_text(
        "\n".join(
            [
                "[mlflow]",
                "default_permission = READ",
                f"database_uri = sqlite:///{db}",
                f"admin_username = {admin}",
                f"admin_password = {password}",
                "authorization_function = mlflow.server.auth:authenticate_request_basic_auth",
                "",
            ]
        ),
        encoding="utf-8",
    )
    ini.chmod(0o600)
    print(f"wrote {ini} admin_set=yes")


if __name__ == "__main__":
    main()
