# Granite Market Studio host edge plane

Session-bound **TradingView** harvest runs on the **Granite Fleet host OS**, not inside `market-app`.

**Workstation-only (not Granite):** IB Gateway (read-only `:4001`), Flex Playwright ensure (operator Edge).

## Components

| Component | Install | Loopback |
|-----------|---------|----------|
| Dedicated Edge + CDP | `forge-market/scripts/granite/install-granite-edge-plane.sh` | `:9222` |
| Daily scheduler | `forge-fleet/scripts/install-granite-market-scheduler.sh` | calls app gateway |

Profile path default: `~/.config/microsoft-edge-granite-market` — **never** copy the laptop operator Edge tree.

## Container connectivity

`compose.granite.yaml` sets:

- `FORGE_MARKET_CDP_URL=http://host.docker.internal:9222` — TradingView harvest from container attach to host CDP
- Flex HTTP tokens in `.env` — unattended Flex sync only (no Gateway)

## First-time login

1. Start Edge unit: `systemctl --user start forge-market-granite-edge.service`
2. Open Fleet CDP stream for the Granite profile and sign into TradingView
3. Set Flex/LLM secrets in `deploy/forge-market-studio/.env` and restart `market-app`

**IB Gateway:** install and log in on the **analyst laptop** (`~/Jts/ibgateway`, Read-Only API `:4001`). Sync while Studio is online locally or via `--ui-remote` (Gateway routes proxy to local `:9792`).

**Flex Client Portal setup:** use Studio Flex ensure on the **laptop** operator Edge.

## Reference

- ADR v2: `forge-market/docs/design/edge-sync-cloud-adr.md`
- Cutover: [granite-market-studio-cutover.md](granite-market-studio-cutover.md)
