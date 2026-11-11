# Hire-Steward — Local Setup and Configuration Guide

**Product:** Hire-Steward / JobPilot  
**Platform:** Windows 10/11, macOS, Linux  
**Runtime:** Python 3.12+ with `uv` package manager, Node.js 18+ with `npm`  
**Database:** PostgreSQL 17.x  

---

## 1. Prerequisites

Before setting up Hire-Steward, verify the following are installed:
1. **Python 3.12 or higher:**
   ```bash
   python --version
   ```
2. **`uv` Package Manager (recommended):**
   ```bash
   uv --version
   ```
3. **Node.js (v18+) and npm:**
   ```bash
   node --version
   npm --version
   ```
4. **PostgreSQL 17.x:**
   Ensure PostgreSQL server is running locally on port 5432 with databases `jobpilot_workspace` (production workspace) and `jobpilot_test` (test runner).

---

## 2. Environment Configuration

Create or configure `.env` in the root repository directory:

```env
# Database Connections
DATABASE_URL=postgresql+psycopg://jobpilot:local_dev_only@127.0.0.1:5432/jobpilot_workspace
JOBPILOT_TEST_DATABASE_URL=postgresql+psycopg://jobpilot:local_dev_only@127.0.0.1:5432/jobpilot_test

# Evidence Storage Root
EVIDENCE_STORAGE_ROOT=C:\Users\<YourUser>\AppData\Local\HireSteward\workspace\evidence

# Background Services
ENABLE_BACKGROUND_SERVICES=true

# Python Path
PYTHONPATH=.
```

---

## 3. Database Initialization & Migrations

Run database migrations to bring the schema up to the latest head (`0010_background_tasks`):

```bash
uv run alembic upgrade head
```

Verify that 28 public tables are created in `jobpilot_workspace`:
```bash
uv run python -c "from sqlalchemy import create_engine, inspect; engine = create_engine('postgresql+psycopg://jobpilot:local_dev_only@127.0.0.1:5432/jobpilot_workspace'); print(len(inspect(engine).get_table_names('public')))"
# Output: 28
```

---

## 4. Building the Frontend

Build the React 18 + TypeScript strict + Vite production bundle:

```bash
npm --prefix frontend run build
```

The compiled assets will be placed in `frontend/dist/` and automatically served by FastAPI with cache-busting headers.

---

## 5. Starting the Application

Start the local FastAPI server:

```bash
uv run uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Open your browser and navigate to:
```
http://127.0.0.1:8000/
```
Or open the direct workbench URL:
```
http://127.0.0.1:8000/workbench
```

---

## 6. Running Automated Tests

### Fast Checks (Unit & Integration Tests):
```bash
uv run --locked pytest -m "not postgres" -q
```

### PostgreSQL Integration Tests:
```bash
uv run --locked pytest -m "postgres" -q
```

### Frontend Typecheck & Vitest:
```bash
npm --prefix frontend run typecheck
npm --prefix frontend test
```

### Browser Live Verification Probes:
```bash
node scripts/verify_live_native_scroll.js
node scripts/verify_all_13_views_live.js
```
