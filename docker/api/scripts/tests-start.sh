#! /usr/bin/env bash
set -e
set -x

python -m crawler.api.tests_pre_start

bash docker/api/scripts/test.sh "$@"
