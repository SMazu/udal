#!/usr/bin/env bash
set -euo pipefail

export POSTGRES_HOST="${POSTGRES_HOST:-127.0.0.1}"
export POSTGRES_PORT="${POSTGRES_PORT:-5432}"
export POSTGRES_DB="${POSTGRES_DB:-finance}"
export POSTGRES_USER="${POSTGRES_USER:-postgres}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-postgres}"
export MYSQL_HOST="${MYSQL_HOST:-127.0.0.1}"
export MYSQL_DATABASE="${MYSQL_DATABASE:-marketing}"
export MYSQL_USER="${MYSQL_USER:-lineage}"
export MYSQL_PASSWORD="${MYSQL_PASSWORD:-lineage}"

service postgresql start
until pg_isready -h 127.0.0.1 -p "${POSTGRES_PORT}" >/dev/null 2>&1; do
  sleep 0.2
done
su postgres -c "psql -v ON_ERROR_STOP=1 -c \"ALTER USER postgres WITH PASSWORD '${POSTGRES_PASSWORD}';\""
su postgres -c "createdb '${POSTGRES_DB}'" >/dev/null 2>&1 || true

service mariadb start
until mysqladmin --host=localhost --protocol=socket -uroot ping --silent; do
  sleep 0.2
done
mysql --host=localhost --protocol=socket -uroot <<SQL
CREATE DATABASE IF NOT EXISTS ${MYSQL_DATABASE};
CREATE USER IF NOT EXISTS '${MYSQL_USER}'@'localhost' IDENTIFIED BY '${MYSQL_PASSWORD}';
CREATE USER IF NOT EXISTS '${MYSQL_USER}'@'%' IDENTIFIED BY '${MYSQL_PASSWORD}';
GRANT ALL PRIVILEGES ON ${MYSQL_DATABASE}.* TO '${MYSQL_USER}'@'localhost';
GRANT ALL PRIVILEGES ON ${MYSQL_DATABASE}.* TO '${MYSQL_USER}'@'%';
FLUSH PRIVILEGES;
SQL

exec "$@"
