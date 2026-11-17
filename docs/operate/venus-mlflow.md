# Venus — MLflow

Tracking server for Forge jobs. Browsers sign in with Google through **`https://login.forgedc.net`**. Jobs use HTTP basic auth and do not need a browser cookie.

## Boundary

- Host: Venus (`FW3GSG3`), user `forge`. The process is a systemd **user** service, `forge-mlflow.service`, not the broken Docker content store.
- Runtime: uv CPython 3.12, MLflow 2.22, `--app-name basic-auth`, SQLite at `~/.local/share/forge-mlflow/mlflow.db`, artifacts beside it. Listen: `127.0.0.1:5050`.
- Auth gate: `forge-auth-gate.service` on `127.0.0.1:5051` (`FORGE_AUTH_GATE_MODE=mlflow`). Cookieless browsers redirect to `login.forgedc.net`. After Google accepts an active Lenses tenant, the gate creates an MLflow user for that email and signs the browser in. `Authorization: Basic` from jobs is proxied unchanged. The gate reads the MLflow admin account from `FORGE_AUTH_GATE_MLFLOW_AUTH_INI`.
- Public name: **`https://mlflow.forgedc.net`**. Cloudflare tunnel Venus `fb689622-f9f8-44ce-a846-5f4b72ed2c6a` (Windows `cloudflared`) sends that hostname to `http://127.0.0.1:5051`.
- Secrets stay in `/home/forge/deploy/mlflow/.env` (mode 0600). Do not commit that file.

## Forge consumers

```bash
export MLFLOW_TRACKING_URI=https://mlflow.forgedc.net
export MLFLOW_TRACKING_USERNAME=forge
export MLFLOW_TRACKING_PASSWORD=…   # from the Venus .env, not from git
```

A tracking client can list or create experiments with those variables and no browser cookie.

## Ingress

```bash
export CF_TUNNEL_ID=fb689622-f9f8-44ce-a846-5f4b72ed2c6a
export CF_ORIGIN_SERVICE=http://127.0.0.1:5051
deploy/mlflow/scripts/apply-cf-mlflow-tunnel.sh
```

Confirm Windows `http://127.0.0.1:5051/_forge_auth/health` answers before changing DNS. The connector is not inside WSL.
