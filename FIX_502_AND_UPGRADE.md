# 502 Fix & Safe Migration — Mac / Windows

## What caused the October 13 error

Your log said `failed to resolve host '1234@db'`. In the old `docker-compose.yml`, the database URL was built by concatenating the raw PostgreSQL password. Any password containing a reserved URL character such as `@` broke the URL and crashed `api`; Nginx displayed `502 Bad Gateway`. **This package fixes URL creation in Python with SQLAlchemy `URL.create()` and passes the existing raw password directly.** No `_ENCODED` duplicate variable is needed.

## Installation on an existing LTMP-modern Docker stack (do not lose data)

1. **Back up your current `LTMP-modern` directory and PostgreSQL volume before changing files.** At a minimum, keep your existing `.env` file and ensure you have a reliable database backup.
2. Extract this project folder and **reuse the same Compose project name**, normally the folder name `LTMP-modern`. Docker Compose volume names depend on the project name. Avoid running two distinct LTMP databases accidentally.
3. Copy **your existing `.env` into the new project root**, keeping the exact value of `POSTGRES_PASSWORD`. Do not substitute the example password, regenerate the password, or change a PostgreSQL password after volume initialization. `POSTGRES_PASSWORD_ENCODED` from previous troubleshooting may be removed; the new Compose file ignores it.
4. Run these commands in the project root:

```sh
docker compose config --quiet
docker compose up -d --build
docker compose ps -a
curl -i http://localhost:5173/api/health
```

5. Expected result: `api`, `db`, and `web` are Up; health returns `HTTP/1.1 200 OK` with `status: ok`. Sign in with an **active** user.

**Never run `docker compose down -v`** on a data-bearing installation. It deletes the Compose PostgreSQL volume. Do not delete or overwrite an existing `.env` or `pgdata` volume.

## Brand-new install

Install Docker Desktop, extract the **private** bundle (contains `imports/LTMP.xlsx`), then run `./start.sh` on macOS/Linux or `./start.ps1` on Windows PowerShell. These scripts create `.env` with a random database password **only if the file does not exist**. First startup imports the supplied workbook once; later restarts keep existing records. Do **not** use new-install instructions over an initialized database with unknown password.

## Still getting 502?

```sh
docker compose ps -a
docker compose logs --tail=80 api
curl -i http://localhost:5173/api/health
```

- `password authentication failed`: Compose `.env` differs from the **actual password of the existing PostgreSQL volume**. Restore the existing secret instead of resetting the volume.
- `connection refused`: database is not accessible yet; inspect `docker compose logs db`.
- `Failed to import` or `IntegrityError`: import/migration issue; retain volume and inspect logs.
- `api` restarting: Nginx will continue to return 502 until API startup succeeds.
- `api` Up but Nginx 502: inspect `docker compose logs --tail=80 web` and verify service names/network.

**Do not paste your `.env`, PostgreSQL password, or full `docker compose config` output into chat.** Docker Compose configuration output may contain secrets.

## What this does not certify

The supplied full project retains earlier LTMP fixes and automated tests, but it is an integrated development build. Full live PostgreSQL/Docker acceptance testing on your machine, complete regression against the 63 original Apps Script failures, performance/load, and production security approval remain required. `RELEASE_AUDIT.md` lists the gaps.
