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
    if [[ -f "$candidate/deploy/nn-gpu-worker/Dockerfile" ]]; then
      ROOT="$candidate"
      break
    fi
  done
fi

[[ -n "$ROOT" && -f "$ROOT/deploy/nn-gpu-worker/Dockerfile" ]] || die "forge-lcdl checkout missing (set FORGE_LCDL_ROOT)"
command -v git >/dev/null || die "git missing"
command -v docker >/dev/null || die "docker missing"

cd "$ROOT"
if [[ -n "$REF" ]]; then
  log "fetch ${REF} in ${ROOT}"
  git fetch origin "$REF"
  git checkout "$REF"
  git merge --ff-only "origin/${REF}"
else
  log "building current checkout ${ROOT} ($(git rev-parse --short=12 HEAD))"
fi

log "docker build ${IMAGE}"
docker build -f deploy/nn-gpu-worker/Dockerfile -t "$IMAGE" .
log "built ${IMAGE} from $(git rev-parse --short=12 HEAD)"
