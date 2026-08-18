#!/bin/sh
set -eu

: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${PHOENIX_DB_USER:?PHOENIX_DB_USER is required}"
: "${PHOENIX_DB_PASSWORD:?PHOENIX_DB_PASSWORD is required}"
: "${PHOENIX_DB_NAME:?PHOENIX_DB_NAME is required}"
: "${BIFROST_DB_USER:?BIFROST_DB_USER is required}"
: "${BIFROST_DB_PASSWORD:?BIFROST_DB_PASSWORD is required}"
: "${BIFROST_DB_NAME:?BIFROST_DB_NAME is required}"

psql \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=ON_ERROR_STOP=1 \
  --set=phoenix_user="$PHOENIX_DB_USER" \
  --set=phoenix_password="$PHOENIX_DB_PASSWORD" \
  --set=phoenix_db="$PHOENIX_DB_NAME" \
  --set=bifrost_user="$BIFROST_DB_USER" \
  --set=bifrost_password="$BIFROST_DB_PASSWORD" \
  --set=bifrost_db="$BIFROST_DB_NAME" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'phoenix_user', :'phoenix_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'phoenix_user') \gexec

SELECT format('CREATE DATABASE %I OWNER %I ENCODING ''UTF8''', :'phoenix_db', :'phoenix_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'phoenix_db') \gexec

SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'bifrost_user', :'bifrost_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'bifrost_user') \gexec

SELECT format('CREATE DATABASE %I OWNER %I ENCODING ''UTF8''', :'bifrost_db', :'bifrost_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'bifrost_db') \gexec
SQL
