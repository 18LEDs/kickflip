# Kickflip

Debug log enabler for Datadog Observability Pipelines.

## Git workflow

Always work on a feature branch — never commit directly to `main`.

```bash
git checkout -b feature/short-description
# make changes
git push -u origin feature/short-description
gh pr create
```

Branch naming: `feature/`, `fix/`, or `chore/` prefix followed by a short kebab-case description.

## Running locally

```bash
uvicorn app.main:app --reload
```

App runs on http://localhost:8123

## Environment variables

Copy `.env.example` to `.env` and fill in values. Both Datadog and ServiceNow integrations degrade gracefully when env vars are absent (stub mode).

| Variable | Description |
|---|---|
| `DD_API_KEY` | Datadog API key |
| `DD_APP_KEY` | Datadog application key |
| `DD_PIPELINE_IDS` | Comma-separated OP pipeline IDs |
| `DD_FILTER_PROCESSOR_ID` | Processor ID holding the debug drop filter (default: `drop-debug`) |
| `SN_INSTANCE` | ServiceNow instance hostname |
| `SN_USER` | ServiceNow username |
| `SN_PASS` | ServiceNow password |
| `GRANT_DURATION_SECONDS` | How long a debug grant lasts (default: 600) |

## Project layout

```
app/
  main.py          — FastAPI app entry point
  config.py        — Settings (pydantic-settings)
  database.py      — Async SQLAlchemy + SQLite
  models.py        — Grant ORM model
  scheduler.py     — APScheduler (SQLite jobstore, survives restarts)
  tasks.py         — revert_grant() + startup recovery
  clients/
    datadog.py     — Observability Pipelines API client
    servicenow.py  — ServiceNow incident validation
  routers/
    grants.py      — REST API: GET/POST/DELETE /api/grants
static/
  index.html       — Single-page UI (Tailwind + Alpine.js)
```
