#!/usr/bin/env bash
# infra-keepalive.sh —— 在 WSL 中常驻，钉住发行版并保持基础服务（db / minio）运行。
#
# 背景：WSL 在没有活动会话时会向发行版发送关机请求（journal 里表现为
# systemd-logind "The system will power off now!"），systemd 随即按
# docker.service 的 `Requires=docker.socket` 停掉 docker.socket / docker.service，
# 容器（含 Postgres）被一并停止；容器重新拉起要十几秒，Windows 侧后端就会拿到
# psycopg 的 "connection timeout expired"。
#
# 本脚本由 scripts/start-infra.ps1 以隐藏进程启动（`wsl -d <发行版> -e bash <本脚本>`）：
#   1. 等 docker daemon 就绪；
#   2. 只拉起 compose.infra.yml 里的 db / minio（绝不碰 backend/frontend/mcp/浏览器容器）；
#   3. 末尾用 `exec sleep` 持有会话，使 WSL 不再触发上面的关机流程。
#
# 失败不退出：先保证会话常驻（发行版不被回收），问题交给 start-infra.ps1 报告。
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WAIT_SECONDS="${INFRA_DOCKER_WAIT_SECONDS:-180}"
# 既是休眠时长，也是 start-infra.ps1 用来识别本会话的进程标记。
SLEEP_SECONDS=2147483647

log() { printf '[infra-keepalive] %s\n' "$*"; }

# 1) 等 docker daemon 就绪：发行版刚启动时 systemd 还在拉起 docker.service
deadline=$(( $(date +%s) + WAIT_SECONDS ))
while ! docker info >/dev/null 2>&1; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
        log "docker daemon 在 ${WAIT_SECONDS}s 内未就绪，仅保持会话；请手动检查 systemctl status docker"
        break
    fi
    sleep 2
done

# 2) 确保基础服务在运行（已在跑时为幂等空操作）
if docker info >/dev/null 2>&1; then
    if (cd "$REPO_DIR" && docker compose -f compose.infra.yml up -d db minio); then
        log "基础服务状态："
        (cd "$REPO_DIR" && docker compose -f compose.infra.yml ps --format '  {{.Name}}  {{.Status}}') || true
    else
        log "启动基础服务失败，请检查 compose.infra.yml 与 .env"
    fi
fi

# 3) 持有会话，避免发行版被回收（SLEEP_SECONDS 同时作为进程标记）
exec sleep "$SLEEP_SECONDS"
