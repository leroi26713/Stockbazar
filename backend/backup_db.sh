#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

DB_FILE="${DB_FILE:-stockbazar.db}"
BACKUP_DIR="${BACKUP_DIR:-backups}"

if [ ! -f "$DB_FILE" ]; then
  echo "Base introuvable: $DB_FILE" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$BACKUP_DIR/stockbazar_${STAMP}.db"

cp "$DB_FILE" "$OUT"
echo "Backup cree: $OUT"
