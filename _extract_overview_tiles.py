from pathlib import Path
admin = Path("fleet_server/static/admin")
lines = (admin / "app-part4.js").read_text(encoding="utf-8").splitlines(keepends=True)
body = "".join(lines[296:613])
if not body.endswith("\n"):
    body += "\n"
out = admin / "app-src/part4/overview-tiles.js"
out.write_text(body, encoding="utf-8")
print(f"wrote {out} ({len(body.splitlines())} lines)")
