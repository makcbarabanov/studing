#!/bin/bash
BACKUP_DIR="/home/makc/db_backups"   # или ~/db_backups
SIZE_FILE="$BACKUP_DIR/last_size.txt"
PG_HOST="83.217.220.97"
PG_USER="marabot"
PG_DB="default_db"
export PGPASSWORD="твой_пароль_от_БД"   # или используй ~/.pgpass

mkdir -p "$BACKUP_DIR"

# Размер БД в байтах (запрос к PostgreSQL)
CURRENT_SIZE=$(/usr/lib/postgresql/17/bin/psql -h "$PG_HOST" -U "$PG_USER" -d "$PG_DB" -t -A -c "SELECT pg_database_size('$PG_DB');" 2>/dev/null)

if [ -z "$CURRENT_SIZE" ]; then
  echo "$(date): Ошибка подключения к БД" >> "$BACKUP_DIR/backup.log"
  exit 1
fi

LAST_SIZE=""
[ -f "$SIZE_FILE" ] && LAST_SIZE=$(cat "$SIZE_FILE")

if [ "$CURRENT_SIZE" != "$LAST_SIZE" ]; then
  DUMP_FILE="$BACKUP_DIR/default_db_$(date +%Y%m%d_%H%M%S).dump"
  /usr/lib/postgresql/17/bin/pg_dump -h "$PG_HOST" -U "$PG_USER" -d "$PG_DB" -F c -f "$DUMP_FILE"
  if [ $? -eq 0 ]; then
    echo "$CURRENT_SIZE" > "$SIZE_FILE"
    echo "$(date): Создан бэкап $DUMP_FILE (размер БД: $CURRENT_SIZE)" >> "$BACKUP_DIR/backup.log"
  else
    echo "$(date): Ошибка pg_dump" >> "$BACKUP_DIR/backup.log"
  fi
else
  echo "$(date): Размер БД не изменился, бэкап пропущен" >> "$BACKUP_DIR/backup.log"
fi