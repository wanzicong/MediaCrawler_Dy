[CmdletBinding()]
param(
    [string]$Distro = "Ubuntu",
    [ValidateRange(10, 900)]
    [int]$WaitSeconds = 180
)

# 确保 WSL 里的基础服务（db / minio）可用，再放行后端启动。
#
# WSL 会在没有活动会话时向发行版发关机请求，systemd 随之停掉
# docker.socket / docker.service，容器（含 Postgres）一并停止，Windows 侧后端
# 于是拿到 psycopg 的 "connection timeout expired"。本脚本做三件事：
#   1. 确认/拉起 wsl 里的常驻会话（scripts/infra-keepalive.sh），钉住发行版；
#   2. 等到 Postgres 端口可连接；
#   3. 用 crawler.api.backend_pre_start 真正验证一次 SQL 连接。
# 只涉及 compose.infra.yml 的 db / minio，不会启动 backend/frontend/mcp/浏览器容器。

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$keepAliveScript = Join-Path $PSScriptRoot "infra-keepalive.sh"
$keepAliveMarker = "infra-keepalive.sh"
$pythonPath = Join-Path $repositoryRoot ".venv\Scripts\python.exe"

function Get-WslKeepAliveProcess {
    # 返回持有常驻会话的 wsl.exe 进程（按命令行里的脚本名识别）
    return Get-CimInstance Win32_Process -Filter "Name='wsl.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine.Contains($keepAliveMarker) }
}

function ConvertTo-WslPath {
    param([Parameter(Mandatory)][string]$WindowsPath)

    if ($WindowsPath -match '^([A-Za-z]):\\(.*)$') {
        $drive = $matches[1].ToLowerInvariant()
        $rest = $matches[2].Replace('\', '/')
        return "/mnt/$drive/$rest"
    }
    throw "无法把 Windows 路径转换为 WSL 路径：$WindowsPath"
}

function Get-PostgresHostPort {
    # 与 scripts/start-local.ps1 一致：以后端实际连接的宿主端口为准
    $line = Get-Content (Join-Path $repositoryRoot ".env") |
        Where-Object { $_ -match "^POSTGRES_HOST_PORT=" } |
        Select-Object -First 1
    if ($line) {
        return [int]$line.Split("=", 2)[1].Trim()
    }
    return 55432
}

function Wait-ForTcpPort {
    param(
        [string]$TargetHost,
        [int]$Port,
        [int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $client = [System.Net.Sockets.TcpClient]::new()
        try {
            $client.Connect($TargetHost, $Port)
            if ($client.Connected) {
                return $true
            }
        }
        catch {
            # 端口尚未监听：继续等待
        }
        finally {
            $client.Dispose()
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

Write-Output "== 基础服务自检（WSL: $Distro，仅 db / minio）=="

if (-not (Test-Path -LiteralPath $keepAliveScript)) {
    throw "缺少常驻脚本：$keepAliveScript"
}

$keepAlive = Get-WslKeepAliveProcess
if ($keepAlive) {
    Write-Output "常驻会话已在运行（PID $($keepAlive.ProcessId -join ', ')）"
}
else {
    $wslScriptPath = ConvertTo-WslPath -WindowsPath $keepAliveScript
    Start-Process `
        -FilePath "wsl.exe" `
        -ArgumentList @("-d", $Distro, "-e", "bash", $wslScriptPath) `
        -WindowStyle Hidden | Out-Null
    Write-Output "已启动常驻会话（隐藏窗口），用于阻止 WSL 回收发行版"
}

$postgresPort = Get-PostgresHostPort
if (-not (Wait-ForTcpPort -TargetHost "127.0.0.1" -Port $postgresPort -TimeoutSeconds $WaitSeconds)) {
    throw "Postgres($postgresPort) 在 $WaitSeconds 秒内仍不可连接；请检查 .\scripts\start-infra.ps1 或 wsl -d $Distro -e docker ps"
}
Write-Output "Postgres 端口 $postgresPort 已就绪"

if (Test-Path -LiteralPath $pythonPath) {
    # 端口通不等于库可用（Postgres 还在初始化时会出现假就绪），这里用项目自带的探测脚本确认
    & $pythonPath -m crawler.api.backend_pre_start
    if ($LASTEXITCODE -ne 0) {
        throw "数据库就绪探测失败（crawler.api.backend_pre_start 退出码 $LASTEXITCODE）"
    }
}
else {
    Write-Warning "未找到虚拟环境 $pythonPath，跳过 SQL 连接探测"
}

$runningContainers = wsl.exe -d $Distro -e docker ps --format "  {{.Names}}  {{.Status}}"
Write-Output "运行中的容器："
$runningContainers | ForEach-Object { Write-Output $_ }
