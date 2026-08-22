#! /usr/bin/env sh

# Exit in case of error
set -e
set -x

docker compose build
docker compose down -v --remove-orphans # Remove possibly previous broken stacks left hanging after an error
docker compose up -d
docker compose --profile test run --rm test-db-prepare
docker compose exec -T backend bash docker/api/scripts/tests-start.sh "$@"
docker compose down -v --remove-orphans
