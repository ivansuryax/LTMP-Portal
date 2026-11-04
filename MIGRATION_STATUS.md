# LTMP Development Phases — Integrated Delivery

Date: October 13, 2026. Status: **Integrated development build; NOT production-certified.**

Each phase is **already combined into one repository**. You do not manually integrate anything.

| Phase | Module | Current development state |
|---|---|---|
| 1 | Original LTMP HTML / CSS / JS frontend, React host and FastAPI transport | Implemented; browser pixel test pending |
| 2 | PostgreSQL setup, Excel import (19 sheets) and account authentication | Implemented; 119 original users smoke-tested |
| 3 | Dashboard, users, college create/edit, category planning, trainer assignments/history | Implemented; automated workflow tests |
| 4 | Daily training updates, syllabus approval, progress/attendance reports | Implemented; automated workflow tests |
| 5 | Leave submissions, reporting-manager review, calendar overlap, availability | Implemented; automated workflow tests |
| 6 | Activity Master, daily tracker, review, missing-day alerts and monthly report | Implemented; automated workflow tests |
| 7 | KPI master, ratings, stamped manager review, returned rating, reopen | Implemented; automated workflow tests |
| 8 | Alerts, vendor and freelance projects, role-based UI routing | Implemented baseline; edge cases need full business-data test |
| 9 | Docker one-command integration, restart-safe first import, setup docs | Implemented; Docker runtime not verified in this environment |

## Tests performed

- 25 backend regression tests passing, including imported account login checks.
- Original user-provided `LTMP.xlsx` (19 worksheets, 119 user rows) imported into
  isolated temporary SQLite; duplicate-safe startup import skipped existing data.
- Imported numeric employee-ID mismatch repaired; all 59 active users from
  supplied workbook authenticated; all 60 inactive users rejected.
- `frontend/public/legacy.js` passed `node --check`.
- All 64 statically named frontend `callServer` RPC names recognized in backend source.
- Chromium original-shell and FastAPI/database bridge workflows tested for 4 roles.
- npm frontend build and live Docker launch could not be run in this environment.

## Fidelity / known deviations

- Existing LTMP HTML/CSS and major UI behavior are preserved. The React conversion
  is a wrapper, not independently rewritten React screens.
- Source `updateCategoryPlanning` contains a completed-day preservation defect;
  new implementation preserves previous completed days correctly.
- New API enforces server-derived identity (the browser cannot authorize itself
  by setting `actorUsername` on writes).
- Dates are stored as ISO; UI presentation returns the original formatted dates.
- Daily update submission is limited to assigned Trainers, adding stricter validation.
- Admin role can perform syllabus approvals in the new backend (original source
  restricted this operation to Reporting Manager).
- Original Apps Script Google Drive attendance-template cloning was intentionally
  NOT reproduced because approved Drive credentials are not available. Manual links work.
- Existing workbook has little/no actual operational data across multiple tabs.
  Empty tables remain empty (no fictional data seeded into production).

## Work required before production

1. Install frontend dependencies and verify Vite production build and all UI flows
   in a real browser. Compare screenshots with original app for every role.
2. Test with production-like populated colleges, assignments, Daily Log, KPI,
   leaves, and project rows. Reconcile calculations and migration row counts.
3. Add typed relational tables/indexes for hot query paths and load-test targets.
4. Verify all role-level read permissions and threat-model the old HTML/JS for XSS.
5. Set HTTPS and secure cookies behind managed ingress; configure backups/restore,
   account recovery, audit logging, monitoring and incident handling.
6. Implement optional Google Drive/Sheets integration only if approved and credentials
   are supplied, or remove clone-related UI expectations.
7. Perform pilot rollout against legacy LTMP before replacing it.

There is no truthful basis to claim pixel-perfect behavior or a faster production
response time without browser tests and representative load measurements.
