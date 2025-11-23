#!/bin/bash

# Настройки
DB_NAME="analitycs"
DB_USER="analitycs_user"
DB_HOST="185.47.207.55"
DB_PORT="5433"
PGPASSFILE="/home/AuthorizationBot/pgpass.conf"
BACKUP_DIR="/home/AuthorizationBot/backups"
DATE=$(date +%Y-%m-%d_%H-%M-%S)

# Создание папки, если нет
mkdir -p "$BACKUP_DIR"

# Экспорт переменной для pgpass
export PGPASSFILE="$PGPASSFILE"

# Создание бэкапа и лог ошибок
pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" > "$BACKUP_DIR/${DB_NAME}_backup_$DATE.sql" 2> "$BACKUP_DIR/error_$DATE.log"

# Удаляем старые бэкапы (старше 7 дней)
find "$BACKUP_DIR" -type f -name "*.sql" -mtime +7 -delete
