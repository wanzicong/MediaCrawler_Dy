#! /usr/bin/env bash

# Exit in case of error
set -e

docker compose -f compose.infra.yml -f compose.yml down -v --remove-orphans # Remove possibly previous broken stacks left hanging after an error

if [ $(uname -s) = "Linux" ]; then
    echo "Remove __pycache__ files"
    sudo find . -type d -name __pycache__ -exec rm -r {} \+
fi

docker compose -f compose.infra.yml -f compose.yml build
docker compose -f compose.infra.yml -f compose.yml up -d
docker compose -f compose.infra.yml -f compose.yml --profile test run --rm test-db-prepare
docker compose -f compose.infra.yml -f compose.yml exec -T backend bash docker/api/scripts/tests-start.sh "$@"
