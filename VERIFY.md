# Verification — October 13, 2026

- Python backend tests in previous release: **25 passed** (`cd backend && python -m pytest -q`).
- Workbook import/auth: **19 sheets, 119 users**. Of these, **59 active**
  accepted their original credentials; **60 inactive** were correctly denied.
- Role classes with successful workbook logins: Admin, Reporting Manager,
  Team Leader, Trainer.
- Existing numeric `.0` usernames: idempotent, transactional repair test passed.
- Chromium original LTMP HTML/CSS/JS smoke: 4 roles passed using test RPCs.
- Chromium original LTMP UI with **real FastAPI TestClient/SQL**: trainer
  leave/tracker submission, Team Leader review, RM and Admin pages passed.
  Browser-to-Python test bridge used in place of actual network due policy.
- JavaScript syntax and Python compilation: passed.
- `npm install`/Vite build: unavailable (registry DNS EAI_AGAIN).
- Live Docker/PostgreSQL and production deployment: not tested (Docker absent).
- Reported original 63 failing Apps Script criteria: traced and selected
  critical paths repaired; not all recertified against a live app.

Read `RELEASE_AUDIT.md` for defects fixed and remaining production gates.

## October 13 PostgreSQL password connection repair
- Compose now passes `POSTGRES_PASSWORD` raw to the API and never concatenates it into a URI.
- `app/db.py` uses SQLAlchemy `URL.create()`, correctly quoting reserved characters.
- Added `tests/test_connection_config.py` for multiple special-character secrets, Compose service/env parity, SQLite backward compatibility and boot entrypoint behavior.
- Docker Compose/PostgreSQL **cannot be run in this environment** (Docker unavailable). Verify API health on the target Mac after preserving the current `.env` and volume.

- Repaired release: **34 passed** (including 9 database URL config/edge-case checks).
- NPM cache lacks React; Vite build not reproduced in this environment; prior Mac Docker logs show frontend build succeeded before this config patch.

### Assignment screenshot regression (October 13)

- `cd backend && python -m pytest -q` : 40/40 passed.
- `python backend/tests/browser_assignment_e2e.py` : Admin creates college, assigns Trainer, Trainer sees Alerts and My Colleges and submits Daily Training Update. Chromium + FastAPI + isolated SQL DB, passed.
- `python backend/tests/browser_backend_e2e.py` : four-role leave/tracker approval E2E, passed.
- The online Vite/Docker frontend build on the user's Mac needs local confirmation; `npm install --offline` was blocked here because the npm cache did not contain dependencies.
- On upgrade: preserve existing `.env` and database volume; startup performs an idempotent backfill of notifications for existing current assignments. Do not reset or wipe database.
