# Run LTMP Modern locally

This package runs the existing LTMP application with **React, FastAPI and PostgreSQL**.

## Before you start

1. Install and open Docker Desktop.
2. Put your private original workbook at `imports/LTMP.xlsx`.
   - The workbook is deliberately not included in this ZIP because it may contain employee data and passwords.
3. Keep the project folder private. Do not upload `.env`, `LTMP.xlsx`, database backups, or screenshots containing employee data to a public repository.

## macOS / Linux

Open Terminal in this project folder and run:

```bash
chmod +x start.sh
./start.sh
```

The first run creates a local `.env` file with a database password and starts the database, API, and React web app. It imports `imports/LTMP.xlsx` only when the database is empty.

Then open:

```text
http://localhost:5173
```

## Windows

Open PowerShell in the project folder and run:

```powershell
.\start.ps1
```

Then open `http://localhost:5173`.

## If it does not open

Run these commands from the project folder:

```bash
docker compose -p ltmp-modern ps -a
docker compose -p ltmp-modern logs --tail=100 api
docker compose -p ltmp-modern logs --tail=100 web
```

Confirm Docker Desktop is running and that `imports/LTMP.xlsx` exists.

## Stop / restart safely

```bash
docker compose -p ltmp-modern stop
docker compose -p ltmp-modern start
```

Never run `docker compose down -v`: it permanently removes the local database volume.

## What has been verified

- React production build succeeds.
- Backend automated tests: 61 passed, 1 skipped.

## Important

This ZIP is the current verified React + FastAPI + PostgreSQL application. A real Spring Boot + TiDB Cloud migration requires porting the backend workflow and security logic, as well as a tested data migration to a TiDB Cloud database; it is not included here.
