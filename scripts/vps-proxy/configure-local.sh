#!/usr/bin/env bash
# configure-local.sh —— 本机（WSL Ubuntu）dockerd 配置，走海外代理直连 Docker Hub
# 用法（在 WSL Ubuntu 里执行）：
#   bash scripts/vps-proxy/configure-local.sh <VPS_IP> <PORT> <USER> <PASS>
# 需要 sudo 权限（会提示输入密码）；执行前请先完成 install-proxy.sh
set -euo pipefail

if [ $# -ne 4 ]; then
  echo "用法: bash configure-local.sh <VPS_IP> <PORT> <USER> <PASS>"
  exit 1
fi
IP="$1"; PORT="$2"; PROXY_USER="$3"; PROXY_PASS="$4"
PROXY="http://${PROXY_USER}:${PROXY_PASS}@${IP}:${PORT}"

echo "==> 备份并写入 /etc/docker/daemon.json ..."
sudo cp /etc/docker/daemon.json "/etc/docker/daemon.json.bak-$(date +%Y%m%d%H%M%S)"
sudo tee /etc/docker/daemon.json >/dev/null <<EOF
{
  "registry-mirrors": [],
  "proxies": {
    "http-proxy":  "${PROXY}",
    "https-proxy": "${PROXY}",
    "no-proxy":    "localhost,127.0.0.1,ghcr.io,mcr.microsoft.com"
  }
}
EOF

echo "==> 重启 docker ..."
sudo systemctl restart docker
sleep 3
sudo systemctl is-active docker

echo "==> 验证 1/2: 拉取 hello-world ..."
docker rmi hello-world >/dev/null 2>&1 || true
time docker pull hello-world

echo "==> 验证 2/2: 拉取 alpine:3.19（未缓存，实测代理带宽）..."
docker rmi alpine:3.19 >/dev/null 2>&1 || true
time docker pull alpine:3.19

cat <<SUMMARY

=======================================================
 完成。现在 docker pull 直连 Docker Hub（经代理）。
 ghcr.io / mcr.microsoft.com 保持本网直连，不绕代理。
 原 daocloud 镜像配置已移除（备份在 daemon.json.bak-*）。
=======================================================
SUMMARY
