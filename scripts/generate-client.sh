#! /usr/bin/env bash

set -e
set -x

uv run python -c "import crawler.api.main; import json; print(json.dumps(crawler.api.main.app.openapi()))" > openapi.json
mv openapi.json frontend/
bun run --filter frontend generate-client
bun run lint
