#!/bin/sh

set -eu

production_db="${POSTGRES_DB:?POSTGRES_DB is required}"
test_db="${TEST_POSTGRES_DB:-${production_db}_test}"
database_user="${POSTGRES_USER:?POSTGRES_USER is required}"

case "$test_db" in
  *[!A-Za-z0-9_]* | "" | "$production_db")
    echo "Refusing unsafe test database name: $test_db" >&2
    exit 1
    ;;
  *_test)
    ;;
  *)
    echo "Test database name must end with _test: $test_db" >&2
    exit 1
    ;;
esac

dump_file="$(mktemp /tmp/mediacrawler-test-db.XXXXXX.dump)"
trap 'rm -f "$dump_file"' EXIT

echo "Refreshing isolated database '$test_db' from '$production_db'..."
pg_dump \
  --host=db \
  --username="$database_user" \
  --dbname="$production_db" \
  --format=custom \
  --no-owner \
  --no-privileges \
  --file="$dump_file"

psql \
  --host=db \
  --username="$database_user" \
  --dbname=postgres \
  --set=ON_ERROR_STOP=1 \
  --set=test_db="$test_db" \
  <<'SQL'
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = :'test_db' AND pid <> pg_backend_pid();
SELECT format('DROP DATABASE IF EXISTS %I', :'test_db') \gexec
SELECT format('CREATE DATABASE %I', :'test_db') \gexec
SQL

pg_restore \
  --host=db \
  --username="$database_user" \
  --dbname="$test_db" \
  --exit-on-error \
  --no-owner \
  --no-privileges \
  "$dump_file"

echo "Test database '$test_db' is ready."
