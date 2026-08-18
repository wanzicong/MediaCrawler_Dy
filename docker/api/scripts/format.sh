#!/bin/sh -e
set -x

ruff check modules tests --fix
ruff format modules tests
