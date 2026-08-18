#! /usr/bin/env bash

set -e
set -x

# Let the DB start
python -m crawler.api.backend_pre_start

# Run migrations (alembic.ini lives in the business module)
(cd modules/business && alembic upgrade head)

# Create initial data in DB
python -m crawler.api.initial_data
