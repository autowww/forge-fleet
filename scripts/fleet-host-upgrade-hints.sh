#!/usr/bin/env bash
# fleet-host-upgrade-hints.sh — print host-level commands between two Fleet semver versions (never executes them).
#
# Data: docs/host-operator-steps.json (maintained with CHANGELOG.md ### Host operator).
#
# Examples:
#   ./scripts/fleet-host-upgrade-hints.sh --from 0.3.40 --to 0.3.49
#   ./scripts/fleet-host-upgrade-hints.sh --from 0.3.40   # --to defaults from pyproject.toml in this repo
#   FORGE_FLEET_BASE_URL=http://127.0.0.1:18766 ./scripts/fleet-host-upgrade-hints.sh --discover-from --to 0.3.49
#
# --discover-from reads package_semver from GET {FORGE_FLEET_BASE_URL}/v1/version (set FORGE_FLEET_BEARER_TOKEN when required).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JSON="$ROOT/docs/host-operator-steps.json"
FROM=""
TO=""
DISCOVER=0

usage() {
  sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//' >&2
  echo "Options:" >&2
  echo "  --from SEMVER           lower bound (exclusive); required unless --discover-from" >&2
  echo "  --to SEMVER             upper bound (inclusive); default: version from pyproject.toml" >&2
  echo "  --discover-from         set --from from GET /v1/version (FORGE_FLEET_BASE_URL; optional bearer)" >&2
  echo "  --json PATH             override host-operator-steps.json location" >&2
  echo "  -h, --help" >&2
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --from)
      FROM="${2:-}"
      [[ -n "$FROM" ]] || { echo "fleet-host-upgrade-hints: --from needs a value" >&2; exit 2; }
      shift 2
      ;;
    --to)
      TO="${2:-}"
      [[ -n "$TO" ]] || { echo "fleet-host-upgrade-hints: --to needs a value" >&2; exit 2; }
      shift 2
      ;;
    --json)
      JSON="${2:-}"
      [[ -n "$JSON" ]] || { echo "fleet-host-upgrade-hints: --json needs a path" >&2; exit 2; }
      shift 2
      ;;
    --discover-from) DISCOVER=1; shift ;;
    -h|--help) usage 0 ;;
    *)
      echo "fleet-host-upgrade-hints: unknown option: $1" >&2
      usage 2
      ;;
  esac
done

if [[ "$DISCOVER" -eq 1 ]]; then
  _base="${FORGE_FLEET_BASE_URL:-}"
  _base="${_base%/}"
  if [[ -z "$_base" ]]; then
    echo "fleet-host-upgrade-hints: --discover-from requires FORGE_FLEET_BASE_URL (scheme + host + port, no /v1 suffix)" >&2
    exit 2
  fi
  if [[ -n "${FORGE_FLEET_BEARER_TOKEN:-}" ]]; then
    FROM="$(curl -fsS -H "Authorization: Bearer ${FORGE_FLEET_BEARER_TOKEN}" "${_base}/v1/version" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('package_semver') or '')")"
  else
    FROM="$(curl -fsS "${_base}/v1/version" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('package_semver') or '')")"
  fi
  if [[ -z "$FROM" ]]; then
    echo "fleet-host-upgrade-hints: could not read package_semver from ${_base}/v1/version" >&2
    exit 2
  fi
fi

if [[ -z "$FROM" ]]; then
  echo "fleet-host-upgrade-hints: provide --from SEMVER or --discover-from (with FORGE_FLEET_BASE_URL)" >&2
  exit 2
fi

if [[ -z "$TO" ]]; then
  TO="$(
    python3 -c "import re; from pathlib import Path; p=Path('${ROOT}')/'pyproject.toml'; t=p.read_text(encoding='utf-8') if p.is_file() else ''; m=re.search(r'(?m)^version\s*=\s*\"([^\"]+)\"', t); print(m.group(1) if m else '0.0.0')"
  )"
fi

[[ -f "$JSON" ]] || { echo "fleet-host-upgrade-hints: missing $JSON" >&2; exit 2; }

python3 -c "
import json, re, sys
from pathlib import Path

def parse_version(v):
    v = (v or '').strip()
    if not v:
        raise ValueError('empty semver')
    parts = v.split('.')
    nums = []
    for p in parts[:3]:
        if not re.fullmatch(r'[0-9]+', p or ''):
            raise ValueError('semver must be numeric major.minor.patch segments: ' + repr(v))
        nums.append(int(p))
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)

path = Path(sys.argv[1])
from_v = sys.argv[2]
to_v = sys.argv[3]
F = parse_version(from_v)
T = parse_version(to_v)
if F > T:
    print('fleet-host-upgrade-hints: --from must be less than or equal to --to', file=sys.stderr)
    sys.exit(2)
if F == T:
    print('fleet-host-upgrade-hints: --from and --to are equal; no version span to scan.', file=sys.stderr)
    sys.exit(0)
raw = path.read_text(encoding='utf-8')
entries = json.loads(raw)
if not isinstance(entries, list):
    print('fleet-host-upgrade-hints: JSON root must be an array', file=sys.stderr)
    sys.exit(2)
shown = False
for e in entries:
    if not isinstance(e, dict):
        continue
    ver = str(e.get('version', '')).strip()
    if not ver:
        continue
    try:
        ev = parse_version(ver)
    except ValueError as ex:
        print('fleet-host-upgrade-hints: ' + str(ex), file=sys.stderr)
        sys.exit(2)
    if F < ev <= T:
        shown = True
        title = str(e.get('title') or ver)
        print()
        print('## ' + title + '  (since ' + ver + ')')
        print()
        cmds = e.get('commands')
        if isinstance(cmds, list):
            for line in cmds:
                print(str(line))
        print()
if not shown:
    print('No host-operator-steps.json entries with from < version <= to.', file=sys.stderr)
    print('See CHANGELOG.md \"### Host operator\" for narrative release notes.', file=sys.stderr)
" "$JSON" "$FROM" "$TO"
