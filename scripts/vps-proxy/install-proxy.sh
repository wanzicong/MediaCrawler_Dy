#!/usr/bin/env bash
# install-proxy.sh —— 在海外轻量服务器上安装 xray HTTP 代理
# 用途：给本机 WSL 里的 dockerd 提供直连 Docker Hub 的通道
# 用法（SSH 登录服务器后，以 root 执行）：
#   bash install-proxy.sh [端口]     # 端口默认 1080
set -euo pipefail

PORT="${1:-1080}"
PROXY_USER="docker"
PROXY_PASS="$(openssl rand -hex 12)"

echo "==> 安装 xray-core ..."
bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install

echo "==> 写入 xray 配置（HTTP 入站 :${PORT}，认证 ${PROXY_USER}）..."
mkdir -p /usr/local/etc/xray
cat > /usr/local/etc/xray/config.json <<EOF
{
  "inbounds": [
    {
      "listen": "0.0.0.0",
      "port": ${PORT},
      "protocol": "http",
      "settings": {
        "accounts": [ { "user": "${PROXY_USER}", "pass": "${PROXY_PASS}" } ]
      },
      "streamSettings": { "network": "tcp" }
    }
  ],
  "outbounds": [
    { "protocol": "freedom", "tag": "direct" }
  ]
}
EOF

systemctl restart xray
systemctl enable xray

echo "==> 配置防火墙（放行 SSH 22 和代理端口 ${PORT}）..."
if command -v ufw >/dev/null 2>&1; then
  ufw allow 22/tcp >/dev/null 2>&1 || true
  ufw allow "${PORT}/tcp" >/dev/null 2>&1 || true
  ufw --force enable >/dev/null 2>&1 || true
else
  echo "    （未安装 ufw，请务必在云控制台安全组/防火墙放行 TCP ${PORT}）"
fi

echo "==> 自测代理能否访问 Docker Hub ..."
IP="$(curl -s -m 10 https://api.ipify.org || hostname -I | awk '{print $1}')"
code="$(curl -s -o /dev/null -w '%{http_code}' -m 15 -x "http://${PROXY_USER}:${PROXY_PASS}@127.0.0.1:${PORT}" https://registry-1.docker.io/v2/ || true)"
echo "    代理访问 registry-1.docker.io/v2/ => HTTP ${code}（401 属正常，说明代理已通）"

cat <<SUMMARY

=======================================================
 代理已就绪。请把以下信息记下来，回本机 WSL 执行：

   IP:   ${IP}
   PORT: ${PORT}
   USER: ${PROXY_USER}
   PASS: ${PROXY_PASS}

 本机执行：
   bash scripts/vps-proxy/configure-local.sh ${IP} ${PORT} ${PROXY_USER} ${PROXY_PASS}

 注意：
   - 腾讯云 Lighthouse 需在控制台「防火墙」里额外放行 TCP ${PORT}
   - PASS 已明文写入本文件运行输出，若泄露可重跑本脚本重新生成
=======================================================
SUMMARY
