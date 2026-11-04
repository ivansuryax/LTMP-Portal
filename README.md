# 2026-10-13 corrections: secure reassignment / booking

See [SECURE_ASSIGNMENT_AND_BOOKING_GUIDE_TAMIL.md](SECURE_ASSIGNMENT_AND_BOOKING_GUIDE_TAMIL.md) and [RELEASE_PERMISSIONS_BOOKING.md](RELEASE_PERMISSIONS_BOOKING.md) for Trainer 403 restrictions, Manager permissions, Admin 409 override, Daily Tracker approvals and safe upgrade. Existing data retained.


## October 2026 unified project workflow (new)

**LeSuccess + Vendor + Freelancer** all support internal Trainer My Projects, in-app assignment notifications, Daily Training Updates, reviewer approvals, and approved-day dashboard metrics. Read `UNIFIED_PROJECTS_GUIDE_TAMIL.md` for workflow details and `SAFE_UPGRADE_MAC_TAMIL.md` before upgrading an existing PostgreSQL installation. The new `external_training_updates` table is additive and preserves original project rows. **Do not run `docker compose down -v` or overwrite `.env`.**

Tested: 46 backend tests, Chromium legacy-shell workflow for LeSuccess and both external project types. Frontend `npm run build` was not verified here because npm package installation timed out; run Docker build locally and check API health before claiming deployment success.

---

# LTMP Modern — Integrated Development Project

**Original LeSuccess LTMP UI + React (JavaScript) + Vite + Python FastAPI + PostgreSQL**

**October 13 release fix:** API no longer constructs PostgreSQL URLs by concatenating raw passwords; special characters such as `@` work. See [`FIX_502_AND_UPGRADE.md`](FIX_502_AND_UPGRADE.md) before updating an existing installation. **Keep the existing `.env` secret and database volume; do not replace your established database password with the sample one.**

This package is an integrated **development build**, produced from the user's original
HTML, Apps Script logic, and LTMP.xlsx spreadsheet. The full original page structure,
stylesheet, and JavaScript interactions are retained to prioritize visual compatibility.
React mounts the original application shell; the existing screen code is bridged to the
FastAPI RPC layer. It is **not** a visual rewrite into separate React components yet.

All **64 RPC names used by the supplied frontend** are routed through the backend.
**Major October 13 regression fixes** include numeric employee-ID authentication for
Team Leaders / Reporting Managers, Admin leave/tracker navigation, duplicate-day
prevention and reviewer mapping. See `AUTH_LOGIN_GUIDE.md` and `RELEASE_AUDIT.md`.
The majority of business workflows are implemented, with automated role/workflow tests.
**This is not a verified production-equivalent release**: see `MIGRATION_STATUS.md`.

## October 13 — Trainer Assignment / Daily Update fix

A Trainer who has a current **LeSuccess** college assignment now gets a persistent
**in-app Alerts notification**, a **My Colleges** entry, and an available
**Daily Update** form. The Admin assignment dialog selects from configured
college training categories and distinguishes current from completed/inactive
assignment states. Numeric IDs like `12345.0` normalize consistently.

Older current assignments receive a **repeat-safe** notification backfill when
the API starts. Empty Daily Update forms now display the exact signed-in
Employee ID and a useful assignment diagnosis rather than a bare empty page.
This is **in-app only**, not email/SMS/WhatsApp/push notifications. Vendor /
Freelance projects are **not** LeSuccess college Daily Update assignments.

**Read `ASSIGNMENT_DAILY_UPDATE_GUIDE_TAMIL.md` before upgrading**, especially
if your Mac Docker installation already contains employees, leave, KPI or
trainer assignment records. Preserve `.env` and the existing Postgres volume.

Validation: **40 backend regression tests passed** and the Chromium browser
Admin create college → assign → Trainer alert → Daily Update submit test passed
using a disposable database. Mac live deployment and latest Vite production
build still need validation on your machine.

## First run — simplest method (no manual integration of phases)

**Prerequisite:** Install and start Docker Desktop. Keep this project in a private folder.

### Windows

Open PowerShell in the extracted project folder, then run:

