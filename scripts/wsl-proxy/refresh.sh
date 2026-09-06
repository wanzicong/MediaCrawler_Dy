#!/usr/bin/env bash
# refresh.sh —— 订阅节点更新后，重新生成 mihomo 配置并重启服务
# 前提：tidalab（或其它 clash 客户端）已把最新节点写入 tmp.yaml
set -euo pipefail

SRC="/mnt/c/Users/WANZICONG/AppData/Roaming/tidalab/tmp.yaml"
if [ ! -f "$SRC" ]; then
  echo "找不到 $SRC（tidalab 的运行时配置），请先打开一次 tidalab 让节点下载完成"
  exit 1
fi

python3 - "$SRC" <<'PY'
import sys, yaml
src = sys.argv[1]
dst = "/etc/mihomo/config.yaml"
d = yaml.safe_load(open(src, encoding="utf-8"))
proxies = d.get("proxies") or []
if not proxies:
    print("ERROR: tmp.yaml 中没有节点"); sys.exit(1)
names = [p["name"] for p in proxies]
cfg = {
    "mixed-port": 7890,
    "allow-lan": False,
    "bind-address": "*",
    "mode": "rule",
    "log-level": "info",
    "ipv6": False,
    "proxies": proxies,
    "proxy-groups": [{
        "name": "PROXY",
        "type": "url-test",
        "url": "http://www.gstatic.com/generate_204",
        "interval": 300,
        "tolerance": 50,
        "proxies": names,
    }],
    "rules": ["MATCH,PROXY"],
}
with open(dst, "w", encoding="utf-8") as f:
    yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
print(f"OK: {dst} 已更新, 节点数={len(proxies)}")
PY

chmod 600 /etc/mihomo/config.yaml
systemctl restart mihomo
sleep 3
systemctl is-active mihomo
echo "--- 验证 ---"
curl -s -o /dev/null -m 15 -x http://127.0.0.1:7890 -w "registry-1.docker.io => HTTP %{http_code} (%{time_total}s)\n" https://registry-1.docker.io/v2/
