# Development

[Project overview](../README.md)

Requirements: Node.js 22.19.0, pnpm 11.7.0, and Python 3.12 for the backend.
Commands below use PowerShell and start from the repository root unless stated otherwise.

## Standalone frontend

```powershell
cd frontend
corepack prepare pnpm@11.7.0 --activate
pnpm install --frozen-lockfile
pnpm run build:pages
pnpm run preview:pages
```

Open [the preview](http://localhost:5173/GrindTracker-WarThunder_RP_Calculator/).
This build uses the bundled catalog and browser-local progress. It requires no backend.

## Frontend with FastAPI

Start the backend:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python cli.py init-db
python cli.py sync-datamine
python -m uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

API documentation: [localhost:8000/docs](http://localhost:8000/docs).

In a second terminal, start the frontend with its default API configuration:

```powershell
cd frontend
corepack prepare pnpm@11.7.0 --activate
pnpm install --frozen-lockfile
pnpm dev
```

`VITE_DATA_MODE=api` is the default. An empty `VITE_API_BASE_URL` uses Vite's `/api` proxy to port 8000.
For overrides, copy `frontend/.env.example` to `frontend/.env`. The `pages` build selects static mode through `.env.pages`.

## Tests and builds

Frontend:

```powershell
cd frontend
pnpm test
pnpm run build
pnpm run build:pages
```

Backend, with its virtual environment activated:

```powershell
cd backend
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

CI runs these checks and audits dependencies with `pnpm audit --prod --audit-level=high` and
`python -m pip_audit -r requirements-dev.txt`.

## Refresh the Pages catalog

With the backend virtual environment activated:

```powershell
cd backend
python cli.py sync-datamine --dry-run --export instance/catalog-source.json
python static_catalog.py instance/catalog-source.json ../frontend/public/data/catalog.json
```

The exporter imports data into an isolated in-memory database. It generates stable vehicle IDs and includes source
metadata. Run the tests and Pages build before committing the updated catalog.

After changing calculator behavior, regenerate its shared test fixture from `backend`, then run both test suites:

```powershell
$env:PYTHONPATH='.'
python tests/calculator_contract.py
```

## Deployment

GitHub Pages uses **Settings > Pages > Source > GitHub Actions**. The deployment workflow publishes `frontend/dist`
after successful CI on `main`; it also supports manual dispatch. Static deployment needs no `API_BASE_URL` variable.

API hosting requires a persistent `DATABASE_URL`, `ENVIRONMENT=production`, a random `SECRET_KEY` of at least
32 characters, appropriate `TRUSTED_HOSTS` and `CORS_ORIGINS`, and `SESSION_COOKIE_SECURE=true`. Configure these as
process environment variables; the backend does not load `.env` automatically. Apply migrations with
`python cli.py init-db`, then set `MIGRATE_ON_STARTUP=false` before serving traffic.

For account synchronization, serve the frontend and API under the same origin, route `/api` to FastAPI, and build
the frontend with `VITE_DATA_MODE=api` and `VITE_AUTH_ENABLED=true`.