```powershell
.\start.ps1
```

If scripts are blocked, use a one-process override (does not change system policy):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start.ps1
```

### Mac / Linux

```bash
./start.sh
```

If `.env` does not already exist, these scripts generate a local random database password and start the three
Docker services. On the very first startup, FastAPI imports `imports/LTMP.xlsx` into
PostgreSQL automatically. Subsequent starts **do not overwrite existing data**.

Open: **http://localhost:5173**

Login using a valid, active account already present in your workbook. No default
credentials are created. **Change imported legacy credentials before any live usage.**

> The private package contains `imports/LTMP.xlsx`, including legacy plaintext
> credentials and other personal data. Treat the ZIP and extracted project as confidential.
> Do not publish it or check it into Git.

## Stopping and restarting

```bash
docker compose stop
docker compose start
```

Stopping or restarting preserves PostgreSQL volume data. `docker compose down` also
preserves data by default, but **`docker compose down -v` destroys the database**.

### If something doesn't start

```bash
docker compose ps
docker compose logs --tail=100 api
docker compose logs --tail=100 web
```

Your browser should use http://localhost:5173. API documentation (local API container)
is available by `docker compose exec api ...`, or set up a local backend as below.

## Local development (without Docker)

A development-only SQLite database can be used for backend tests and API debugging:

```bash
cd backend
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
export DATABASE_URL='sqlite+pysqlite:///./ltmp-dev.db' # macOS/Linux only
python scripts/import_excel.py --file ../imports/LTMP.xlsx --if-empty
uvicorn app.main:app --reload --port 8000
```

For Windows PowerShell replace `export ...` with:

```powershell
$env:DATABASE_URL='sqlite+pysqlite:///./ltmp-dev.db'
```

Open another terminal:

```bash
cd frontend
npm install
npm run dev
```

`http://localhost:5173` has a Vite proxy for `/api` to port 8000. The production
Docker web image runs Nginx, which proxies `/api` to the FastAPI container.

## Fixes for previous login failures

The old importer stored numeric Excel employee IDs as `12999.0`; this release
normalizes IDs and repairs existing references without resetting the DB.
**All 59 active accounts from the 119-user supplied workbook were verified to
log in**, across all four roles. The other 60 users are inactive in the source
workbook; their logins are intentionally rejected.
See `AUTH_LOGIN_GUIDE.md` for precise upgrade/diagnostic steps.

## How everything is integrated

```text
Browser http://localhost:5173
    |
    +-- React mounting the original LTMP HTML/CSS/JS
    |      `callServer('submitDailyActivity', payload)`
    |                    |
    |                    v
    +-- /api/rpc/{method} -- FastAPI + session cookie
                               |
                               v
                        Workflow validation
                               |
                               v
                       PostgreSQL transactions
```

No separate merging, copying individual phase files, or Google Apps Script deployment
is required. The supplied workbook is imported into a standalone database; changes
made in LTMP Modern do **not** automatically sync back to the original Google Sheet.

## Code structure

```text
frontend/
  src/main.jsx            React shell preserving the LTMP markup
  src/original-shell.html  Original UI structure
  src/original.css         Original UI styling
  public/legacy.js        Original LTMP UI behavior, FastAPI call bridge
  src/api.js              Promise wrapper for backend RPC
backend/
  app/main.py             FastAPI, authentication, core resource routes
  app/workflows.py        Trainer, daily log, leave, KPI, activity, alerts
  app/queries.py          Dashboard, roster, reports, project read models
  app/db.py               SQLAlchemy model and connections
  scripts/import_excel.py Source workbook -> database import
  tests/                 Workflow, role and integration tests
imports/LTMP.xlsx         PRIVATE user-supplied source data (private ZIP only)
docker-compose.yml        PostgreSQL + API + web
start.sh / start.ps1       One-command setup
MIGRATION_STATUS.md       What is verified and what remains
```

## Testing

```bash
cd backend
pytest -q
```

The included tests (40 passing) exercise auth, role gates, trainer assignments, daily update
and syllabus approval, leave, activity tracker approval, KPI review/unlock,
user/project operations, and first-run workbook import behavior. Use staging data
from a production-like export to validate all role screens and performance before rollout.

