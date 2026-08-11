# Dedicated headed Chrome service for Douyin CDP sessions.
# The crawler never launches Playwright Chromium inside this image; it only
# connects to Chrome through the DevTools Protocol exposed on port 9222.
FROM mcr.microsoft.com/playwright/python:v1.61.0-jammy

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    DISPLAY=:99

# Keep this layer aligned with the already-built MediaCrawler browser image so
# Docker can reuse the local BuildKit cache, including Chrome for Testing.
RUN sed -i 's@archive.ubuntu.com@mirrors.aliyun.com@g; s@security.ubuntu.com@mirrors.aliyun.com@g' /etc/apt/sources.list \
    && apt-get update && apt-get install -y --no-install-recommends \
        xvfb supervisor wget gnupg ca-certificates fonts-noto-cjk \
        curl x11vnc novnc websockify unzip \
    && wget -q -O /tmp/chrome-linux64.zip https://registry.npmmirror.com/-/binary/chrome-for-testing/141.0.7390.65/linux64/chrome-linux64.zip \
    && unzip -q /tmp/chrome-linux64.zip -d /opt/ \
    && mv /opt/chrome-linux64 /opt/chrome \
    && ln -sf /opt/chrome/chrome /usr/local/bin/google-chrome \
    && mkdir -p /opt/google/chrome \
    && ln -sf /opt/chrome/chrome /opt/google/chrome/chrome \
    && rm -f /tmp/chrome-linux64.zip \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Headed Chrome 141 binds its CDP listener to loopback in this environment.
# socat exposes a container-network endpoint without exposing Chrome itself.
RUN apt-get update && apt-get install -y --no-install-recommends socat \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

ENV DOUYIN_BROWSER_PROFILE_DIR=/profile/douyin

COPY supervisord.conf /etc/supervisor/conf.d/douyin-browser.conf
COPY start-chrome.sh /usr/local/bin/start-douyin-chrome

RUN chmod +x /usr/local/bin/start-douyin-chrome \
    && mkdir -p /profile/douyin /app/logs

VOLUME ["/profile"]

EXPOSE 9222 6080

HEALTHCHECK --interval=5s --timeout=3s --start-period=20s --retries=12 \
    CMD curl -fsS http://127.0.0.1:9223/json/version >/dev/null || exit 1

CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/supervisord.conf"]
