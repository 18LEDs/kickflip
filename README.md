# Kickflip — Debug Log Enabler

A self-service web tool that lets teams temporarily allow debug logs into Datadog for a specific application (CAR ID) during an active incident.

Debug logs are normally dropped at two layers: the Observability Pipelines Worker filter and the log index exclusion filter. Kickflip modifies both for the granted CAR ID, then automatically reverts both when the grant window closes.

---

## How it works

1. A team member opens the UI, enters their **CAR ID** and an active **ServiceNow incident number** (SEV2 or higher required)
2. Kickflip validates the incident against ServiceNow
3. Two filters are updated simultaneously:

   **Observability Pipelines** (ingestion layer):
   ```
   level:debug  →  level:debug AND NOT (car_id:1234)
   ```
   **Log Index exclusion filter** (indexing layer):
   ```
   status:debug  →  status:debug AND NOT (car_id:1234)
   ```

4. After the grant window expires the filters are automatically reverted — even across pod/server restarts

Multiple CAR IDs can be active simultaneously. Both filter expressions are rebuilt each time a grant is added or removed.

---

## Running locally

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and fill in environment variables
cp .env.example .env

# Start the server
uvicorn app.main:app --reload --reload-exclude '*.db' --port 8123
```

Open **http://localhost:8123**

Both Datadog and ServiceNow integrations run in **stub mode** when their env vars are absent — any `INC…` number is accepted and all API calls are skipped. This lets you run and test the UI without any real credentials.

---

## Running with Docker

```bash
# Build and run (uses docker-compose.yml)
docker compose up --build
```

Open **http://localhost:8000**

The SQLite database is stored in a named Docker volume (`kickflip-data`) so grants persist across container restarts.

---

## Deploying to k3s

### 1. Build and push the image

```bash
docker build -t your-registry/kickflip:latest .
docker push your-registry/kickflip:latest
```

### 2. Configure

**`k8s/secret.yaml`** — fill in base64-encoded credentials before applying:
```bash
echo -n 'your-value' | base64
```

**`k8s/configmap.yaml`** — fill in your pipeline IDs, index name, and ServiceNow instance hostname.

**`k8s/deployment.yaml`** — update the `image:` field to point to your registry.

### 3. Deploy

```bash
kubectl apply -f k8s/
```

k3s's built-in Traefik handles ingress. Update the hostname in `k8s/ingress.yaml` to match your DNS or local hostname.

> **Note:** `replicas: 1` and `strategy: Recreate` are intentional — SQLite cannot handle concurrent writers. If you need HA in the future, set `DATABASE_URL` to a Postgres connection string.

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `DD_API_KEY` | Yes | Datadog API key |
| `DD_APP_KEY` | Yes | Datadog application key (needs `observability_pipelines_write` scope) |
| `DD_SITE` | No | Datadog site (default: `datadoghq.com`) |
| `DD_PIPELINE_IDS` | Yes | Comma-separated OP pipeline IDs to update |
| `DD_FILTER_PROCESSOR_ID` | No | ID of the debug drop processor in your pipeline config (default: `drop-debug`) |
| `DD_INDEX_NAME` | Yes | Name of the shared log index whose exclusion filter is updated |
| `SN_INSTANCE` | Yes | ServiceNow instance hostname e.g. `mycompany.service-now.com` |
| `SN_USER` | Yes | ServiceNow username |
| `SN_PASS` | Yes | ServiceNow password |
| `SN_MIN_SEVERITY` | No | Minimum incident priority to accept (default: `2` = SEV2+) |
| `GRANT_DURATION_SECONDS` | No | How long a debug grant lasts in seconds (default: `600`) |
| `DATABASE_URL` | No | SQLAlchemy async DB URL (default: `sqlite+aiosqlite:///./grants.db`) |

### Finding your pipeline IDs

```bash
curl -X GET "https://api.datadoghq.com/api/v2/observability_pipelines" \
  -H "DD-API-KEY: <your_api_key>" \
  -H "DD-APPLICATION-KEY: <your_app_key>"
```

### Finding your filter processor ID

```bash
curl -X GET "https://api.datadoghq.com/api/v2/observability_pipelines/<pipeline_id>" \
  -H "DD-API-KEY: <your_api_key>" \
  -H "DD-APPLICATION-KEY: <your_app_key>"
```

Look for the processor whose `include` field starts with `level:debug`. Its `id` is your `DD_FILTER_PROCESSOR_ID`.

### Finding your index name

In Datadog: **Logs → Configuration → Indexes**. Look for the index with an exclusion filter containing `status:debug`. That index's name is your `DD_INDEX_NAME`.

---

## Project layout

```
app/
  main.py              — FastAPI app, startup/shutdown lifecycle, /health endpoint
  config.py            — All settings via env vars (pydantic-settings)
  database.py          — Async SQLAlchemy + SQLite
  models.py            — Grant model
  scheduler.py         — APScheduler with SQLite jobstore (reverts survive restarts)
                         Includes a 30s interval sweep as a safety net for missed reverts
  tasks.py             — revert_grant() and startup recovery sweep
  clients/
    datadog.py         — Observability Pipelines filter client
    datadog_index.py   — Log index exclusion filter client
    servicenow.py      — ServiceNow incident validation
  routers/
    grants.py          — REST API: GET / POST / DELETE /api/grants
static/
  index.html           — Single-page UI (Tailwind + Alpine.js)
k8s/
  namespace.yaml       — kickflip namespace
  secret.yaml          — Credential template (DD API keys, SN credentials)
  configmap.yaml       — Non-sensitive configuration
  pvc.yaml             — 1Gi PVC for SQLite (k3s local-path provisioner)
  deployment.yaml      — Single-replica deployment with probes and resource limits
  service.yaml         — ClusterIP service on port 80
  ingress.yaml         — Optional Traefik ingress
```

---

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/grants` | List recent grants (active + history) |
| `POST` | `/api/grants` | Create a new debug grant |
| `DELETE` | `/api/grants/{id}` | Manually revoke an active grant |
| `GET` | `/health` | Healthcheck — returns `{"status": "ok"}` |

Interactive docs: **http://localhost:8123/docs**

---

## Grant lifecycle

```
submitted → [SN incident validated]
                ↓
            active  (both filters updated — pipeline + index)
                ↓  timer expires (default 10m) or manual revoke
            reverted  (both filters restored)
```

Grants that expired while the server was offline are cleaned up on next startup. A 30-second background sweep also catches any grants the scheduler missed while the app was running.
