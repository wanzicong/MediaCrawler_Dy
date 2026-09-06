# WSL 内自建代理（mihomo）直连 Docker Hub —— 已生效方案

**背景**：本机网络被墙 Docker Hub（registry-1.docker.io / auth.docker.io / production.cloudflare.docker.com 全超时），
公共镜像站（daocloud 等）带宽只有 0.5~2.6MB/s。本方案把用户已有的代理订阅（tidalab 的 clash 配置）
搬进 WSL 内运行 **mihomo**（clash meta 的 Linux 内核），dockerd 走本机回环代理直连 Docker Hub。
完全绕开 Windows 防火墙 / WSL 网络限制，一次配置长期生效。

**当前状态（2026-08-30 已验证）**：
- mihomo v1.19.30 作为 systemd 服务运行在 WSL，监听 `127.0.0.1:7890`（HTTP+SOCKS 混合端口）
- 节点来自 `C:\Users\WANZICONG\AppData\Roaming\tidalab\tmp.yaml`（31 个 vmess 节点，url-test 自动选最快）
- `/etc/docker/daemon.json` 已配置 `proxies: http://127.0.0.1:7890`（ghcr.io / mcr.microsoft.com 保持直连）
- 实测：alpine:3.19 拉取 8 秒；postgres:18（~450MB）分钟级；对比镜像站时代：2.5MB 要 3 分钟

## 文件清单

| 文件 | 作用 |
|---|---|
| `/usr/local/bin/mihomo` | mihomo Linux 二进制 |
| `/etc/mihomo/config.yaml` | 生成的代理配置（含节点，权限 600） |
| `/etc/systemd/system/mihomo.service` | systemd 服务（随 WSL 自启） |
| `/etc/docker/daemon.json` | dockerd 代理配置 |
| `scripts/wsl-proxy/refresh.sh` | 订阅更新后重新生成配置并重启 |

## 日常使用

- **拉镜像**：直接 `docker pull` / `docker compose up` 即可，无需任何额外操作；
- **订阅节点更新**（tidalab 刷新订阅后）：
  ```bash
  sudo bash scripts/wsl-proxy/refresh.sh
  ```
- **停止代理**：`sudo systemctl stop mihomo`（dockerd 会回到直连，Docker Hub 将被墙回原样）；
- **查看代理日志**：`journalctl -u mihomo -f`；
- **验证代理状态**：
  ```bash
  curl -x http://127.0.0.1:7890 -sI https://registry-1.docker.io/v2/   # 应返回 401
  ```

## 原理说明

- Windows 上的 tidalab 只是 clash 的 GUI 壳，真实节点在其运行配置 `tmp.yaml` 里；
- mihomo 在 WSL 内监听回环端口，dockerd 的 `proxies` 配置让它经此访问所有 registry；
- 不依赖 Windows 防火墙放行（本机实测 Win10 + WSL2 的入站 TCP 有系统性问题，即使加了规则也丢包，故放弃"WSL→Windows 代理"路线）；
- 无需海外 VPS，完全复用你已有的代理订阅。

## 常见问题

- **拉取突然失败**：多半是订阅过期/节点失效 → 打开一次 tidalab 刷新订阅，然后跑 `refresh.sh`；
- **`refresh.sh` 报找不到 tmp.yaml**：先启动一次 tidalab 让节点下载落盘；
- **想要更快的速度**：代理带宽取决于订阅节点线路，可在 `/etc/mihomo/config.yaml` 里把 `PROXY` 组改为 `select` 手动挑节点（改后 `systemctl restart mihomo`）。
