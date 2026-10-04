#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/cineviax"
DB_FILE="$APP_DIR/movies.db"
BACKUP_DIR="/opt/cineviax/backups"
STAMP="$(date +%Y%m%d_%H%M%S)"

mkdir -p "$BACKUP_DIR"
if [[ ! -f "$DB_FILE" ]]; then
  echo "Database not found: $DB_FILE" >&2
  exit 1
fi

cp "$DB_FILE" "$BACKUP_DIR/movies_$STAMP.db"
find "$BACKUP_DIR" -type f -name 'movies_*.db' -mtime +14 -delete

echo "Backup created: $BACKUP_DIR/movies_$STAMP.db"
