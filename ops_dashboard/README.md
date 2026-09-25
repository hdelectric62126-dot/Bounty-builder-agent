# Central Operations

A private, read-only operations command center for the user's automation stack.

## Connected surfaces

- **Bounty Builder** — public `/health` endpoint including database, worker, cloud-budget and opportunity/revenue counters.
- **Alpaca Trading Agent** — public `/health` plus its authenticated read-only `/api/dashboard?days=7` feed.
- **Opportunity Scout** — cloud health endpoint.
- **1099 Business OS** — GitHub source/CI state plus an optional signed runtime heartbeat.
- **Native Mind / LocalMind** — optional signed local heartbeat; the dashboard does not receive command-execution privileges.
- **License Navigator / Scraper** — optional signed local heartbeat.
- **GitHub source + CI** — cached source state for public repositories; private repositories can optionally use a read-only `GITHUB_TOKEN`.

## Security

- The UI is protected by `OPS_ACCESS_TOKEN`.
- Local heartbeat senders use a separate `OPS_HEARTBEAT_TOKEN`.
- The downstream integrations are read-only.
- No downstream mutation endpoint is exposed.
- Secrets are server-side environment variables and are never placed in the dashboard HTML.
- Security headers disable framing, browser geolocation, camera and microphone.
- The status database is backed up once per UTC day.

## Railway environment

Required:

- `OPS_ACCESS_TOKEN` — minimum 24 characters.
- `OPS_HEARTBEAT_TOKEN` — minimum 24 characters.
- `OPS_DB_PATH=/data/ops_dashboard.db`
- `OPS_BACKUP_DIR=/data/backups`

Recommended:

- `ALPACA_DASHBOARD_READ_TOKEN` — reference the existing Alpaca service's read-only token.
- `ALPACA_HEALTH_URL` and `ALPACA_DETAIL_URL` — use Railway private networking when Central Operations is deployed in the same project.
- `GITHUB_TOKEN` — optional read-only token if private repository source status is desired.

The service needs a persistent Railway volume mounted at `/data`.
