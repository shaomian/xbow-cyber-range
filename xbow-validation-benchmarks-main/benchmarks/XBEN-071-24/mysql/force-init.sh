#!/bin/bash
# Force-init wrapper: always run backup.sql after MySQL is ready, regardless of
# whether docker-entrypoint-initdb.d already ran (handles leftover volumes).
set -e

# Start MySQL in background via official entrypoint
docker-entrypoint.sh mysqld &
MYSQL_PID=$!

# Wait until MySQL accepts connections
for i in $(seq 1 60); do
    if mysqladmin ping -h localhost -uroot -proot_password --silent 2>/dev/null; then
        break
    fi
    sleep 1
done

# Always force-run the init SQL (idempotent: backup.sql uses DROP TABLE IF EXISTS)
echo "[force-init] Executing backup.sql..."
mysql -u root -proot_password challenge < /docker-entrypoint-initdb.d/backup.sql 2>/dev/null || true
echo "[force-init] Done."

# Wait for the background MySQL process
wait $MYSQL_PID