# LTMP – Render Free + Neon Free hosting (Tamil-English)

**Architecture:** Render **one Free Web Service** (React static assets + FastAPI API at the **same HTTPS origin**), Neon **one Free PostgreSQL database**. Keep local Docker Compose for development. This project does **not** publish the Excel workbook or import data on every startup.

> This package provides deployment configuration and local/static tests; **deployment is not performed**. Render Free is appropriate for a controlled pilot, not guaranteed production uptime or sensitive employee-data compliance. Test permissions, CSRF, data access, backups and all four roles before real use.

## 0. Read this FIRST

- **Do not upload** `.env`, `LTMP.xlsx`, `.dump`, `.sql`, database credentials, screenshots with personal data, or backups to GitHub.
- Keep existing Mac `LTMP-modern/.env` and Docker `pgdata` volume untouched. Never run `docker compose down -v`.
- The deployment uses **Neon `DATABASE_URL`**, not local `POSTGRES_PASSWORD`. Local `docker-compose.yml` remains unchanged.
- New Render service will run with **no `imports/LTMP.xlsx`**. Users/projects must be migrated from your local DB **before** you publish the live URL.
- To prevent third-party cookie login failures, there is **one `https://<app>.onrender.com` origin** for UI and API. Do **not** create a separate Render Static Site for this configuration.

## 1. Create Neon Free database

