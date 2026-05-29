"""Assemble the Fleet admin HTML shell from static fragments."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

_HTML_SRC_PARTS = ("static", "admin", "html_src")


def _html_src_root(*, html_src: Path | None = None):
    if html_src is not None:
        return html_src
    return resources.files("fleet_server").joinpath(*_HTML_SRC_PARTS)


def _manifest_names(manifest_text: str) -> list[str]:
    names: list[str] = []
    for line in manifest_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        names.append(line)
    return names


def assemble_admin_html(*, html_src: Path | None = None) -> str:
    """Concatenate ``html_src`` fragments in MANIFEST order."""
    root = _html_src_root(html_src=html_src)
    manifest_text = (root / "MANIFEST.txt").read_text(encoding="utf-8")
    chunks: list[str] = []
    for name in _manifest_names(manifest_text):
        text = (root / name).read_text(encoding="utf-8")
        if not text.endswith("\n"):
            text += "\n"
        chunks.append(text)
    body = "".join(chunks)
    if not body.endswith("\n"):
        body += "\n"
    return body


def assemble_admin_html_bytes(*, html_src: Path | None = None) -> bytes:
    return assemble_admin_html(html_src=html_src).encode("utf-8")
