#!/bin/sh
set -eu

profile_dir="${DOUYIN_BROWSER_PROFILE_DIR:-/profile/douyin}"
mkdir -p "$profile_dir"

# Container recreation changes the hostname. Chrome's process singleton files
# can then incorrectly report that the persisted profile is still in use.
# These are runtime locks only; removing them does not touch cookies or login data.
rm -f \
    "$profile_dir/SingletonCookie" \
    "$profile_dir/SingletonLock" \
    "$profile_dir/SingletonSocket"

exec /usr/local/bin/google-chrome \
    --no-sandbox \
    --remote-debugging-address=127.0.0.1 \
    --remote-debugging-port=9223 \
    --user-data-dir="$profile_dir" \
    --no-first-run \
    --no-default-browser-check \
    --disable-infobars \
    --disable-background-networking \
    --disable-blink-features=AutomationControlled \
    --no-proxy-server \
    --window-size=1920,1080 \
    --start-maximized \
    about:blank
