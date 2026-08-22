#!/usr/bin/env bash

set -euo pipefail

if [[ "${TESTING:-}" != "true" || "${POSTGRES_DB:-}" != *_test ]]; then
  echo "Refusing to start test backend without TESTING=true and a *_test database" >&2
  exit 1
fi

python -m crawler.api.backend_pre_start

pushd modules/business >/dev/null
alembic upgrade head
popd >/dev/null

python -m crawler.api.initial_data
exec fastapi run --workers 1 modules/api/src/crawler/api/main.py
