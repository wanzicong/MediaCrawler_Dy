# 海外 VPS 代理直连 Docker Hub（一劳永逸方案）

> ⚠️ **此方案已被替代**：最终采用的是 `../wsl-proxy/`（在 WSL 内直接运行 mihomo，
> 复用你已有的代理订阅，无需购买 VPS、无需配置 Windows 防火墙）。本目录保留作为
> 「没有现成代理订阅」时的备选路线。

本目录提供两段式配置，让本机 WSL 里的 Docker 通过海外轻量服务器代理**直连 Docker Hub**，
彻底摆脱公共镜像站（daocloud 等）的带宽墙。一次配置长期生效，覆盖未来任何新镜像。

## 第一步：买服务器（预算 ¥200~400/年）

- **推荐**：腾讯云轻量应用服务器 Lighthouse 海外区（香港/新加坡/东京），2核4G、30M 带宽，
  大促价约 **199 元/年**（以官网实时价为准）：
  - 官方活动页：<https://cloud.tencent.com/act/pro/lhsp2025>
  - 参考价格来源：[618 海外节点 199 元/年](https://www.liuzhanwu.com/125269.html)、
    [腾讯云 618 活动汇总](https://www.gwvpsceping.com/18588.html#1)
- 备选：阿里云轻量应用服务器海外区（价格见 [2026 阿里云价格表](https://developer.aliyun.com/article/1704130#1#1)）
- 区域选择：香港延迟最低、带宽到大陆通常最好；新加坡/东京次之
- 系统选 **Ubuntu 22.04/24.04**（脚本按 Ubuntu 编写）

> ⚠️ 购买后**必须**在云控制台「防火墙 / 安全组」里放行 **TCP 1080**（以及默认的 22）。
> 腾讯云 Lighthouse 有自带防火墙，光改服务器内 ufw 不够。

## 第二步：在服务器上装代理

SSH 登录服务器（root），执行：

```bash
bash install-proxy.sh          # 默认端口 1080；可传参改端口
```

脚本会自动：安装 xray-core → 生成随机密码 → 配置 HTTP 代理（带账号认证）→ 放行防火墙 →
自测访问 `registry-1.docker.io`。最后会打印一行汇总信息，**记下来**：

```
IP:   <服务器公网IP>
PORT: 1080
USER: docker
PASS: <随机密码>
```

## 第三步：在本机 WSL 里配置 dockerd

回到本机 WSL Ubuntu，在项目根目录执行：

```bash
bash scripts/vps-proxy/configure-local.sh <IP> 1080 docker <PASS>
```

脚本会自动：备份原 daemon.json → 写入代理配置（`ghcr.io` / `mcr.microsoft.com` 保持直连，
不绕代理）→ 重启 docker → 实测拉取 `hello-world` 和 `alpine:3.19` 验证速度。

完成后所有 `docker pull` / `docker compose up` 都直连 Docker Hub，速度取决于服务器带宽
（30M ≈ 3~4MB/s，比 daocloud 的 0.5~2.6MB/s 快且稳定）。

## 常见问题

- **拉取还是慢？** 先确认服务器控制台防火墙放行了 1080；再在服务器上跑
  `curl -x http://docker:<PASS>@127.0.0.1:1080 -sI https://registry-1.docker.io/v2/` 看是否 401。
- **想换密码？** 重新执行 install-proxy.sh（会重新生成并覆盖配置）。
- **拉 ghcr/mcr 镜像慢？** 这两个源本网络本来可达，若也想走代理，把
  `configure-local.sh` 里 no-proxy 一行中的 `ghcr.io,mcr.microsoft.com` 删掉即可。
- **以后不想要代理了？** 恢复备份：`sudo cp /etc/docker/daemon.json.bak-* /etc/docker/daemon.json && sudo systemctl restart docker`。

## 可选升级：服务器上跑 Docker Hub 缓存（团队/多机共用）

在服务器上（它本身能直连 Docker Hub）：

```bash
docker run -d --name docker-hub-cache --restart unless-stopped -p 5000:5000 \
  -e REGISTRY_PROXY_REMOTEURL=https://registry-1.docker.io \
  -v registry-cache:/var/lib/registry registry:2
```

然后本机 daemon.json 改为 `"registry-mirrors": ["http://<IP>:5000"]` +
`"insecure-registries": ["<IP>:5000"]`（去掉 proxies 段）。拉过的镜像缓存在服务器上，
多台机器/同事可复用，且不消耗代理流量。适合以后要协作的场景。
