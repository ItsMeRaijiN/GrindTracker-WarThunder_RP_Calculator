# GrindTracker

GrindTracker is a War Thunder research planner: browse a nation's vehicle tree, mark progress, and estimate the battles and time needed to reach a selected vehicle.

## Stack

- Web: React 19, TypeScript 7, Vite 8, pnpm 11, modern CSS without a component framework.
- API: Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, Argon2id, SQLite by default (PostgreSQL-ready URL).
- Quality: Ruff, pytest, Vitest, TypeScript strict mode, dependency audits, and production builds in GitHub Actions.

### API

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python cli.py init-db
python cli.py sync-datamine --dry-run
python cli.py sync-datamine
python -m uvicorn app:app --reload --host 127.0.0.1 --port 8000
```
API documentation is generated at `http://127.0.0.1:8000/docs`.

For schema development:

```powershell
python -m alembic revision --autogenerate -m "describe the schema change"
python -m alembic upgrade head
```

To use an existing local checkout:

```powershell
python cli.py sync-datamine --source C:\path\to\War-Thunder-Datamine
```

### Web

```powershell
cd frontend
Copy-Item .env.example .env
corepack prepare pnpm@11.7.0 --activate
pnpm install
pnpm dev
```

## Verification

```powershell
cd backend
python -m ruff check --no-cache .
python -m ruff format --check --no-cache .
python -m pip_audit -r requirements-dev.txt
python -m pytest

cd ../frontend
pnpm audit --prod --audit-level=high
pnpm test
pnpm run build
```

## Research model

Select both the target and the vehicle used in battle. Its `expMul` value from `wpcost.blkx` is used as the RP
multiplier. The calculator also applies the official rank-difference efficiency table and the direct predecessor
bonus: 130% in Arcade, 110% in Realistic and Simulator. Cascade forecasts calculate efficiency separately for every
vehicle on the route instead of dividing the entire route by one global average.

- **Observed modification RP** from the battle report already includes the research vehicle, account, talisman,
  booster, and skill multipliers. The game shows it before research efficiency, so GrindTracker can apply the correct
  target-specific value without double counting.
- **Base RP** applies the research vehicle multiplier and adds premium account, talisman, booster, and skill
  percentages to the same base amount before research efficiency. These bonuses are not multiplied by one another.

Do not paste Vehicle Research RP that has already been applied to the currently selected target into the observed
field; that number already contains the target's research-efficiency multiplier.

Mechanics reference: [War Thunder Wiki — Basic economy](https://wiki.warthunder.com/mechanics/basic_economy).

## Important limitations

- Datamine snapshots are unofficial community data and may briefly lag behind a live game update.
- Mission-only datamine copies (`nt_`, `_race`, `_killstreak`, and unavailable `_event` variants) are excluded from
  the player catalog. Persistent event rewards remain available.
- Estimates are projections, not a reproduction of Gaijin's battle reward service. Modification-tier bonuses, daily
  research bonuses, and mixed line-up contribution weights across several vehicles are not modeled yet.
- The `1 GE ≈ 45 RP` conversion is shown as an approximation.
