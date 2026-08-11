# Douyin Crawler Full Stack

本项目以 FastAPI 官方 `full-stack-fastapi-template` 0.10.0 为底座，保留其
FastAPI、React、JWT、SQLModel/PostgreSQL、Alembic、Docker Compose 和 CI/CD
体系，并将 `MediaCrawler` 的抖音请求逻辑重构为纯 HTTP API 服务。

抖音浏览器操作**只允许 CDP**：服务可以连接一个已开启远程调试的
Chrome/Edge，也可以在本机启动 Chrome/Edge 后再通过 CDP 连接。CDP 连接失败时
任务直接失败，不会回退到 `chromium.launch()` 或持久化 Playwright 标准模式。

> 抖音适配代码沿用 MediaCrawler 的 NON-COMMERCIAL LEARNING LICENSE 1.1，
> 仅限非商业学习与研究；不得大规模抓取、干扰平台运营或用于违法用途。
> 官方 Full Stack FastAPI Template 自身仍遵循根目录 MIT `LICENSE`。

## 抖音任务 API

所有接口均在 `/api/v1/douyin` 下并使用模板原有 JWT 鉴权：

- `POST /tasks`：创建 search/detail/creator/liked/collected 任务。
- `GET /tasks`、`GET /tasks/{id}`：查看任务历史和进度。
- `POST /tasks/{id}/cancel`：取消任务。
- `POST /tasks/{id}/resume`：从持久化断点继续爬取、视频下载和字幕。
- `GET /tasks/{id}/qrcode`：获取当前任务的扫码登录二维码。
- `GET /tasks/{id}/awemes`：分页读取作品。
- `GET /tasks/{id}/comments`：分页读取评论。
- `POST /tasks/{id}/awemes/{aweme_id}/comments/recrawl`：为单个视频创建评论重爬任务。
- `POST /tasks/{id}/awemes/{aweme_id}/creator/crawl`：从视频发现作者并创建作者作品任务。
- `GET /tasks/{id}/actions`：分页读取点赞/收藏关系。

搜索任务示例：

```json
{
  "crawl_type": "search",
  "login_type": "qrcode",
  "keywords": ["FastAPI"],
  "max_awemes": 10,
  "fetch_comments": true,
  "fetch_sub_comments": false,
  "max_comments_per_aweme": 10,
  "concurrency": 1,
  "request_delay_level": "steady"
}
```

`request_delay_level` 支持 `fast`（随机 1–2 秒）、`steady`（随机 3–6 秒）和
`ultra_steady`（随机 6–12 秒）。每次请求都会在对应范围内重新随机等待；旧客户端仍可
传递 `request_interval_seconds`，它会作为最小等待下限保留兼容性。

Cookie 仅存在于运行任务的内存对象中，不写入数据库、不出现在任务响应或日志中。
创作者资料遵循源项目隐私边界，不落库；数据库只保存作品、脱敏评论和匿名化账号互动。

任务详情的作品列表支持按视频查看已保存评论、重新爬取该视频评论，以及抓取该视频作者
的其他作品。后两种操作会创建独立任务，保留来源任务结果并自动进入新任务详情页。
“视频作者作品”任务只在运行时从视频详情提取原始作者标识，标识不会写入任务配置、
断点、数据库、日志或 API 响应。

## 中断恢复

任务会持久化当前阶段和安全断点。API 服务退出、浏览器异常、网络失败或用户取消后，
可以继续使用原任务 ID 和已经落库的数据：

```json
{
  "resume_crawl": true,
  "resume_media": true,
  "cookies": "可选，仅本次恢复使用"
}
```

- 关键词任务保存关键词序号、页码和中断页待补评论。
- 指定作品保存已完成目标索引，恢复时只处理剩余作品。
- 创作者、点赞和收藏任务保存分页游标及中断页。
- 视频与字幕恢复会扫描任务全部作品；本地文件或 MinIO 对象已经完成时直接跳过，缺失、
  失败和服务重启中断项会重新排队。
- 两个布尔字段都省略时，服务根据任务阶段自动选择恢复范围。

Cookie、Token 和浏览器登录信息不会进入断点。原任务使用 Cookie 登录时可以在恢复请求
重新提交；留空时复用 CDP 浏览器登录态，登录态失效则进入扫码流程。

