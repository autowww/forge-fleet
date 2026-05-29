#!/usr/bin/env python3
"""One-off verification for part3 fragment concat vs HEAD."""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[0]
PART3 = REPO / "fleet_server/static/admin/app-src/part3"
MANIFEST = PART3 / "MANIFEST.txt"
HEAD_PART3 = REPO / "fleet_server/static/admin/app-part3.js"

names = []
for line in MANIFEST.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#"):
        names.append(line)

print("=== Line counts per part3 fragment ===")
total = 0
for name in names:
    p = PART3 / name
    n = len(p.read_text(encoding="utf-8").splitlines())
    total += n
    print(f"  {name}: {n}")
print(f"  TOTAL (concat): {total}")

head_text = subprocess.check_output(
    ["git", "show", "HEAD:fleet_server/static/admin/app-part3.js"],
    cwd=REPO,
    text=True,
)
concat_chunks = []
for name in names:
    t = (PART3 / name).read_text(encoding="utf-8")
    if not t.endswith("\n"):
        t += "\n"
    concat_chunks.append(t)
concat_text = "".join(concat_chunks)

head_lines = len(head_text.splitlines())
print(f"\nHEAD app-part3.js: {head_lines} lines, {len(head_text.encode())} bytes")
print(f"Concat fragments: {len(concat_text.splitlines())} lines, {len(concat_text.encode())} bytes")
print(f"BYTE_MATCH (full HEAD): {'yes' if head_text == concat_text else 'no'}")

# Semantic region: HEAD after modal-chart-rows close (line before fleetTelemetryXAxisMarkup)
marker = "    /** UTC x-axis ticks and labels below the plot"
idx = head_text.find(marker)
if idx >= 0:
    head_sem = head_text[idx:]
    print(f"BYTE_MATCH (HEAD from x-axis marker): {'yes' if head_sem == concat_text else 'no'}")
    if head_sem != concat_text:
        for i, (a, b) in enumerate(zip(head_sem, concat_text)):
            if a != b:
                print(f"  first diff at byte {i}: HEAD={a!r} concat={b!r}")
                break
        else:
            if len(head_sem) != len(concat_text):
                print(f"  length diff: HEAD={len(head_sem)} concat={len(concat_text)}")

# Footprint scan
scan = Path("/home/lzvyahin/Code/blueprints/sdlc/methodologies/forge/setup/code_footprint_scan.py")
if scan.is_file():
    import subprocess
    print("\n=== Footprint scan (part3) ===")
    r = subprocess.run(
        [sys.executable, str(scan), str(PART3), str(HEAD_PART3)],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    out = (r.stdout + r.stderr).splitlines()[:40]
    print("\n".join(out))
    print(f"exit={r.returncode}")

# Bundle
print("\n=== bundle_admin_app.py (tail) ===")
r2 = subprocess.run(
    [sys.executable, str(REPO / "scripts/bundle_admin_app.py")],
    cwd=REPO,
    capture_output=True,
    text=True,
)
tail = (r2.stdout + r2.stderr).splitlines()[-5:]
print("\n".join(tail))
print(f"exit={r2.returncode}")
