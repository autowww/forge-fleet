#!/usr/bin/env python3
"""Create MLflow Flask secret file if missing. Does not print the secret."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

ROOT = Path(os.environ.get("FORGE_MLFLOW_STATE", Path.home() / ".local/share/forge-mlflow"))


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    path = ROOT / "server.env"
    if not path.is_file() or "MLFLOW_FLASK_SERVER_SECRET_KEY=" not in path.read_text(encoding="utf-8"):
        path.write_text(f"MLFLOW_FLASK_SERVER_SECRET_KEY={secrets.token_hex(32)}\n", encoding="utf-8")
    path.chmod(0o600)
    print(f"server_env {path} ready")


if __name__ == "__main__":
    main()