## 视频下载与字幕

任务支持以下媒体配置：

```json
{
  "download_media": true,
  "translate_subtitles": true,
  "media_processing_mode": "immediate",
  "media_storage": "minio",
  "transcription_language": "auto"
}
```

- `immediate`：每个作品入库后立即在后台下载和生成字幕，爬虫继续抓取其他作品。
- `batch`：全部作品抓取完成后批量下载并生成字幕。
- `media_storage`：当前任务使用 `local`（本地服务器）或 `minio`（对象存储）；省略时
  使用服务端 `MEDIA_STORAGE_BACKEND` 默认值。
- `translate_subtitles=true` 会自动启用视频下载。

### 视频存储

本地模式把视频保存到 `MEDIA_OUTPUT_DIR`。MinIO 模式只在本机留下下载暂存文件，上传
成功后即删除暂存文件；数据库仅保存 bucket 和对象键，不保存访问密钥。无论使用哪种
存储，浏览器端都通过私有媒体接口下载或流式预览，MinIO bucket 不需要公开。任务详情
中的播放按钮支持浏览器 Range 请求和进度条拖动，不会先把整段视频下载到内存。

启动项目自带的持久化 MinIO 容器：

```powershell
docker compose -f compose.yml -f compose.override.yml -f compose.storage.yml up -d minio
```

对象 API 为 `http://127.0.0.1:9100`，管理控制台为 `http://127.0.0.1:9101`；端口仅
监听本机。数据保存在 `minio-data` Docker 卷中。首次使用前请在 `.env.local` 设置强
随机的 `MINIO_ACCESS_KEY` 和 `MINIO_SECRET_KEY`。本机后端连接 `127.0.0.1:9100`，
Compose 后端由覆盖配置自动改用容器内部地址 `minio:9000`。

```dotenv
MEDIA_STORAGE_BACKEND=minio
MEDIA_PREVIEW_TTL_SECONDS=300
MEDIA_MIGRATION_CONCURRENCY=2
MINIO_ENDPOINT=127.0.0.1:9100
MINIO_ACCESS_KEY=replace-me
MINIO_SECRET_KEY=replace-with-a-long-random-secret
MINIO_SECURE=false
MINIO_BUCKET=douyin-media
```

创建任务时仍可用 `media_storage` 覆盖全局默认值。服务端没有配置 MinIO、MinIO 不可用
或上传失败时，对应媒体任务会进入 `failed`，不会静默回退到本地存储。

已经下载到本地的视频可以在任务详情中选择“上传本地视频到 MinIO”。该操作使用独立
异步队列：系统先保留本地文件完成上传，再从 MinIO 完整回读对象并核对文件大小和
SHA-256；MinIO 上传响应或 ETag 本身不视为成功。只有完整性校验和数据库存储切换都
成功后才删除本地文件。上传、校验或数据库切换失败时仍使用原本地文件；删除因文件
占用失败时显示 `cleanup_pending`，可重试且不会重复上传。服务重启会自动恢复未完成
的上传、切换或清理。`MEDIA_MIGRATION_CONCURRENCY` 控制迁移并发量，默认 2。

字幕严格调用 OpenAI 兼容的远程 `/v1/audio/transcriptions` 服务，不包含本地模型，
也不会在远程失败后回退本地。配置示例：

```dotenv
WHISPER_API_BASE_URL=https://speech.example.com
WHISPER_API_KEY=replace-me
WHISPER_API_MODEL=whisper-1
WHISPER_API_TIMEOUT=1800
WHISPER_API_CONCURRENCY=5
FFMPEG_BINARY=ffmpeg
WHISPER_AUDIO_BITRATE_KBPS=64
WHISPER_AUDIO_PREPROCESS_TIMEOUT=300
```

连接、鉴权、超时、非 2xx 响应或返回格式错误都会把对应字幕任务标记为 `failed`，
错误可在前端查看并重试。API Key 仅从服务端环境变量读取，不进入任务参数、数据库、
日志或前端响应。非本机 API 必须使用 HTTPS，本机开发可使用
`http://127.0.0.1:9000`。

