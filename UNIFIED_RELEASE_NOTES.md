# LTMP integrated all-project training — Release notes

**Date:** 13 October 2026 | **Stage:** integrated development release

### Delivered

- Existing LTMP React/JavaScript/Vite frontend and exact original CSS/layout preserved.
- Existing Python/FastAPI backend with PostgreSQL (SQLite for isolated tests) and cookie sessions preserved.
- `My Projects` (Trainer landing page) now consolidates assigned LeSuccess, Vendor, and Freelancer projects. `My Colleges` remains available for LeSuccess.
- Project-type dropdown in Daily Training Update; Vendor/Freelancer updates saved to new `external_training_updates` table with a unique project / trainer / date / category constraint.
- Historical Vendor/Freelancer projects matched by Employee ID (unique-name legacy fallback only), repeat-safe assignment alert backfill, and new in-app assignment alerts.
- Only assigned Trainer may submit; Running status, dates, category and attendance validated; related Reporting Manager (or in-chain Admin fallback) is stamped as reviewer.
- Unified Training Approvals for authorized Reporting Manager/Admin, with approve/reject only once.
- Project cards show approved-day progress and pending count; All Projects dashboard has a consolidated table.
- Excel import unchanged: original 19 worksheets and 119 user records remain in private ZIP; import runs with --if-empty only.
- Safe upgrade scripts/docs preserve `.env` and PostgreSQL volume; `start.sh` prevents accidentally generating a new password if an existing ltmp-modern_pgdata volume is present.

### Evidence

- `python -m pytest -q`: **46 passed**.
- `python tests/browser_assignment_e2e.py`: Chromium original UI -> LeSuccess assignment -> Trainer alert -> Daily Update **passed**.
- `python tests/browser_unified_training_e2e.py`: Chromium Admin creates Vendor/Freelancer -> Trainer receives alerts + submits -> RM approves -> Admin progress **passed**.
- `node --check frontend/public/legacy.js`: **passed**.
- `npm install && npm run build`: **not verified**, npm install timed out in this environment. Build on Mac via `docker compose -p ltmp-modern up -d --build`.
- PostgreSQL Docker/Nginx startup on user's Mac not verified here. Local isolated tests ran against SQLite with FastAPI and Chromium.
- Full 173-item original Apps Script audit was not repeated against production; separate earlier audit failures outside this requested workflow remain subject to review.
- Email, SMS, WhatsApp notifications are not implemented (in-app only).
- External freelance individuals without an LTMP internal Trainer account cannot sign in; Admin must select an Assigned Trainer account.
- Legacy LeSuccess dashboard progress counters count existing completed-day metrics; new cross-project summary counts unique **approved** training dates. This avoids rewriting historical data with potentially different business semantics.

### Safety

Existing source rows, login hashes, historical leave/KPI/tracker data, and database volumes are not modified by migration except additive external table creation and repeat-safe alert insertion. Project CRUD actions initiated by Admin still modify the project rows as usual. Keep backups. Do not run `docker compose down -v`. Do not share the private ZIP publicly.
