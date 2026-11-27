# MLflow on Mercury

Tracking server for Forge jobs. Browsers sign in with Google through **`https://login.forgedc.net`**. Jobs use HTTP basic auth and do not need a browser cookie.

## Boundary

- Host: Mercury, user `leo`. The process is a systemd **user** service, `forge-mlflow.service`. Venus (`FW3GSG3`) no longer runs it.
- Runtime: uv CPython 3.12, MLflow 2.22, `--app-name basic-auth`, SQLite at `~/.local/share/forge-mlflow/mlflow.db`, artifacts beside it. Listen: `127.0.0.1:5050`. SQLAlchemy stays on 2.0 (`mlflow[auth]==2.22.0`).
- Auth gate: `forge-mlflow-gate.service` on `127.0.0.1:5051` (`FORGE_AUTH_GATE_MODE=mlflow`). This is a separate unit from Mercury's Open WebUI `forge-auth-gate.service` on `:19809`. Cookieless browsers redirect to `login.forgedc.net`. After Google accepts an active Lenses tenant, the gate creates an MLflow user for that email and signs the browser in. `Authorization: Basic` from jobs is proxied unchanged. The gate reads the MLflow admin account from `FORGE_AUTH_GATE_MLFLOW_AUTH_INI`.
- Public name: **`https://mlflow.forgedc.net`**. Cloudflare tunnel Mercury `6e783b10-a38e-4715-a57e-f55c649fcba2` sends that hostname to `http://127.0.0.1:5051`.
- On Mercury, Forge MLX uses `MLFLOW_TRACKING_URI=http://127.0.0.1:5050`. Other hosts keep the public name.
- Secrets stay in `~/.local/share/forge-mlflow/` and `~/.config/forge-mlflow-gate/gate.env` (mode 0600). Do not commit those files.

## Forge consumers

```bash
export MLFLOW_TRACKING_URI=https://mlflow.forgedc.net
export MLFLOW_TRACKING_USERNAME=forge
export MLFLOW_TRACKING_PASSWORD=…   # from the Mercury MLflow basic-auth file, not from git
```

A tracking client can list or create experiments with those variables and no browser cookie.

## Ingress

```bash
export CF_TUNNEL_ID=6e783b10-a38e-4715-a57e-f55c649fcba2
export CF_ORIGIN_SERVICE=http://127.0.0.1:5051
deploy/mlflow/scripts/apply-cf-mlflow-tunnel.sh
```

Confirm Mercury `http://127.0.0.1:5051/_forge_auth/health` answers before changing DNS.
