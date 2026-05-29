#!/usr/bin/env python3
"""One-shot: run bundle_admin_app.main then wc + node --check."""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import bundle_admin_app  # noqa: E402

bundle_admin_app.main()
admin = REPO / "fleet_server" / "static" / "admin"
for i in range(1, 7):
    p = admin / f"app-part{i}.js"
    n = len(p.read_text(encoding="utf-8").splitlines())
    print(f"LINE_COUNT app-part{i}.js {n}")
parts = sorted(admin.glob("app-part*.js"))
cat = b"".join(p.read_bytes() for p in parts)
proc = subprocess.run(["node", "--check", "-"], input=cat, capture_output=True)
if proc.returncode == 0:
    print("NODE_CHECK PASS")
else:
    print("NODE_CHECK FAIL")
    sys.stdout.buffer.write(proc.stderr)
    sys.exit(proc.returncode)
