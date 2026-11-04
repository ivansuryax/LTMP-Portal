# Render + Neon deployment changes

- Added `Dockerfile.render`: multistage build React assets and FastAPI in one Render Web Service to keep browser and API on the **same HTTPS origin**.
- Added `render.yaml` Blueprint (Free Docker web service; DATABASE_URL secret requested at deploy time).
- Updated FastAPI main to serve compiled React from `/` **only when `SERVE_FRONTEND=true`** and reject disallowed browser Origins for state-changing `/api` calls. Explicit CORS allowlist remains available locally; Render's same-origin mode enables none by default.
- Existing HttpOnly cookie now uses `Secure` when `COOKIE_SECURE=true` (Render config), with `SameSite=Lax` and `Path=/api` unchanged.
- Updated database engine to accept Neon's PostgreSQL URL with `psycopg3` (without installing psycopg2), using a bounded pool with `pool_pre_ping`.
- Added `REQUIRE_DATABASE_URL=true` fail-safe so Render cannot silently launch an empty ephemeral SQLite database when Neon credentials are missing.
- Added `deploy/migrate_mac_db_to_neon.sh` non-destructive backup-and-restore script: checks remote DB empty, single transaction, no `--clean` or `--replace`.
- Added `deploy/backup_neon.sh` for private ongoing cloud backups.
- Added `backend/tests/test_render_deployment.py` tests for configuration, secure origin enforcement and frontend serving.
- Existing local `docker-compose.yml`, all existing functionality, and original project data are unchanged. ZIP intentionally contains **NO private `.env`, `.xlsx`, `.sql`, or `.dump` files**.

**Limitations:** Render account and Neon credentials are user-controlled. No live deployment or network build has been performed here. Full security, privacy, load, and production recovery tests remain required before real employee data use.
