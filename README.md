# Kickflip — Debug Log Enabler

A self-service web tool that lets teams temporarily allow debug logs into Datadog for a specific application (CAR ID) during an active incident.

Debug logs are normally dropped at the Observability Pipelines layer. Kickflip modifies the drop filter to exclude a CAR ID for a fixed window (default: 10 minutes), then automatically reverts the change when the window closes.

---

## How it works

1. A team member opens the UI, enters their **CAR ID** and an active **ServiceNow incident number** (SEV2 or higher required)
2. Kickflip validates the incident against ServiceNow
3. The Observability Pipelines filter is updated from:
   ```
   level:debug
   ```
   to:
   ```
   level:debug AND NOT (car_id:1234)
   ```
4. After the grant window expires, the filter is automatically reverted — even across server restarts

Multiple CAR IDs can be active simultaneously. The filter expression is rebuilt each time a grant is added or removed.

---

## Running locally

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
# Install dependencies
pip install -r requirements.txt

# Copy and fill in environment variables
cp .env.example .env

# Start the server
uvicorn app.main:app --reload --reload-exclude '*.db' --port 8123
```

Open **http://localhost:8123**

Both Datadog and ServiceNow integrations run in **stub mode** when their env vars are absent — any `INC…` number is accepted and pipeline updates are skipped. This lets you run and test the UI without any real credentials.

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `DD_API_KEY` | Yes | Datadog API key |
| `DD_APP_KEY` | Yes | Datadog application key (needs `observability_pipelines_write` scope) |
| `DD_SITE` | No | Datadog site (default: `datadoghq.com`) |
| `DD_PIPELINE_IDS` | Yes | Comma-separated OP pipeline IDs to update |
| `DD_FILTER_PROCESSOR_ID` | No | ID of the debug drop processor in your pipeline (default: `drop-debug`) |
| `SN_INSTANCE` | Yes | ServiceNow instance hostname e.g. `mycompany.service-now.com` |
| `SN_USER` | Yes | ServiceNow username |
| `SN_PASS` | Yes | ServiceNow password |
| `SN_MIN_SEVERITY` | No | Minimum incident priority to accept (default: `2` = SEV2+) |
| `GRANT_DURATION_SECONDS` | No | How long a debug grant lasts in seconds (default: `600`) |

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

---

## Project layout

```
app/
  main.py          — FastAPI app, startup/shutdown lifecycle
  config.py        — All settings via env vars (pydantic-settings)
  database.py      — Async SQLAlchemy + SQLite
  models.py        — Grant model
  scheduler.py     — APScheduler with SQLite jobstore (reverts survive restarts)
  tasks.py         — revert_grant() and startup recovery sweep
  clients/
    datadog.py     — Observability Pipelines API client
    servicenow.py  — ServiceNow incident validation
  routers/
    grants.py      — REST API: GET / POST / DELETE /api/grants
static/
  index.html       — Single-page UI (Tailwind + Alpine.js)
```

---

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/grants` | List recent grants (active + history) |
| `POST` | `/api/grants` | Create a new debug grant |
| `DELETE` | `/api/grants/{id}` | Manually revoke an active grant |

Interactive docs available at **http://localhost:8123/docs**

---

## Grant lifecycle

```
created → active (filter pushed to pipelines)
              ↓ timer expires or manual revoke
           reverted (filter removed from pipelines)
```

Grants that expired while the server was offline are cleaned up and the filter corrected on next startup. A 30-second background sweep catches any grants the scheduler missed while the app was running.