视频不会再以完整 MP4 直接上传。后端先用 FFmpeg 提取 16 kHz 单声道压缩音轨，再把
音频交给远程 API，避免大视频在远程服务忙碌时发生上传超时；语音识别仍完全由远程
服务执行，不安装、不调用本地 Whisper，也没有本地回退。Docker 后端构建会从原项目
`mediacrawler:latest` 镜像复用 FFmpeg，不依赖 Debian 软件源重复下载。媒体任务采用
跨任务公平限流，一个包含大量视频的任务不会阻塞后续小任务；
CDP 单任务限制只覆盖实际浏览器阶段，下载和字幕不会长期占用浏览器槽。

本地私密值可放在不会提交 Git 的 `.env.local`，该文件会覆盖 `.env`，Docker Compose
也会在文件存在时自动加载。当前开发环境已从参考项目复制 Whisper 服务配置到该文件。

媒体接口：

- `GET /api/v1/douyin/tasks/{id}/media`：读取下载和字幕进度、错误及字幕正文。
- `GET /api/v1/douyin/tasks/{id}/media-summary`：读取状态汇总。
- `POST /api/v1/douyin/tasks/{id}/media/process`：对已完成爬取任务补做视频下载和远程字幕。
- `POST /api/v1/douyin/tasks/{id}/media/retry`：重试失败任务。
- `POST /api/v1/douyin/tasks/{id}/media/migrate-to-minio`：把全部或指定本地视频完整
  校验后迁移到 MinIO，并在数据库切换成功后删除本地文件。
- `POST /api/v1/douyin/library/media/migrate-to-minio`：按照资源库当前的关键词、任务、
  创作者、标签和字幕筛选条件，跨任务批量迁移全部匹配的本地视频。
- `POST /api/v1/douyin/tasks/{id}/media/{asset_id}/retranslate`：强制重新生成字幕。
- `GET /api/v1/douyin/tasks/{id}/media/{asset_id}/file`：鉴权下载已保存视频。
- `POST /api/v1/douyin/tasks/{id}/media/{asset_id}/preview-session`：鉴权创建短时预览会话。
- `GET /api/v1/douyin/tasks/{id}/media/{asset_id}/preview`：使用短时 HttpOnly Cookie
  流式播放本地或 MinIO 视频，支持单段 `Range` 请求。

预览会话默认有效 300 秒，可通过 `MEDIA_PREVIEW_TTL_SECONDS` 调整。播放授权绑定任务和
媒体记录，令牌不会进入 URL、数据库、日志或 API JSON 响应。

## MCP 接入

MCP 是现有 FastAPI 的网关，所有工具通过模板原有登录接口鉴权并复用同一套任务、
权限和数据库，不会启动第二套爬虫状态。

### 外部智能体可直接使用的 JSON

先确保 Compose 服务已启动，然后把下面配置原样复制到支持 MCP 的智能体工具中：

```json
{
  "mcpServers": {
    "douyin-crawler": {
      "type": "streamable-http",
      "url": "http://127.0.0.1:8766/mcp"
    }
  }
}
```

部分客户端把相同协议类型命名为 `http`；如果客户端不识别 `streamable-http`，只替换
`type`，地址保持不变：

```json
{
  "mcpServers": {
    "douyin-crawler": {
      "type": "http",
      "url": "http://127.0.0.1:8766/mcp"
    }
  }
}
```

这份客户端 JSON **不需要 API Key、Authorization Header、登录账号或密码**。MCP
端口只监听本机 `127.0.0.1`，MCP 容器会在服务端使用项目现有环境变量登录 FastAPI；
账号和密码不会发送给外部智能体，也不应复制进客户端配置。当前 Compose 默认读取
`FIRST_SUPERUSER` 和 `FIRST_SUPERUSER_PASSWORD`，如果设置了
`MCP_API_USERNAME`/`MCP_API_PASSWORD` 则优先使用后者。它们都只属于服务端私密
配置，不是上述 MCP JSON 的缺失字段。

连接前可在浏览器访问 `http://127.0.0.1:8766/health`，返回 `{"status":"ok"}` 即表示
MCP 服务已就绪。MCP 协议地址是 `http://127.0.0.1:8766/mcp`，不能用健康检查地址
替代。这个配置适用于与 Docker 运行在同一台 Windows 主机上的智能体；其他机器不能
直接访问，因为端口有意只绑定回环地址。

媒体迁移工具 `migrate_douyin_media_to_minio` 接受任务 ID 和可选资产 ID 列表；列表
为空时迁移任务下全部符合条件的本地视频。工具不接受或返回 MinIO 凭据和本地路径。

