#!/usr/bin/env bash

set -e
set -x

mypy -p crawler.bootstrap -p crawler.browser -p crawler.douyin_client -p crawler.business -p crawler.api -p crawler.mcp
ruff check modules tests
ruff format modules tests --check
