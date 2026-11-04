# Integration guide — already integrated

Bro, separate files copy / paste panna thevai illa. Orey package!

## Stage A — Open and start

1. Download **LTMP-modern-integrated-private.zip** to your own computer.
2. Extract it in a **private folder**. The included `imports/LTMP.xlsx` is confidential.
3. Start Docker Desktop.
4. **Windows**: from PowerShell run `.\start.ps1`.
   **macOS/Linux**: run `./start.sh`.
5. In browser open `http://localhost:5173` and sign in with an active account
   already in the original workbook.

## Stage B — First-run flow (automatic)

- Docker creates PostgreSQL container.
- FastAPI checks whether the workbook has already been imported.
- On fresh DB, all sheets are staged and Users records become password-hashed accounts.
- React/Vite production frontend is served through Nginx on port 5173.
- Legacy UI calls FastAPI directly through `/api/rpc/{functionName}`.

## Stage C — Verify modules in this order

1. Admin: Login, Dashboard, User Management.
2. Admin: Create College, set categories, assign Trainer.
3. Trainer: My Colleges, submit a Daily Update.
4. Reporting Manager: approve syllabus; Admin: check progress.
5. Trainer: submit leave; Team Leader: review leave.
6. Trainer: submit Daily Tracker; Team Leader: approve.
7. Trainer: KPI rating; Team Leader: approve/return and unlock.
8. Admin: Vendor/Freelance projects, reporting, alerts.

**These phases are coding milestones, not separate installation steps.**

## Stage D — Next release readiness

Use `MIGRATION_STATUS.md` to track browser tests, security review, data reconciliation,
Google Drive integration and deployment. Keep the current Apps Script live until a
real-world comparison passes; this app never silently writes back to Google Sheets.
