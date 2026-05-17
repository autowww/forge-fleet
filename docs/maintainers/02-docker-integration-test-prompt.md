# Prompt: run real Docker integration test (Forge Fleet)

> **Maintainer-facing:** paste prompt for disposable environments; pytest flags or Docker prerequisites may drift between releases—verify against **`pytest.ini`** locally.

Copy everything inside the block below into a new Cursor chat (or any agent). Adjust `forge-fleet` path if your clone differs.

---

## Agent prompt (paste this)

Run the Forge Fleet **real Docker** integration test on this machine and report the result.

1. ** Preconditions:** `docker info` must succeed in the same environment you use for pytest (same user / groups / `PATH`). Do not skip unless Docker is actually unavailable.

2. ** Commands** (from repo root that contains `forge-fleet/pyproject.toml`, or `cd` into `forge-fleet`):

   ```bash
   cd forge-fleet
   unset SKIP_DOCKER_INTEGRATION 2>/dev/null || true
   python3 -m pytest tests/test_fleet_docker_integration.py -v --tb=short
   ```

3. ** Optional:** use another image if Alpine pull fails:

   ```bash
   FLEET_DOCKER_INTEGRATION_IMAGE=busybox:latest python3 -m pytest tests/test_fleet_docker_integration.py -v --tb=short
   ```

4. ** Success criteria:** `test_fleet_runs_docker_container_echo` is **PASSED** (not skipped). It performs a real `docker run` via Fleet’s job runner (`POST /v1/jobs` → `runner.spawn`).

5. ** If skipped:** Print why (`docker` missing vs `docker info` failing). Suggest `groups`, `sg docker`, or fixing Docker socket access — do not claim success.

6. ** Do not** edit `.cursor/plans/*.plan.md`. Only report pytest output and exit code.

---

## One-liner (human)

```bash
cd /path/to/forge-fleet && python3 -m pytest tests/test_fleet_docker_integration.py -v --tb=short
```

Expect **1 passed** when Docker works; **1 skipped** when `docker info` fails from that shell.
