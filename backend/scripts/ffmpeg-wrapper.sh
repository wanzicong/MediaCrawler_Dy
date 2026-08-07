#!/bin/sh
set -eu

exec /opt/ffmpeg/bin/ld-linux-x86-64.so.2 \
  --library-path /opt/ffmpeg/lib \
  /opt/ffmpeg/bin/ffmpeg "$@"