不使用 Docker、需要由 MCP 客户端直接拉起进程时，可使用 stdio 模式：

```powershell
Set-Location backend
uv run python -m app.mcp_server
```

本地手动启动 Streamable HTTP 模式：

```powershell
uv run python -m app.mcp_server --transport streamable-http
```

MCP 暴露创建/查询/取消/恢复任务、单视频评论重爬、视频作者作品抓取、完成后媒体处理、
媒体进度、失败重试、重新翻译、作品/评论/互动分页读取、标签查询与历史标签同步工具。
其中 `resume_douyin_task` 与 Web 页面和 REST API 共用同一断点和状态机。
详细设计见 `docs/媒体处理与MCP设计.md`。

## 本地服务与日志

Windows 本地开发统一使用下面的脚本启动或重启后端、前端和 MCP：

```powershell
.\scripts\start-local.ps1 -Services all -Restart
```

也可以通过 `-Services backend`、`frontend` 或 `mcp` 只处理单个服务。脚本将每次启动的
标准输出和错误输出写入独立的 `data/logs/runs/<时间戳>` 目录，并把历史遗留在项目
根目录的 `*.log` 文件迁移到 `data/logs/legacy`。这样既不会污染项目根目录，也不会在
重启时覆盖上一轮日志。启动命令和业务代码都不应再使用相对于项目根目录的日志路径。

## CDP 配置

浏览器只允许通过 CDP 控制。服务级默认模式由下面的配置决定，创建任务时还可
通过 `browser_mode` 单独覆盖：

```dotenv
DOUYIN_BROWSER_MODE=remote  # 默认连接 Docker CDP；也可设为 local
```

### 本机浏览器

直接在 Windows 运行后端时，`local` 模式会自动查找本机 Chrome/Edge，并使用
`browser_data/douyin` 独立用户目录启动远程调试。也可以先自行启动浏览器：

```powershell
chrome.exe --remote-debugging-port=9222 --user-data-dir=D:\browser-data\douyin
```

然后设置：

```dotenv
DOUYIN_CDP_CONNECT_EXISTING=true
DOUYIN_CDP_HOST=127.0.0.1
DOUYIN_CDP_PORT=9222
```

Docker 后端无法直接控制宿主机普通浏览器进程，开发环境应把主机改为
`host.docker.internal` 并连接宿主机已开启 CDP 的浏览器。CDP 端口等同浏览器完全
控制权限，请勿暴露到公网。

### Docker 远程浏览器

项目提供独立的有头 Chrome 服务，包含 Xvfb、noVNC 和持久化登录目录。构建并
启动浏览器服务：

```powershell
docker compose -f compose.yml -f compose.override.yml -f compose.browser.yml build douyin-browser
docker compose -f compose.yml -f compose.override.yml -f compose.browser.yml up -d douyin-browser
```

本机运行的后端通过 `127.0.0.1:9223` 连接它；Compose 中的后端通过
`douyin-browser:9222` 连接。noVNC 页面为
`http://127.0.0.1:6081/vnc.html?autoconnect=1&resize=scale`。首次扫码后的登录态保存在
`douyin-browser-profile` 卷中，重建容器不会丢失。

全局默认使用远程浏览器时设置：

```dotenv
DOUYIN_BROWSER_MODE=remote
DOUYIN_REMOTE_CDP_HOST=127.0.0.1
DOUYIN_REMOTE_CDP_PORT=9223
```

单个 API 任务可覆盖默认值：

```json
{
  "crawl_type": "search",
  "keywords": ["FastAPI"],
  "browser_mode": "remote"
}
```

任务只接受 `local` 或 `remote`，远程主机和端口只能由服务端配置，不能通过请求
传入。CDP 与无密码 noVNC 均只绑定宿主机回环地址，禁止改成公网监听。

## 数据库迁移与启动

本地运行需要 Python 3.10+、`uv`、Node.js（用于执行从源项目复制的
`a_bogus` JavaScript 签名逻辑）和 PostgreSQL；Docker 后端镜像已内置 Node.js。

```powershell
docker compose up -d db
$env:POSTGRES_PORT=55432
Set-Location backend
uv run alembic upgrade head
uv run fastapi run app/main.py
```

