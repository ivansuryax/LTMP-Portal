#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if ! command -v docker >/dev/null 2>&1; then
  echo 'Please install and start Docker Desktop first.'
  exit 1
fi
# Do this before creating .env.  When Docker Desktop is stopped, a volume
# inspection returns an error that is indistinguishable from a missing volume;
# generating a new password in that state would lock the API out of an
# existing database after Docker starts.
if ! docker info >/dev/null 2>&1; then
  echo 'Docker Desktop is installed but not running. Open it, wait for Engine running, then run this script again.'
  exit 1
fi
if [ ! -f .env ]; then
  if docker volume inspect ltmp-modern_pgdata >/dev/null 2>&1; then
    echo 'SAFETY STOP: Existing ltmp-modern PostgreSQL volume detected but .env is missing.'
    echo 'Restore your ORIGINAL POSTGRES_PASSWORD into .env before upgrading.'
    echo 'Do not generate a new password or use docker compose down -v.'
    exit 1
  fi
  PASS="$(LC_ALL=C od -An -N24 -tx1 /dev/urandom | tr -d ' \n')"
  printf 'POSTGRES_PASSWORD=%s\nCOOKIE_SECURE=false\n' "$PASS" > .env
  chmod 600 .env
  echo 'Created a private .env for a NEW local database. Keep this file safe.'
fi
if [ ! -f imports/LTMP.xlsx ]; then
  echo 'Missing imports/LTMP.xlsx. Use the private ZIP or place your source workbook in imports/.'
  exit 1
fi
docker compose -p ltmp-modern config --quiet
docker compose -p ltmp-modern up -d --build
echo 'LTMP requested. Once ready, open http://localhost:5173.'
echo 'Health: curl -i http://localhost:5173/api/health'
echo 'Diagnostics: docker compose -p ltmp-modern ps -a && docker compose -p ltmp-modern logs --tail=60 api'
echo 'NEVER run docker compose down -v: it destroys PostgreSQL data.'
