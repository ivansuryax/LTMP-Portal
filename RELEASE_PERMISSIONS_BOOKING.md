# LTMP secure assignment + scheduling release

**Feature scope:** Trainer reassignment prohibition, Admin/Manager ownership permissions, date/time/batch conflict warnings with Admin-only acknowledgement, Daily Tracker reviewer clarity, and review notifications. Includes the previous unified LeSuccess + Vendor + Freelancer trainer flows and all original project modules.

**Files changed**

- `backend/app/scheduling.py` — new cross-project booking conflict engine
- `backend/app/workflows.py` — role guards, schedule validation for LeSuccess assignments, Daily Tracker reviewers/status notifications
- `backend/app/main.py` — exact 403 for Trainer reassign attempts, guarded Vendor/Freelancer write actions, manager-only ownership RPC `reassignJob`, create-college initial assignment checks
- `backend/app/queries.py` + `backend/app/unified_projects.py` — optional time/batch fields in API readers
- `frontend/public/legacy.js` — trainer read-only ownership controls, manager reassign UI, booking previews, 409 acknowledgement modal, clearer tracker status
- `frontend/src/api.js` — actionable status/conflict details for HTTP 409
- `backend/tests/test_permissions_booking.py` — targeted tests for session security and cross-source conflict cases
- `backend/tests/browser_unified_training_e2e.py` — updated explicit override and manager modal smoke

**Behavior notes**

- `Manager` means LTMP roles **Team Leader** and **Reporting Manager**, not a literal extra database role.
- Override authorization: Admin only. A management user can save an available booking but cannot force a conflict.
- `RM` means Reporting Manager. Daily Tracker uses immediate supervisor approval; Daily Training Update uses Reporting Manager in hierarchy.
- No destructive schema or data migration; no new database volume. `.env` intentionally omitted.
- Prior production records with missing dates cannot be scheduled reliably; inspect manually. No new e-mail/SMS delivery has been added.
- Time slots are local and non-recurring. Explicit Trainer Employee ID is required for portal assignment (historical unique display-name resolution remains supported by read paths).

See `SECURE_ASSIGNMENT_AND_BOOKING_GUIDE_TAMIL.md` for usage, upgrade, QA and precise role behavior.
