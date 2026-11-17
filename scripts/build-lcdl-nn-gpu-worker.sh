#!/usr/bin/env bash
# Fetch forge-lcdl on this host and build the GPU worker image. Code arrives by git.
set -euo pipefail

log() { printf 'build-lcdl-nn-gpu-worker: %s\n' "$*"; }
die() { log "ERROR: $*"; exit 1; }

IMAGE="${FORGE_LCDL_NN_GPU_IMAGE:-forge-lcdl-nn-gpu-worker:local}"
REF="${FORGE_LCDL_GIT_REF:-}"
ROOT="${FORGE_LCDL_ROOT:-}"

if [[ -z "$ROOT" ]]; then
  for candidate in \
    "/home/administrator/forge-lcdl" \
    "/home/administrator/Code/forge-lcdl" \
    "$HOME/forge-lcdl" \
    "$HOME/Code/forge-lcdl"; do
    if [[ ! -d "$candidate/.git" && ! -f "$candidate/.git" ]]; then
      continue
    fi
    if [[ -z "$REF" && ! -f "$candidate/deploy/nn-gpu-worker/Dockerfile" ]]; then
      continue
    fi
    ROOT="$candidate"
    break
  done
fi

[[ -n "$ROOT" && ( -d "$ROOT/.git" || -f "$ROOT/.git" ) ]] || die "forge-lcdl checkout missing (set FORGE_LCDL_ROOT)"
command -v git >/dev/null || die "git missing"
command -v docker >/dev/null || die "docker missing"

cd "$ROOT"
if [[ -n "$REF" ]]; then
  log "fetch ${REF} in ${ROOT}"
  git fetch origin "$REF"
  sha="$(git rev-parse FETCH_HEAD)"
  work="${FORGE_LCDL_WORKTREE:-${ROOT}-train-build}"
  if [[ -e "$work/.git" ]]; then
    git -C "$work" checkout --detach "$sha"
  else
    git worktree add --detach "$work" "$sha"
  fi
  ROOT="$work"
  cd "$ROOT"
else
  log "building current checkout ${ROOT} ($(git rev-parse --short=12 HEAD))"
fi

[[ -f "$ROOT/deploy/nn-gpu-worker/Dockerfile" ]] || die "Dockerfile missing in ${ROOT}"
log "docker build ${IMAGE}"
docker build -f deploy/nn-gpu-worker/Dockerfile -t "$IMAGE" .
log "built ${IMAGE} from $(git rev-parse --short=12 HEAD)"
