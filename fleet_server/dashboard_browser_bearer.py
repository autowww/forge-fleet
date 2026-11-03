"""Optional dashboard bearer synced into /admin/ when explicitly enabled."""

from __future__ import annotations

from pathlib import Path


def bearer_path(data_dir: Path) -> Path:
    return data_dir / "etc" / "dashboard-browser-bearer"


def configured(data_dir: Path) -> bool:
    p = bearer_path(data_dir)
    return p.is_file() and bool(p.read_text(encoding="utf-8").strip())


def read_bearer(data_dir: Path) -> str:
    p = bearer_path(data_dir)
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8").strip()


def write_bearer(data_dir: Path, token: str) -> None:
    tok = (token or "").strip()
    if not tok:
        raise ValueError("bearer_required")
    path = bearer_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tok + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def clear_bearer(data_dir: Path) -> None:
    path = bearer_path(data_dir)
    if path.is_file():
        path.unlink()