首次运行仍需按官方模板修改 `.env` 中的 `SECRET_KEY`、数据库密码和管理员密码。

## 官方模板能力

<a href="https://github.com/fastapi/full-stack-fastapi-template/actions?query=workflow%3A%22Test+Docker+Compose%22" target="_blank"><img src="https://github.com/fastapi/full-stack-fastapi-template/workflows/Test%20Docker%20Compose/badge.svg" alt="Test Docker Compose"></a>
<a href="https://github.com/fastapi/full-stack-fastapi-template/actions?query=workflow%3A%22Test+Backend%22" target="_blank"><img src="https://github.com/fastapi/full-stack-fastapi-template/workflows/Test%20Backend/badge.svg" alt="Test Backend"></a>
<a href="https://coverage-badge.samuelcolvin.workers.dev/redirect/fastapi/full-stack-fastapi-template" target="_blank"><img src="https://coverage-badge.samuelcolvin.workers.dev/fastapi/full-stack-fastapi-template.svg" alt="Coverage"></a>

## Technology Stack and Features

- ⚡ [**FastAPI**](https://fastapi.tiangolo.com) for the Python backend API.
  - 🧰 [SQLModel](https://sqlmodel.tiangolo.com) for the Python SQL database interactions (ORM).
  - 🔍 [Pydantic](https://docs.pydantic.dev), used by FastAPI, for the data validation and settings management.
  - 💾 [PostgreSQL](https://www.postgresql.org) as the SQL database.
- 🚀 [React](https://react.dev) for the frontend.
  - 💃 Using TypeScript, hooks, [Vite](https://vitejs.dev), and other parts of a modern frontend stack.
  - 🎨 [Tailwind CSS](https://tailwindcss.com) and [shadcn/ui](https://ui.shadcn.com) for the frontend components.
  - 🤖 An automatically generated frontend client.
  - 🧪 [Playwright](https://playwright.dev) for End-to-End testing.
  - 🦇 Dark mode support.
- 🐋 [Docker Compose](https://www.docker.com) for development and production.
- 🔒 Secure password hashing by default.
- 🔑 JWT (JSON Web Token) authentication.
- 📫 Email based password recovery.
- 📬 [Mailcatcher](https://mailcatcher.me) for local email testing during development.
- ✅ Tests with [Pytest](https://pytest.org).
- 📞 [Traefik](https://traefik.io) as a reverse proxy / load balancer.
- 🚢 Deployment instructions using Docker Compose, including how to set up a frontend Traefik proxy to handle automatic HTTPS certificates.
- 🏭 CI (continuous integration) and CD (continuous deployment) based on GitHub Actions.

### Dashboard Login

[![API docs](img/login.png)](https://github.com/fastapi/full-stack-fastapi-template)

### Dashboard - Admin

[![API docs](img/dashboard.png)](https://github.com/fastapi/full-stack-fastapi-template)

### Dashboard - Items

[![API docs](img/dashboard-items.png)](https://github.com/fastapi/full-stack-fastapi-template)

### Dashboard - Dark Mode

[![API docs](img/dashboard-dark.png)](https://github.com/fastapi/full-stack-fastapi-template)

### Interactive API Documentation

[![API docs](img/docs.png)](https://github.com/fastapi/full-stack-fastapi-template)

## How To Use It

You can **just fork or clone** this repository and use it as is.

✨ It just works. ✨

### How to Use a Private Repository

If you want to have a private repository, GitHub won't allow you to simply fork it as it doesn't allow changing the visibility of forks.

But you can do the following:

- Create a new GitHub repo, for example `my-full-stack`.
- Clone this repository manually, set the name with the name of the project you want to use, for example `my-full-stack`:

```bash
git clone git@github.com:fastapi/full-stack-fastapi-template.git my-full-stack
```

- Enter into the new directory:

```bash
cd my-full-stack
```

- Set the new origin to your new repository, copy it from the GitHub interface, for example:

```bash
git remote set-url origin git@github.com:octocat/my-full-stack.git
```

- Add this repo as another "remote" to allow you to get updates later:

```bash
git remote add upstream git@github.com:fastapi/full-stack-fastapi-template.git
```

- Push the code to your new repository:

```bash
git push -u origin master
```

### Update From the Original Template

After cloning the repository, and after doing changes, you might want to get the latest changes from this original template.

- Make sure you added the original repository as a remote, you can check it with:

```bash
git remote -v

origin    git@github.com:octocat/my-full-stack.git (fetch)
origin    git@github.com:octocat/my-full-stack.git (push)
upstream    git@github.com:fastapi/full-stack-fastapi-template.git (fetch)
upstream    git@github.com:fastapi/full-stack-fastapi-template.git (push)
```

- Pull the latest changes without merging:

```bash
git pull --no-commit upstream master
```

This will download the latest changes from this template without committing them, that way you can check everything is right before committing.

- If there are conflicts, solve them in your editor.

- Once you are done, commit the changes:

```bash
git merge --continue
```

### Configure

You can then update configs in the `.env` files to customize your configurations.

Before deploying it, make sure you change at least the values for:

- `SECRET_KEY`
- `FIRST_SUPERUSER_PASSWORD`
- `POSTGRES_PASSWORD`

You can (and should) pass these as environment variables from secrets.

Read the [deployment.md](./deployment.md) docs for more details.

### Generate Secret Keys

Some environment variables in the `.env` file have a default value of `changethis`.

You have to change them with a secret key, to generate secret keys you can run the following command:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copy the content and use that as password / secret key. And run that again to generate another secure key.

## How To Use It - Alternative With Copier

This repository also supports generating a new project using [Copier](https://copier.readthedocs.io).

It will copy all the files, ask you configuration questions, and update the `.env` files with your answers.

### Install Copier

You can install Copier with:

```bash
pip install copier
```

Or better, if you have [`pipx`](https://pipx.pypa.io/), you can run it with:

```bash
pipx install copier
```

**Note**: If you have `pipx`, installing copier is optional, you could run it directly.

### Generate a Project With Copier

Decide a name for your new project's directory, you will use it below. For example, `my-awesome-project`.

Go to the directory that will be the parent of your project, and run the command with your project's name:

```bash
copier copy https://github.com/fastapi/full-stack-fastapi-template my-awesome-project --trust
```

If you have `pipx` and you didn't install `copier`, you can run it directly:

```bash
pipx run copier copy https://github.com/fastapi/full-stack-fastapi-template my-awesome-project --trust
```

**Note** the `--trust` option is necessary to be able to execute a [post-creation script](https://github.com/fastapi/full-stack-fastapi-template/blob/master/.copier/update_dotenv.py) that updates your `.env` files.

### Input Variables

Copier will ask you for some data, you might want to have at hand before generating the project.

But don't worry, you can just update any of that in the `.env` files afterwards.

The input variables, with their default values (some auto generated) are:

- `project_name`: (default: `"FastAPI Project"`) The name of the project, shown to API users (in .env).
- `stack_name`: (default: `"fastapi-project"`) The name of the stack used for Docker Compose labels and project name (no spaces, no periods) (in .env).
- `secret_key`: (default: `"changethis"`) The secret key for the project, used for security, stored in .env, you can generate one with the method above.
- `first_superuser`: (default: `"admin@example.com"`) The email of the first superuser (in .env).
- `first_superuser_password`: (default: `"changethis"`) The password of the first superuser (in .env).
- `smtp_host`: (default: "") The SMTP server host to send emails, you can set it later in .env.
- `smtp_user`: (default: "") The SMTP server user to send emails, you can set it later in .env.
- `smtp_password`: (default: "") The SMTP server password to send emails, you can set it later in .env.
- `emails_from_email`: (default: `"info@example.com"`) The email account to send emails from, you can set it later in .env.
- `postgres_password`: (default: `"changethis"`) The password for the PostgreSQL database, stored in .env, you can generate one with the method above.
- `sentry_dsn`: (default: "") The DSN for Sentry, if you are using it, you can set it later in .env.

## Backend Development

Backend docs: [backend/README.md](./backend/README.md).

## Frontend Development

Frontend docs: [frontend/README.md](./frontend/README.md).

## Deployment

Deployment docs: [deployment.md](./deployment.md).

## Development

General development docs: [development.md](./development.md).

This includes using Docker Compose, custom local domains, `.env` configurations, etc.

## Release Notes

Check the file [release-notes.md](./release-notes.md).

## License

The Full Stack FastAPI Template is licensed under the terms of the MIT license.
