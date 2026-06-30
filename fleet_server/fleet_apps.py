"""Fleet App Extension Protocol (FAEP) v1 — install registry, handlers, docs mirror."""

from __future__ import annotations

import hashlib
import html
import importlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

APP_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
ALLOWED_PERMISSIONS = frozenset({"read_host_paths", "invoke_local_cli"})
_HANDLER_CACHE: dict[str, dict[str, Any]] = {}


def default_catalog_url() -> str:
    return os.environ.get(
        "FLEET_APPS_CATALOG_URL",
        "https://fleet.forgesdlc.com/catalog/catalog.json",
    ).strip()


def _max_package_bytes() -> int:
    raw = os.environ.get("FLEET_APP_PACKAGE_MAX_BYTES", "67108864").strip()
    try:
        return max(1024, int(raw))
    except ValueError:
        return 67_108_864


def apps_root(data_dir: Path) -> Path:
    return data_dir / "apps"


def etc_apps_dir(data_dir: Path) -> Path:
    p = data_dir / "etc" / "fleet-apps"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _record_path(data_dir: Path, app_id: str) -> Path:
    if not APP_ID_RE.match(app_id):
        raise ValueError("invalid_app_id")
    return etc_apps_dir(data_dir) / f"{app_id}.json"


def load_installed_record(data_dir: Path, app_id: str) -> dict[str, Any] | None:
    p = _record_path(data_dir, app_id)
    if not p.is_file():
        return None
    doc = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("invalid_installed_record")
    return doc


def list_installed(data_dir: Path) -> list[dict[str, Any]]:
    root = etc_apps_dir(data_dir)
    out: list[dict[str, Any]] = []
    for p in sorted(root.glob("*.json")):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(doc, dict) and doc.get("id"):
            out.append(doc)
    return out