## Important limits

- Google Drive attendance-sheet template cloning is **not implemented** (requires
  credentials and approval); manually provided attendance-sheet links are supported.
- The current PostgreSQL `source_rows` JSON table is an interim compatibility layer
  with indexes by sheet and row; high-volume modules should be normalized before load testing.
- Pixel-perfect parity was not browser-verified; the original markup and CSS were preserved.
- Chromium legacy HTML/CSS/JS shell and real API/SQL workflows were smoke-tested
  across Admin, Reporting Manager, Team Leader and Trainer.
- Frontend production build was **not** verified in this runtime because npm packages
  were unavailable offline. Run `npm install && npm run build` where network is allowed.
- Not yet certified for production: browser E2E tests, password reset/admin access recovery,
  audit/compliance review, concurrent update races, import data reconciliation,
  security audit, TLS/domain configuration, DB backups, and load tests.

**Run privately, test with representative business records and every role, then plan
production deployment only after the above checks pass.**

## Leave Management visibility fix (October 13, 2026)

Admin can now open **Leave Management** from the navigation and monitor **all**
leave requests, including `Pending` rows. The Admin dashboard also shows a
**Pending Leave Requests** counter; clicking it opens the full leave list.
The existing **Approved Leave Days** dashboard counter continues to show only
approved leave days overlapping running assignments in the current month.

**Who approves?** A Trainer's submitted leave is assigned to their recorded
Team Leader (the direct reporting manager). Only that exact assigned manager
may approve or reject. Admin has visibility of all requests but cannot approve
requests assigned to another manager. The Leave Management list displays
**Assigned Approver** so routing is transparent.

**Updating a previous LTMP-modern install without losing data:**

1. Take a PostgreSQL backup before changes (`docker compose exec -T db pg_dump -U ltmp ltmp > ltmp-backup.sql`) using your existing project terminal.
2. Extract this updated package **over the existing `LTMP-modern` folder**, keeping its existing `.env` file and Compose project directory unchanged. Alternatively, copy only `frontend/public/legacy.js` plus the updated docs/tests.
3. Run `docker compose up -d --build` in that same folder. Do not use `docker compose down -v` and do not delete the `pgdata` volume.
4. Open the app and use **Admin → Leave Management**. Pending requests should appear if they were successfully submitted to this same database.
5. If a request is absent from both **Trainer → My Leave Requests** and **Admin → Leave Management**, confirm the original submit returned a success message and verify both sessions use the same deployment/database.

No database migration is required for this UI fix. Existing leave records are not changed.

## Release QA

Run `cd backend && python -m pytest -q` (25 passing tests). Optional Chromium
checks: `cd backend && python tests/browser_smoke.py` (mocked API) and
`python tests/browser_backend_e2e.py` (real FastAPI/TestClient + temporary DB,
Playwright and system Chromium required). Full details: `VERIFY.md` and
`RELEASE_AUDIT.md`.


## Free cloud deployment: Render + Neon (October 2026)

**Deployment package:** this same complete LTMP app can be deployed to **one Render Free Docker Web Service** (React + FastAPI on the same HTTPS domain) and **Neon Free PostgreSQL**.

1. Start with **`deploy/README_RENDER_NEON_TAMIL.md`** — complete Tamil-English, click-by-click setup and security notes.
2. `Dockerfile.render` builds React and serves it through FastAPI; it does **not** replace local `docker-compose.yml`.
3. `render.yaml` creates one Free Render Web Service; configure the **Neon secret DATABASE_URL** in Render, never in Git.
4. Migrate existing PostgreSQL data to a brand-new empty Neon DB using `bash deploy/migrate_mac_db_to_neon.sh`, **before** deploying Render. Private backups go in ignored `backups/`.
5. Back up Neon later using `bash deploy/backup_neon.sh`. Do not publish original `LTMP.xlsx`, `.env`, `.dump`, or `.sql`.

This is a **pilot deployment configuration**, not a completed online deployment or production certification. See `deploy/DEPLOYMENT_CHANGELOG.md`.
