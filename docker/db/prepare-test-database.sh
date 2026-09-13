#!/bin/sh

set -eu

production_db="${POSTGRES_DB:?POSTGRES_DB is required}"
test_db="${TEST_POSTGRES_DB:-${production_db}_test}"
database_user="${POSTGRES_USER:?POSTGRES_USER is required}"
# 本脚本预期在 db 容器里执行（脚本由 compose.infra.yml 挂载进去）；从别的容器执行时传 PGHOST=db。
postgres_host="${PGHOST:-127.0.0.1}"
# 容器内可直接复用 POSTGRES_PASSWORD，调用方不必重复传密钥
if [ -z "${PGPASSWORD:-}" ] && [ -n "${POSTGRES_PASSWORD:-}" ]; then
  PGPASSWORD="$POSTGRES_PASSWORD"
  export PGPASSWORD
fi

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
  --host="$postgres_host" \
  --username="$database_user" \
  --dbname="$production_db" \
  --format=custom \
  --no-owner \
  --no-privileges \
  --file="$dump_file"

psql \
  --host="$postgres_host" \
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
  --host="$postgres_host" \
  --username="$database_user" \
  --dbname="$test_db" \
  --exit-on-error \
  --no-owner \
  --no-privileges \
  "$dump_file"

# 浏览器槽位绑定属于用户库的运行时状态：复制到测试库后必须解绑，否则用户数据会占住
# 本机 / 远程槽位，槽位发现与独占绑定用例会被误判成「已绑定」。
psql \
  --host="$postgres_host" \
  --username="$database_user" \
  --dbname="$test_db" \
  --set=ON_ERROR_STOP=1 \
  --command='UPDATE douyin_account SET slot = NULL WHERE slot IS NOT NULL;'

echo "Test database '$test_db' is ready."