def snapshot_apps(data_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rec in list_installed(data_dir):
        if not rec.get("enabled", True):
            continue
        app_id = str(rec.get("id") or "")
        rows.append(
            {
                "id": app_id,
                "title": str(rec.get("title") or app_id),
                "version": str(rec.get("app_version") or ""),
                "summary": str(rec.get("summary") or ""),
                "enabled": True,
                "docs_index": f"/admin/apps/{app_id}/docs/",
                "admin_href": f"/admin/apps/{app_id}/",
            }
        )
    return rows


def fetch_remote_catalog(url: str | None = None) -> dict[str, Any]:
    target = (url or default_catalog_url()).strip()
    if not target.lower().startswith("https://"):
        raise ValueError("catalog_url_must_be_https")
    req = urllib.request.Request(target, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
    except urllib.error.URLError as ex:
        raise ValueError(f"catalog_fetch_failed:{ex}") from ex
    doc = json.loads(raw.decode("utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("invalid_catalog")
    return doc


def _find_catalog_entry(catalog: dict[str, Any], app_id: str, version: str | None) -> dict[str, Any]:
    apps = catalog.get("apps")
    if not isinstance(apps, list):
        raise ValueError("invalid_catalog")
    matches = [a for a in apps if isinstance(a, dict) and str(a.get("id") or "") == app_id]
    if not matches:
        raise ValueError("app_not_in_catalog")
    if version:
        for row in matches:
            if str(row.get("version") or "") == version:
                return row
        raise ValueError("version_not_in_catalog")
    if len(matches) == 1:
        return matches[0]
    versions = sorted({str(m.get("version") or "") for m in matches}, reverse=True)
    for ver in versions:
        for row in matches:
            if str(row.get("version") or "") == ver:
                return row
    return matches[0]


def _download_bytes(url: str) -> bytes:
    if not url.lower().startswith("https://"):
        raise ValueError("download_url_must_be_https")
    req = urllib.request.Request(url, headers={"Accept": "application/octet-stream"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    if len(data) > _max_package_bytes():
        raise ValueError("package_too_large")
    return data


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_manifest(install_dir: Path) -> dict[str, Any]:
    p = install_dir / "fleet-app.manifest.json"
    if not p.is_file():
        raise ValueError("manifest_missing")
    doc = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("invalid_manifest")
    if int(doc.get("protocol_version") or 0) != 1:
        raise ValueError("unsupported_protocol_version")
    app_id = str(doc.get("id") or "")
    if not APP_ID_RE.match(app_id):
        raise ValueError("invalid_app_id")
    return doc


def _extract_zip_bytes(data: bytes, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if not name or name.endswith("/"):
                continue
            parts = [p for p in name.split("/") if p]
            if ".." in parts:
                raise ValueError("zip_path_traversal")
            target = (dest / Path(*parts)).resolve()
            if not str(target).startswith(str(dest.resolve())):
                raise ValueError("zip_path_traversal")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)


def _pip_install_package(install_dir: Path, manifest: dict[str, Any]) -> Path | None:
    wheels = sorted((install_dir / "dist").glob("*.whl")) if (install_dir / "dist").is_dir() else []
    pyproject = install_dir / "pyproject.toml"
    src_pkg = install_dir / "src"
    target: str | None = None
    if wheels:
        target = str(wheels[0])
    elif pyproject.is_file():
        target = str(install_dir)
    elif src_pkg.is_dir():
        pkg_name = str((manifest.get("python") or {}).get("package") or "")
        if pkg_name:
            target = str(install_dir)
    if not target:
        return None
    site = install_dir / ".python_packages"
    site.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", "--target", str(site), target]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "pip_failed").strip()[:500]
        raise ValueError(f"pip_install_failed:{detail}")
    return site


def _ensure_handler_path(install_dir: Path, site: Path | None) -> None:
    for p in (site, install_dir / "src", install_dir):
        s = str(p) if p is not None else ""
        if s and Path(s).exists() and s not in sys.path:
            sys.path.insert(0, s)


def _validate_permissions(perms: Any) -> list[str]:
    if perms is None:
        return []
    if not isinstance(perms, list):
        raise ValueError("invalid_permissions")
    out: list[str] = []
    for item in perms:
        s = str(item or "").strip()
        if s not in ALLOWED_PERMISSIONS:
            raise ValueError(f"permission_not_allowed:{s}")
        out.append(s)
    return out


def install_package_bytes(
    data_dir: Path,
    data: bytes,
    *,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    if len(data) > _max_package_bytes():
        raise ValueError("package_too_large")
    digest = _sha256_hex(data)
    if expected_sha256 and digest.lower() != expected_sha256.lower():
        raise ValueError("sha256_mismatch")
    with tempfile.TemporaryDirectory(prefix="fleet-app-") as tmp:
        stage = Path(tmp) / "stage"
        _extract_zip_bytes(data, stage)
        manifest = _load_manifest(stage)
        app_id = str(manifest["id"])
        version = str(manifest.get("version") or "0.0.0")
        perms = _validate_permissions(manifest.get("permissions"))
        install_path = apps_root(data_dir) / app_id / version
        if install_path.exists():
            shutil.rmtree(install_path)
        shutil.copytree(stage, install_path)
        site = _pip_install_package(install_path, manifest)
        if site is not None:
            record_site = str(site.resolve())
        else:
            record_site = None
        _HANDLER_CACHE.pop(app_id, None)
        record = {
            "version": 1,
            "id": app_id,
            "app_version": version,
            "title": str(manifest.get("title") or app_id),
            "summary": str(manifest.get("summary") or ""),
            "enabled": True,
            "install_path": str(install_path.resolve()),
            "python_site": record_site,
            "installed_at": datetime.now(UTC).isoformat(),
            "sha256": digest,
            "permissions": perms,
        }
        _record_path(data_dir, app_id).write_text(
            json.dumps(record, indent=2) + "\n",
            encoding="utf-8",
        )
        return record


def install_from_catalog(
    data_dir: Path,
    app_id: str,
    *,
    version: str | None = None,
    catalog_url: str | None = None,
) -> dict[str, Any]:
    if not APP_ID_RE.match(app_id):
        raise ValueError("invalid_app_id")
    catalog = fetch_remote_catalog(catalog_url)
    entry = _find_catalog_entry(catalog, app_id, version)
    url = str(entry.get("download_url") or "").strip()
    sha = str(entry.get("sha256") or "").strip()
    if not url or not sha:
        raise ValueError("catalog_entry_incomplete")
    blob = _download_bytes(url)
    return install_package_bytes(data_dir, blob, expected_sha256=sha)


def uninstall(data_dir: Path, app_id: str) -> None:
    rec = load_installed_record(data_dir, app_id)
    if rec is None:
        raise ValueError("not_installed")
    install_path = Path(str(rec.get("install_path") or ""))
    if install_path.is_dir():
        shutil.rmtree(install_path, ignore_errors=True)
    app_parent = apps_root(data_dir) / app_id
    if app_parent.is_dir() and not any(app_parent.iterdir()):
        shutil.rmtree(app_parent, ignore_errors=True)
    p = _record_path(data_dir, app_id)
    if p.is_file():
        p.unlink()
    _HANDLER_CACHE.pop(app_id, None)


def _install_dir_for(data_dir: Path, app_id: str) -> Path:
    rec = load_installed_record(data_dir, app_id)
    if rec is None:
        raise ValueError("not_installed")
    p = Path(str(rec.get("install_path") or "")).resolve()
    if not p.is_dir():
        raise ValueError("install_path_missing")
    return p


def get_ui_spec(data_dir: Path, app_id: str) -> dict[str, Any]:
    install_dir = _install_dir_for(data_dir, app_id)
    manifest = _load_manifest(install_dir)
    rel = str((manifest.get("ui") or {}).get("spec") or "ui/app.ui.json")
    spec_path = (install_dir / rel).resolve()
    if not str(spec_path).startswith(str(install_dir.resolve())):
        raise ValueError("ui_spec_path_invalid")
    if not spec_path.is_file():
        raise ValueError("ui_spec_missing")
    doc = json.loads(spec_path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("invalid_ui_spec")
    return doc


def _load_handlers(data_dir: Path, app_id: str) -> dict[str, Any]:
    cached = _HANDLER_CACHE.get(app_id)
    if cached is not None:
        return cached
    install_dir = _install_dir_for(data_dir, app_id)
    manifest = _load_manifest(install_dir)
    rec = load_installed_record(data_dir, app_id) or {}
    site_raw = str(rec.get("python_site") or "").strip()
    site = Path(site_raw) if site_raw else install_dir / ".python_packages"
    _ensure_handler_path(install_dir, site if site.is_dir() else None)
    py_info = manifest.get("python") if isinstance(manifest.get("python"), dict) else {}
    module_name = str(py_info.get("handlers_module") or "").strip()
    if not module_name:
        raise ValueError("handlers_module_missing")
    mod = importlib.import_module(module_name)
    reg_fn: Callable[[], dict[str, Any]] | None = getattr(mod, "register_handlers", None)
    if reg_fn is None:
        raise ValueError("register_handlers_missing")
    reg = reg_fn()
    if not isinstance(reg, dict):
        raise ValueError("invalid_handlers_registry")
    _HANDLER_CACHE[app_id] = reg
    return reg


def _handler_ctx(data_dir: Path, app_id: str) -> dict[str, Any]:
    rec = load_installed_record(data_dir, app_id) or {}
    return {
        "app_id": app_id,
        "data_dir": str(data_dir.resolve()),
        "install_path": str(rec.get("install_path") or ""),
        "permissions": list(rec.get("permissions") or []),
    }


def call_data_handler(data_dir: Path, app_id: str, binding: str) -> Any:
    reg = _load_handlers(data_dir, app_id)
    data_map = reg.get("data") if isinstance(reg.get("data"), dict) else {}
    fn = data_map.get(binding)
    if not callable(fn):
        raise ValueError("unknown_data_binding")
    return fn(_handler_ctx(data_dir, app_id))


def call_action_handler(data_dir: Path, app_id: str, action: str, body: dict[str, Any]) -> Any:
    reg = _load_handlers(data_dir, app_id)
    actions = reg.get("actions") if isinstance(reg.get("actions"), dict) else {}
    fn = actions.get(action)
    if not callable(fn):
        raise ValueError("unknown_action")
    return fn(_handler_ctx(data_dir, app_id), body)


def _docs_root(data_dir: Path, app_id: str) -> Path:
    install_dir = _install_dir_for(data_dir, app_id)
    manifest = _load_manifest(install_dir)
    rel = str((manifest.get("docs") or {}).get("root") or "docs")
    root = (install_dir / rel).resolve()
    if not root.is_dir() or not str(root).startswith(str(install_dir.resolve())):
        raise ValueError("docs_root_missing")
    return root


def list_doc_slugs(data_dir: Path, app_id: str) -> list[str]:
    root = _docs_root(data_dir, app_id)
    slugs: list[str] = []
    for p in sorted(root.rglob("*.md")):
        rel = p.relative_to(root).as_posix()
        if rel.lower() == "readme.md":
            slugs.append("index")
        else:
            slugs.append(rel[:-3].replace("/", "-"))
    return slugs


def _resolve_doc_path(root: Path, slug: str) -> Path | None:
    slug = slug.strip().strip("/")
    if slug in ("", "index", "index.html"):
        candidates = [root / "README.md", root / "index.md"]
    else:
        parts = slug.replace("-", "/").split("/")
        if parts[-1].endswith(".html"):
            parts[-1] = parts[-1][:-5]
        candidates = [root / Path(*parts[:-1]) / f"{parts[-1]}.md" if parts else root / "README.md"]
        flat = slug.replace("/", "-")
        candidates.append(root / f"{flat}.md")
        candidates.append(root / f"{slug}.md")
    for c in candidates:
        try:
            resolved = c.resolve()
            resolved.relative_to(root.resolve())
        except (ValueError, OSError):
            continue
        if resolved.is_file():
            return resolved
    return None


def _md_to_html(md: str, title: str) -> str:
    lines = md.splitlines()
    out: list[str] = []
    in_code = False
    for line in lines:
        if line.startswith("```"):
            if in_code:
                out.append("</code></pre>")
                in_code = False
            else:
                out.append('<pre class="fleet-mono small p-2 rounded border bg-body-secondary"><code>')
                in_code = True
            continue
        if in_code:
            out.append(html.escape(line))
            continue
        if line.startswith("#### "):
            out.append(f"<h5>{html.escape(line[5:])}</h5>")
        elif line.startswith("### "):
            out.append(f"<h4>{html.escape(line[4:])}</h4>")
        elif line.startswith("## "):
            out.append(f"<h3>{html.escape(line[3:])}</h3>")
        elif line.startswith("# "):
            out.append(f"<h2>{html.escape(line[2:])}</h2>")
        elif line.strip() == "":
            out.append("")
        elif line.startswith("|"):
            out.append(line)
        else:
            out.append(f"<p>{html.escape(line)}</p>")
    body = "\n".join(out)
    return (
        f"<!DOCTYPE html><html lang=\"en\" data-bs-theme=\"dark\"><head>"
        f"<meta charset=\"utf-8\"/><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"/>"
        f"<title>{html.escape(title)}</title>"
        f"<link rel=\"stylesheet\" href=\"https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css\"/>"
        f"<link rel=\"stylesheet\" href=\"/admin/ks/css/forge-theme.css\"/>"
        f"<link rel=\"stylesheet\" href=\"/admin/ks/css/forge-fleet-admin.css\"/>"
        f"</head><body class=\"fleet-admin-body\"><main class=\"container py-4\">"
        f"<p class=\"small\"><a href=\"/admin/\">Fleet admin</a></p>"
        f"{body}</main></body></html>"
    )


def render_doc_html(data_dir: Path, app_id: str, slug: str) -> str | None:
    root = _docs_root(data_dir, app_id)
    path = _resolve_doc_path(root, slug)
    if path is None:
        return None
    md = path.read_text(encoding="utf-8")
    title = f"{app_id} docs"
    return _md_to_html(md, title)


def app_host_html(app_id: str, title: str) -> str:
    safe_id = html.escape(app_id)
    safe_title = html.escape(title)
    return (
        f"<!DOCTYPE html><html lang=\"en\" data-bs-theme=\"dark\"><head>"
        f"<meta charset=\"utf-8\"/><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"/>"
        f"<title>{safe_title}</title>"
        f"<link rel=\"stylesheet\" href=\"https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css\"/>"
        f"<link rel=\"stylesheet\" href=\"/admin/ks/css/forge-theme.css\"/>"
        f"<link rel=\"stylesheet\" href=\"/admin/ks/css/forge-fleet-admin.css\"/>"
        f"</head><body class=\"fleet-admin-body\"><main class=\"container py-4\">"
        f"<p class=\"small mb-3\"><a href=\"/admin/\">Fleet admin</a> · "
        f"<a href=\"/admin/apps/{safe_id}/docs/\">Docs</a></p>"
        f"<div id=\"fleet-app-root\" data-fleet-app-id=\"{safe_id}\"></div>"
        f"<script src=\"/admin/ks/js/forge-fleet-app-ui.js\"></script>"
        f"<script>"
        f"(function(){{"
        f"var root=document.getElementById('fleet-app-root');"
        f"var tok=localStorage.getItem('forgeFleetAdminToken')||'';"
        f"if(window.ForgeFleetAppUi){{ForgeFleetAppUi.mount(root,{{"
        f"appId:'{safe_id}',uiUrl:'/v1/fleet-apps/{safe_id}/ui',"
        f"dataBase:'/v1/fleet-apps/{safe_id}/data',"
        f"actionsBase:'/v1/fleet-apps/{safe_id}/actions',token:tok"
        f"}});}}"
        f"}})();"
        f"</script></main></body></html>"
    )