1. Open [Neon](https://console.neon.tech/) and sign up.
2. Create a new **Free** project, select PostgreSQL version and **Singapore / closest available region** if offered.
3. Leave the database **empty** (no app deployment/migrations before restore).
4. Click **Connect**, set **Connection pooling OFF** for the initial migration (DIRECT URL) and copy the Postgres connection URI that includes `sslmode=require` (Neon may also include `channel_binding=require`).
5. **Never paste the URL in chat, GitHub, screenshots, or the browser console**. It contains a password.

## 2. Preserve existing Mac data: migrate before Render starts

Ensure old local PostgreSQL container is running. From the extracted complete project folder (`LTMP-modern`), use:

```bash
cd ~/Desktop/LTMP/LTMP-modern
bash deploy/migrate_mac_db_to_neon.sh
```

This script:

- creates a **private `.dump` backup** of local Docker PostgreSQL without reading `.env`;
- prompts you to paste the **Neon DIRECT URL without echoing**;
- checks the Neon database is **empty**; refuses to overwrite existing remote tables;
- restores **all** tables, including `users`, `sessions`, `source_rows`, `source_sheets`, `external_training_updates`, alerts and workflows, in **one transaction**;
- prints users-by-role/active counts so you can compare with local data.

If you are using a different DB container name, run:

```bash
LTMP_DB_CONTAINER=your-db-container-name bash deploy/migrate_mac_db_to_neon.sh
```

**If migration fails:** local backup/database stays unchanged. Do not use a `--clean` restore or run the migration again on a populated Neon database. Investigate the error; make a *new empty Neon database* for a new attempt if needed. Save the backup offline.

**No existing PostgreSQL records on Mac?** You can import an original Excel workbook into a fresh **private** database using `backend/scripts/import_excel.py` per the existing local README, then migrate it. The exported workbook snapshot may omit recent local records; prefer the running PostgreSQL database.

## 3. GitHub PRIVATE repository

Keep the `.gitignore` included in this ZIP. With the project at its **root**:

```bash
cd ~/Desktop/LTMP/LTMP-modern
# If no repository has been initialized yet:
git init
git add .
git status --short
```

Review files before committing. It should **NOT** include `.env`, `*.xlsx`, `*.dump`, `*.sql`, `backups/`, or `imports/LTMP.xlsx`.

```bash
git commit -m "Prepare LTMP for Render and Neon"
```

Create a **PRIVATE** GitHub repository (for example `ltmp-modern-private`). After copying its URL from GitHub:

```bash
git branch -M main
git remote add origin https://github.com/YOUR_ACCOUNT/ltmp-modern-private.git
git push -u origin main
```

If Git is already initialized, don't repeat `git init`/`git remote add origin`; verify the remote first with `git remote -v`.

## 4. Render Free deployment

1. Open [Render Dashboard](https://dashboard.render.com/). Connect your GitHub account, giving Render access to the **PRIVATE repo**.
2. Choose **New → Blueprint** (Render infrastructure-as-code) and select the repo with the included `render.yaml` at its root.
3. Render creates **one Web Service** named `ltmp-portal`. Verify plan is **Free**, runtime **Docker**, `Dockerfile.render`, region Singapore if available.
4. When Render requests the `DATABASE_URL` secret, paste the **Neon DIRECT Postgres URL** from the same Neon database restored in step 2. It must include `sslmode=require` (and any supplied `channel_binding=require`). Do not put this value in `render.yaml` or GitHub.
5. Environment variables (already in `render.yaml`):

   | Name | Value |
   |---|---|
   | `DATABASE_URL` | Private Neon URL (enter in Render only) |
   | `REQUIRE_DATABASE_URL` | `true` |
   | `SERVE_FRONTEND` | `true` |
   | `COOKIE_SECURE` | `true` |
   | `PYTHONUNBUFFERED` | `1` |

   **Do not set `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_USER` in the Render service**; the backend prioritizes raw local-Compose credentials when they are set.

6. Deploy. Render builds frontend (Vite) and backend into one Docker image, then starts Uvicorn on its assigned `$PORT`.
7. Open your Render service URL, e.g. `https://ltmp-portal.onrender.com` (use **your actual URL**, names can vary). Test `https://YOUR-URL/api/health`: expects HTTP 200 with `{"status":"ok",...}`.
8. Login with an **existing active LTMP Employee ID** and its existing LTMP password. Neon restore should preserve Argon2 password hashes. Test Admin, Reporting Manager, Team Leader, Trainer, especially role-specific access.

### Alternative: manual Render Web Service creation

If Blueprint setup is unavailable, use Render **New → Web Service → GitHub repo**, plan **Free**, runtime **Docker**, Dockerfile path `./Dockerfile.render` and project-root build context `.`, health path `/api/health`, add same environment variables above. **Don't** create separate Static Site for this version.

## 5. Cookies, CORS, HTTPS: exactly what this version does

- Frontend API client calls relative `/api/rpc/...`; **same HTTPS hostname** for React and FastAPI.
- Auth session is **HttpOnly**, `Secure` (`COOKIE_SECURE=true`), `SameSite=Lax`, path `/api`. No session token in JS/localStorage.
- FastAPI permits **no cross-origin browser requests by default on Render**; same-origin calls work without CORS. A request claiming a different `Origin` is rejected (403) before a state-changing API call.
- Render provides an HTTPS `onrender.com` endpoint and certificate; use HTTPS link only.
- No `VITE_API_ROOT` override needed; leave it unset/empty. A nonempty remote VITE_API_ROOT would re-introduce cross-site cookie problems.

**Later using a custom domain?** Point one custom domain to the same Render Web Service; no split `app`/`api` domains necessary.

## 6. Smoke-test checklist (with disposable records)

- `GET /api/health` returns HTTP 200.
- Login works for all four active roles, inactive users cannot log in.
- Trainer sees **LeSuccess, Vendor, Freelancer** assigned projects and notifications.
- Trainer submits Daily Training Update; Reporting Manager reviews; approved progress appears on dashboard.
- Trainer Daily Tracker submission → immediate Team Leader review.
- Trainer cannot reassign jobs (HTTP 403), manager without permission is blocked.
- Double-booking collision → HTTP 409; Admin can explicitly override.
- Leave request → correct immediate manager approval; Admin visibility.
- A browser refresh keeps login while session valid; Logout ends session.
- All requests go to **same HTTPS origin** (browser Network tab), no CORS errors, and cookies show HttpOnly/Secure/SameSite Lax.

## 7. Free-plan limitations and ongoing backups

- **Render Free Web Service sleeps after ~15 min idle**; first load may take ~1 minute after sleep. Free plan has no uptime SLA, and filesystem is ephemeral. Application records MUST remain in Neon, not container files.
- Neon Free currently offers limited monthly compute hours/storage/transfer; crossing a quota can stop requests/writes. Check official Free plan pages before launch.
- Render Free cannot run paid-only pre-deploy one-off jobs. `Base.metadata.create_all()` handles **new missing tables only**; it does NOT automatically migrate changed table columns. Test schema changes in a disposable Neon branch and add proper migrations before future database changes.
- Keep **manual backups** of Neon: `bash deploy/backup_neon.sh`, copy resulting `.dump` to encrypted private storage; repeat before releases and periodically. The first local DB backup does NOT contain newer cloud changes.
- Do not use this free pilot for regulated/sensitive employee information without an organizational privacy/security review, access policy, and verified disaster recovery.

## 8. Troubleshooting

| Symptom | Cause / action |
|---|---|
| Missing `DATABASE_URL` | Set Neon URI in Render environment dashboard. Render refuses to run SQLite fallback. |
| `psycopg2` missing | This version automatically normalizes Neon `postgresql://` URLs to `postgresql+psycopg://`. Make sure Docker image rebuilt. |
| `password authentication failed` | Copy exact Neon DIRECT URL with password, check DB name and endpoint. Don't reuse local POSTGRES_PASSWORD. |
| First request slow | Render Free cold start + Neon scale-to-zero. |
| Login invalid | Use Employee ID, not full/display name; check status and that Neon restored users. |
| Login works then not persisted | Check site is `https://`, cookie is Secure + Lax, frontend calls relative `/api`. Avoid separate frontend domain. |
| 403 Cross-origin | An API request came from a different website. Check `VITE_API_ROOT` or custom-domain deployment. |
| Empty users/data | DB restore not completed, or Render points to a different Neon database/branch. Don't auto-import old XLSX over new records. |
| New version missing columns | ORM `create_all()` doesn't ALTER tables. Build an explicit migration and verify before rollout. |
| Cloud database restore fails | Local DB remains untouched. Use new empty Neon DB for retry; no `--clean` or `--replace`. |

## Reference docs

- Render free tiers: https://render.com/docs/free
- Render Docker/web service: https://render.com/docs/web-services
- Render Blueprints: https://render.com/docs/blueprint-spec
- Render HTTPS: https://render.com/docs/static-sites
- Neon plans: https://neon.com/docs/introduction/plans
- Neon connection strings: https://neon.com/docs/connect/connect-from-any-app
