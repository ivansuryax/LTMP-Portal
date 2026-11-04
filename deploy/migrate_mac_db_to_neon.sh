#!/usr/bin/env bash
# SAFE: Copy existing LTMP PostgreSQL database to a BRAND-NEW EMPTY Neon database.
# Does NOT remove or change the local database; does NOT run pg_restore --clean.
set -euo pipefail
umask 077

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUPS="$PROJECT_DIR/backups"
mkdir -p "$BACKUPS"
LOCAL_CONTAINER="${LTMP_DB_CONTAINER:-ltmp-modern-db-1}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
DUMP="$BACKUPS/ltmp-local-$TIMESTAMP.dump"
RESTORE_LIST="$BACKUPS/ltmp-restore-list-$TIMESTAMP.txt"

if ! command -v docker >/dev/null 2>&1; then
  echo 'ERROR: Docker Desktop must be installed and started.' >&2
  exit 1
fi
if ! docker inspect "$LOCAL_CONTAINER" >/dev/null 2>&1; then
  echo "ERROR: Local Postgres container '$LOCAL_CONTAINER' was not found." >&2
  echo 'Start the original local LTMP stack first, or set LTMP_DB_CONTAINER.' >&2
  exit 1
fi
printf 'Making local backup (no .env file needed)...\n'
docker exec "$LOCAL_CONTAINER" pg_dump --format=custom --no-owner --no-acl -U ltmp -d ltmp > "$DUMP"
if ! [ -s "$DUMP" ]; then
  echo 'ERROR: backup file is empty; aborting.' >&2
  exit 1
fi
printf 'Backup saved locally: %s\n' "$DUMP"

printf '\nCreate a fresh, EMPTY Neon Free database first.\n'
printf 'In Neon Connect, disable Connection pooling, copy the DIRECT Postgres URL.\n'
printf 'Your password/URL will not be printed or saved by this script.\n'
read -r -s -p 'Paste Neon DIRECT connection URL (hidden): ' NEON_DIRECT_URL
printf '\n'
if [[ "$NEON_DIRECT_URL" != postgresql://* && "$NEON_DIRECT_URL" != postgres://* ]]; then
  echo 'ERROR: expected a PostgreSQL connection URL.' >&2
  exit 1
fi
if [[ "$NEON_DIRECT_URL" == *-pooler.* ]]; then
  echo 'ERROR: this is a POOLED Neon URL. Disable Pooled connection in Neon and paste the DIRECT URL for migration.' >&2
  exit 1
fi
if [[ "$NEON_DIRECT_URL" != *sslmode=require* && "$NEON_DIRECT_URL" != *sslmode=verify-full* ]]; then
  echo 'ERROR: Neon connection URL must require TLS (sslmode=require or verify-full).' >&2
  exit 1
fi
export NEON_DIRECT_URL

# Require an EMPTY destination so a mistake cannot overwrite your Neon data.
printf 'Checking destination is reachable and empty...\n'
TABLES="$(docker run --rm -e NEON_DIRECT_URL postgres:16-alpine sh -c \
 'psql "$NEON_DIRECT_URL" -X -A -t -v ON_ERROR_STOP=1 -c "SELECT COUNT(*) FROM pg_catalog.pg_tables WHERE schemaname = '\''public'\''"' | tr -d '\r\n[:space:]')"
if [[ "$TABLES" != 0 ]]; then
  echo "ERROR: Neon destination contains $TABLES public tables or inspection failed." >&2
  echo 'Refusing to overwrite existing remote data; use a newly created EMPTY database.' >&2
  exit 1
fi

# Neon already has public schema. Suppress a duplicate CREATE SCHEMA public
# without using --clean and without touching any existing data.
docker run --rm -i postgres:16-alpine pg_restore --list < "$DUMP" > "$RESTORE_LIST"
sed -E '/ SCHEMA - public[[:space:]]/d;/ COMMENT - SCHEMA public[[:space:]]/d' "$RESTORE_LIST" > "$RESTORE_LIST.filtered"
mv "$RESTORE_LIST.filtered" "$RESTORE_LIST"
DUMP_FILE="$(basename "$DUMP")"
LIST_FILE="$(basename "$RESTORE_LIST")"
export DUMP_FILE LIST_FILE
printf 'Restoring to empty Neon DB in a single transaction (no destructive clean)...\n'
docker run --rm \
  -v "$BACKUPS:/backups:ro" \
  -e NEON_DIRECT_URL -e DUMP_FILE -e LIST_FILE \
  postgres:16-alpine sh -c \
  'pg_restore --no-owner --no-acl --single-transaction --exit-on-error --use-list="/backups/$LIST_FILE" --dbname="$NEON_DIRECT_URL" "/backups/$DUMP_FILE"'

printf '\nChecking imported user count...\n'
docker run --rm -e NEON_DIRECT_URL postgres:16-alpine sh -c \
 'psql "$NEON_DIRECT_URL" -X -v ON_ERROR_STOP=1 -c "SELECT role, active, COUNT(*) AS users FROM public.users GROUP BY role, active ORDER BY role, active"'
unset NEON_DIRECT_URL
printf '\nSUCCESS: local database unchanged; new Neon database restored.\n'
printf 'NEXT: Configure Render DATABASE_URL with Neon DIRECT URL, then deploy.\n'
