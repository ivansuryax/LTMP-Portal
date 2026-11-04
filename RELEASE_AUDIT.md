# LTMP Repaired Development Build — Code Review and Test Results

**Date:** October 13, 2026. **Status:** Development/staging candidate; not
production certified. Input: user's pasted Apps Script frontend/backend source,
19-sheet Excel snapshot, previously generated integrated FastAPI project, and
user-supplied **LTMP Functionality Traversal Report**.

## Scope clarification

The submitted traversal report's **173 / 110 / 63** numbers evaluate the
*original Google Apps Script code*, using a simulated SpreadsheetApp and DOM.
They are **not** test results for this FastAPI redevelopment. We used the
reported failure modes as a regression checklist; do not interpret 25 backend
tests as disproving or resolving all 63 original failed criteria.

## Confirmed fixes and coverage

| Area | Repair / safeguard | Automated evidence |
|---|---|---|
| Authentication | Normalize Excel numeric user IDs and direct manager references; repair pre-existing PostgreSQL data without reset | 119 real workbook account logins checked; 4 roles |
| Roles | Active accounts across Admin/RM/TL/Trainer can sign in; inactive denied; server session authorization | Role-level RPC and access tests |
| Admin Leave | Leave Management menu, pending list with stamped approver and review comments | Chromium shell and real API/browser bridge |
| Admin Daily Tracker | Review navigation and team approval page | Chromium shell and browser/API bridge |
| Leave | Duplicate-overlap prevention, approver stamping, visibility and expired-alert suppression | Leave workflow regression tests |
| Tracker | Stamped approver survives reassignment, 24-hour total limit, inactive activity and location checks, approved-leave missing-day exemption | Regression tests |
| KPI | Imported Excel numeric 0.05 -> 5%, admin self-rating, historic stamped approver visibility, decision validation | Regression tests |
| Colleges | Unique categories, nonnegative planning, correctly shaped initial assignment flags | Service tests |
| Assignment | Current vs historical assignment in trainer counts, roster, My Colleges, invalid date range validation | Regression tests |
| Daily Training | Active date-valid assignment required, duplicate submissions blocked, attendance range guard, log-linked syllabus review state | Regression tests |
| Syllabus | Explicit decision and already-reviewed check, restrict RM review to their hierarchy | Regression tests |
| Vendor | User ID rather than full name sent from picker; backend resolves unique name where possible | Regression test and JS syntax |
| Alerts | Navigate leave/tracker/KPI alerts to respective pages | Chromium shell smoke |
| UX | Avoid false success messages on common mutations, display review comments, preserve CSV input cell values, neutralize formula-like CSV values | JavaScript check / selective Chromium smoke |
| Sessions | Hashed passwords, HttpOnly SameSite session, inactive account rejection, logout clears UI caches | API auth tests |

## Executed checks

- Previous build: **25 passed**; current re-tested build: **34 passed** (9 additional database connection regression checks).
- Original 19-sheet workbook: **119 users** imported to isolated SQLite.
  All **59 active** user/password combinations accepted, all **60 inactive**
  combinations rejected; nothing printed from credential fields.
- `node --check frontend/public/legacy.js`: passed.
- Chromium original-shell page smoke across 4 roles: passed, using stub API.
- Chromium original-shell DOM + actual FastAPI TestClient + disposable database:
  passed for Trainer leave/tracker submission, Team Leader approvals,
  Reporting Manager navigation, Admin leave/tracker visibility.
- `npm install` / Vite build: **not verified**; registry DNS returned EAI_AGAIN.
- Docker/PostgreSQL runtime, Nginx and live deployment: **not verified**; Docker
  is not available here. Browser loopback-network E2E could not run due policy,
  hence the Chromium TestClient bridge was used instead.

## Remaining important gaps — do NOT use for unreviewed production

- Run real `npm install && npm run build` and Docker Compose on an actual
  connected development machine. Conduct production-like cross-browser E2E.
- Database is an intermediate JSON row compatibility model (`source_rows`), not
  a fully indexed relational redesign. Concurrent writes, high load, race
  handling and transaction/deadlock behavior on PostgreSQL remain to be tested.
- Full original UI includes complex inline handlers. Adversarial text inputs,
  broad XSS sanitization, CSP and security review are still required.
- Some original planning/progress business rules remain ambiguous: when a
  training day counts (on log vs on syllabus approval), whether rejected
  syllabus work decrements progress, and leave/reporting period semantics.
- Current Admin leave dashboard counts approved working days intersecting
  running assignments; pending requests are instead in Leave Management.
- Old project data import preserves source rows but no current production
  project/leave transactions exist in supplied workbook, so full migration
  reconciliation remains impossible from this snapshot.
- Cloud attendance template cloning/sync requires authorized Google Drive
  credentials and is not yet implemented; manually entered URLs work.
- Account recovery, secure HTTPS deployment, logging/audit retention,
  PostgreSQL backup/restore drill, alert delivery, operational monitoring,
  mobile/pixel parity and load benchmarks require deployment validation.
- Original code's CSV/report UI, vendor/freelance summary edge cases, rapid
  navigation races and rich KPI review interactions need expanded browser tests.

This package is the best tested integrated development source we can deliver
from the supplied material here, **not a claim that all 63 historical failure
criteria were exhaustively cleared in the live app**.

## October 13 follow-up: startup 502 fix

User-provided real Mac logs pinpointed an API restart loop caused by interpolating a password containing reserved URI characters into `DATABASE_URL`. The repaired Compose file provides raw `POSTGRES_PASSWORD`, `POSTGRES_USER`, `POSTGRES_DB`, and `POSTGRES_HOST`, and `app/db.py` creates an SQLAlchemy URL object. This change fixes the demonstrated parse issue. Environment-specific PostgreSQL authentication and live Docker startup on the user Mac are still unverified.

## October 13 trainer assignment / notifications follow-up

- Current assignment identity is normalized at query and profile authorization boundaries (`12345.0` vs `12345`).
- Backend `assignTrainer` validates college/category/dates/status/active Trainer and writes a persistent `Trainer Assigned` alert for that Trainer's Employee ID. Initial college-trainer assignment and assignment replacement/status-change also generate alerts.
- Trainer navigation includes **Alerts**, and notifications can be marked read by their own recipient. Read notices are not recreated by the repeat-safe historical assignment alert backfill.
- Admin assignment form category selector is populated from the selected college's **Training Planning**, reducing typographical mismatches. Inactive/Completed state shows a warning explaining that the Daily Update form will not appear.
- Trainer Daily Update now explains exactly why the form is unavailable, with self-only diagnostics and retry.
- `backend/tests/test_assignment_notifications.py`: role/privacy/ID/backfill/initial assignment/replacement/current/inactive checks.
- `backend/tests/browser_assignment_e2e.py`: Chromium UI with disposable SQL FastAPI backend tests Admin college create, assignment, Trainer notification and Daily Update submission.
- Validation: `40 passed` via pytest, Chromium assignment E2E passed. No live Mac Docker run or Vite bundle build was available for this revision.
