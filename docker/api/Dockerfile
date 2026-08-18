FROM mediacrawler:latest AS ffmpeg-source

# Reuse the original project's cached FFmpeg without copying its 4.8 GB
# runtime image into the final API image. ldd returns the complete transitive
# shared-library set needed by this executable.
RUN set -eux; \
    mkdir -p /opt/ffmpeg/bin /opt/ffmpeg/lib; \
    cp /usr/bin/ffmpeg /opt/ffmpeg/bin/ffmpeg; \
    cp -L /lib64/ld-linux-x86-64.so.2 /opt/ffmpeg/bin/ld-linux-x86-64.so.2; \
    ldd /usr/bin/ffmpeg \
      | awk '/=> \// {print $3} /^\// {print $1}' \
      | sort -u \
      | while read -r library; do cp "$library" /opt/ffmpeg/lib/; done

FROM python:3.10

ENV PYTHONUNBUFFERED=1

# Never inherit a workstation-only proxy baked into a cached base image. In a
# container 127.0.0.1 refers to itself and breaks apt/uv during rebuilds.
ENV HTTP_PROXY="" HTTPS_PROXY="" ALL_PROXY="" \
    http_proxy="" https_proxy="" all_proxy=""

# MediaCrawler's copied a_bogus signer is JavaScript and PyExecJS needs a
# system JavaScript runtime in the API container.
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ffmpeg-source /opt/ffmpeg /opt/ffmpeg
COPY ./docker/api/scripts/ffmpeg-wrapper.sh /usr/local/bin/ffmpeg
RUN chmod 0755 /usr/local/bin/ffmpeg

# Install uv
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#installing-uv
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

# Compile bytecode
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#compiling-bytecode
ENV UV_COMPILE_BYTECODE=1

# uv Cache
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#caching
ENV UV_LINK_MODE=copy

WORKDIR /app/

# Place executables in the environment at the front of the path
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#using-the-environment
ENV PATH="/app/.venv/bin:$PATH"

# Install dependencies. Every workspace member manifest must be present so the
# workspace resolves; sources are copied afterwards.
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#intermediate-layers
# api/routes/system_docs.py imports crawler.mcp.server, so the mcp member's
# third-party dependencies must be installed alongside the api tree.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=modules/bootstrap/pyproject.toml,target=modules/bootstrap/pyproject.toml \
    --mount=type=bind,source=modules/browser/pyproject.toml,target=modules/browser/pyproject.toml \
    --mount=type=bind,source=modules/douyin-client/pyproject.toml,target=modules/douyin-client/pyproject.toml \
    --mount=type=bind,source=modules/business/pyproject.toml,target=modules/business/pyproject.toml \
    --mount=type=bind,source=modules/api/pyproject.toml,target=modules/api/pyproject.toml \
    --mount=type=bind,source=modules/mcp/pyproject.toml,target=modules/mcp/pyproject.toml \
    uv sync --frozen --no-install-workspace --package crawler-api --package crawler-mcp

COPY ./modules /app/modules
COPY ./docker/api/scripts /app/docker/api/scripts

# Runtime dependencies were installed from the lock file above. The services
# execute directly from the module sources, so installing the workspace
# packages a second time is unnecessary and would force an isolated hatchling
# download.
RUN python -m compileall -q /app/modules

WORKDIR /app/
# api/routes/system_docs.py introspects crawler.mcp.server, so the mcp module
# belongs on the path of every service built from this image.
ENV PYTHONPATH="/app/modules/api/src:/app/modules/business/src:/app/modules/douyin-client/src:/app/modules/browser/src:/app/modules/bootstrap/src:/app/modules/mcp/src"

# CDP sessions and the in-process task registry are intentionally single-worker.
CMD ["fastapi", "run", "--workers", "1", "modules/api/src/crawler/api/main.py"]
