# LTMP: Trainer reassignment security + double-booking (2026-10-13)

## 1. Exact approval chain (two independent modules)

**RM = Reporting Manager**, not Regional Manager.

- **Daily Tracker (hours/activity):** Trainer -> the Trainer's **immediately assigned Team Leader**. A Team Leader's own daily tracker -> its Reporting Manager. A Reporting Manager's own tracker -> its Admin. `Pending` means the assigned immediate reviewer has not yet decided. The reviewer can approve or reject; rejection comments are returned to the employee.
- **Daily Training Update / Syllabus:** College training topic / Vendor / Freelancer training record. In this portal it is routed to a **Reporting Manager** found in the trainer's reporting chain, falling back to an active Admin in the chain. This approval is *not* the same as Daily Tracker approval. Approved unique training dates feed progress metrics.
- **Draft / In Progress** is a form editing state; it is not a saved server status in the current portal. `Pending`, `Approved`, and `Rejected` are persisted. Rejected Daily Tracker records retain review comments; this release does **not** add edit-in-place/reopen for a rejected tracker. To correct it, submit an appropriately revised entry as permitted by your process.

## 2. Reassignment permissions

- **Trainer:** My Projects / Daily Updates are read/submit actions only. No reassignment/transfer/delegation controls. Any direct call to assignment-ownership mutators returns **HTTP 403** with `Trainers are not permitted to reassign jobs`.
- **Team Leader / Reporting Manager:** Can reassign LeSuccess trainers and change assignment status, and use the **ownership-only** Vendor/Freelancer reassignment form. Cannot edit general external project business fields; cannot override a double booking.
- **Admin:** Can assign/reassign all three project types, edit project metadata, and **explicitly override** occupied slots.
- Access control is checked using the current signed-in **server session**; passing another username in the request body does not grant permissions.

## 3. Double-booking rules

A trainer is considered occupied when an active/upcoming/on-hold booking for the **same normalized Employee ID** overlaps the intended date range AND time slot across **LeSuccess, Vendor, and Freelancer** assignments, or they have approved leave in that range.

- `Start Date` and `End Date` are required for a **new active trainer assignment**. Completed historical rows are preserved.
- `Start Time` / `End Time` are optional. When omitted, an assignment conservatively occupies the **whole day**. When set, both must be provided; end time must be later than start time. Adjacent non-overlapping slots (e.g. 09:00–11:00 and 11:00–12:00) are allowed.
- `Batch / Slot` is stored and displayed in warnings, but **a different batch name never bypasses a time conflict**.
- Active/historical booking rows with **no dates** cannot be evaluated accurately. New active assignments now require dates. Please audit historical undated rows manually.
- Assignment owner updates exclude the current assignment from its own clash test (but check against all *other* bookings).
- Browser dropdown/date selection runs `checkTrainerSchedule` and shows a warning. API also checks **again within the database transaction**. When conflict exists, it returns **409 Conflict** and writes **nothing**.
- Warning UI: **Cancel** or (**Admin only**) **Override & Proceed**. Admin confirmation repeats the API write with `acknowledgeConflict: true`. An audit alert records the override. Managers cannot override even with a forged flag.
- Booking time values are treated as **local project schedule times**; no timezone conversion or recurring-calendar scheduler has been implemented. A multi-day timed assignment is considered booked during that same time range on each date in the interval.
- PostgreSQL assignment writes take a trainer row lock to reduce simultaneous double-booking races. There is no external Google Calendar synchronization.

## 4. API sample

The portal calls the existing cookie-authenticated RPC endpoint. No authorization token is supplied in the JSON payload.

```json
POST /api/rpc/checkTrainerSchedule
{"args":[{"trainerUsername":"TK01103","startDate":"2026-10-13","endDate":"2026-10-14","startTime":"09:00","endTime":"12:00","projectType":"vendor"}]}
```

Successful availability previews return `available`, `is_occupied`, `conflicts`, and `alerts`. When attempting to commit an occupied slot without acknowledgement, the API returns **HTTP 409** with an `is_occupied` flag and details of the conflicting project, location/batch, dates and times. **403** is returned if a Trainer tries a reassignment; **403** is also returned if a manager tries overriding a conflict.

## 5. Manual acceptance test on your Mac

1. **Admin:** Create a LeSuccess project and assign Trainer A for 13–15 October, 09:00–11:00. Verify the assignment in the Trainer's My Projects and Alerts.
2. **Admin:** Create a Vendor project with the **same Trainer A** for 14 October, 10:00–12:00. A warning must appear. Click **Cancel**: no second assignment. Repeat and click **Override & Proceed**: save succeeds with an audit notice.
3. **Admin:** Assign Trainer A another Freelancer project for 14 October, 11:00–13:00; the overlap must be shown. Try a distinct slot 13:00–15:00 (if no all-day booking): no conflict.
4. **Team Leader or Reporting Manager:** Open a project and change its owner to a free trainer; save should succeed. Try occupied trainer: cannot override.
5. **Trainer:** Log in and check no ownership-edit controls appear. A crafted direct assignment request must fail with **403**. Trainer can still submit an assigned Daily Training Update and Daily Tracker.
6. **Trainer → Daily Tracker:** Submit a record. Check `Pending`, the immediate Team Leader account in the assigned reviewer field. Team Leader approves/rejects with comments; refresh Trainer's status and Alerts.
7. **Reporting Manager → Training Approvals:** Verify Daily Training Update approval is separate from the Daily Tracker approval; approved updates feed dashboard progress.

## 6. Data protection and safe upgrade

The project is **additive**: existing Users, LeSuccess, Vendor/Freelancer records, training submissions, leave requests, KPI and alerts are not replaced. Optional time/batch attributes are stored in the existing JSON project/assignment rows, so no destructive SQL migration is needed. This ZIP does not contain your local `.env` or PostgreSQL volume.

```sh
cd ~/Desktop/LTMP/LTMP-modern
docker compose -p ltmp-modern exec -T db pg_dump -U ltmp -d ltmp > ../ltmp-before-permission-upgrade.sql
test -s ../ltmp-before-permission-upgrade.sql && echo 'Backup non-empty'
# Copy new code files over old ones, keep original .env and database volume
docker compose -p ltmp-modern config --quiet
docker compose -p ltmp-modern up -d --build
docker compose -p ltmp-modern ps -a
curl -i http://localhost:5173/api/health
```

**Never run `docker compose down -v` on the existing installation.** Keep the existing `POSTGRES_PASSWORD`. On `502`, inspect `docker compose -p ltmp-modern logs --tail=80 api`, and do not share plaintext passwords or the `.env` file.

## 7. Verification scope

- `58/58` automated Python backend regression tests passed with SQLite test databases, including new permission, cross-project booking, leave, slot, audit and reviewer tests.
- Chromium UI (real DOM/script) + FastAPI TestClient bridge workflow passed: Admin creates two intentionally overlapping projects and explicitly overrides; Trainer submits updates; Reporting Manager approves; Admin sees dashboard approved progress. Manager reassignment modal and four-role shell smoke also passed.
- `node --check` for the legacy frontend JS and API client passed.
- The **new Vite/npm production build and your local Docker/PostgreSQL deployment were not verified here**: npm dependencies were unavailable offline and Docker is unavailable in the execution environment. Use your Mac and the checks above for final verification. Do not call this release production-certified without those checks.
