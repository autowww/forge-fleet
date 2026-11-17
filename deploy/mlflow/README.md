# MLflow on Venus

Pinned `ghcr.io/mlflow/mlflow:v2.18.0` with Postgres and basic-auth. Public URL: **`https://mlflow.forgedc.net`** (auth gate on loopback `:5051`, server on `:5050`).

## Install on Venus

```bash
cd deploy/mlflow
cp .env.example .env
# set MLFLOW_POSTGRES_PASSWORD, MLFLOW_ADMIN_PASSWORD, tracking user secrets
./scripts/rollout-mlflow.sh
```

Configure the auth gate (`deploy/forge-auth-gate`) with `FORGE_AUTH_GATE_MODE=mlflow`, port `5051`, upstream `http://127.0.0.1:5050`.

## Cloudflare

```bash
export CF_TUNNEL_ID=fb689622-f9f8-44ce-a846-5f4b72ed2c6a
deploy/mlflow/scripts/apply-cf-mlflow-tunnel.sh
```

## Forge consumers

```bash
export MLFLOW_TRACKING_URI=https://mlflow.forgedc.net
export MLFLOW_TRACKING_USERNAME=forge
export MLFLOW_TRACKING_PASSWORD=…
```

Browser users sign in with Google via `login.forgedc.net`. Programmatic clients send HTTP Basic (or Bearer where applicable) and bypass the Google redirect.