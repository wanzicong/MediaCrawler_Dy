#! /usr/bin/env sh

# Exit in case of error
set -e
set -x

docker compose -f compose.infra.yml -f compose.yml build
docker compose -f compose.infra.yml -f compose.yml down -v --remove-orphans # Remove possibly previous broken stacks left hanging after an error
docker compose -f compose.infra.yml -f compose.yml up -d
docker compose -f compose.infra.yml exec -T db sh /usr/local/bin/prepare-test-database
docker compose -f compose.infra.yml -f compose.yml exec -T backend bash docker/api/scripts/tests-start.sh "$@"
docker compose -f compose.infra.yml -f compose.yml down -v --remove-orphans
