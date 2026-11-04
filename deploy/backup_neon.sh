#!/usr/bin/env bash
# Manual Neon backup. Keep resulting dump PRIVATE; do not commit or upload.
set -euo pipefail
umask 077
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$ROOT/backups"
OUT="$ROOT/backups/ltmp-neon-$(date +%Y%m%d-%H%M%S).dump"
read -r -s -p 'Paste Neon DIRECT PostgreSQL URL (hidden): ' NEON_DIRECT_URL
printf '\n'
if [[ "$NEON_DIRECT_URL" != postgresql://* && "$NEON_DIRECT_URL" != postgres://* ]]; then
  echo 'Invalid Neon URL; refusing backup.' >&2; exit 1
fi
export NEON_DIRECT_URL
docker run --rm -e NEON_DIRECT_URL postgres:16-alpine sh -c \
 'pg_dump --format=custom --no-owner --no-acl --dbname="$NEON_DIRECT_URL"' > "$OUT"
unset NEON_DIRECT_URL
test -s "$OUT" || { echo 'ERROR: empty backup' >&2; exit 1; }
echo "Private Neon backup saved: $OUT"
