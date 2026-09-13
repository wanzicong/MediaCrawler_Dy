[CmdletBinding()]
param()

# 用一致性快照覆盖独立测试库（不改用户库）。
# 原 test-db-prepare 服务已删除，刷新逻辑改为在 db 容器里执行同一份脚本
# （容器自带 pg_dump / pg_restore，脚本随 db 服务挂载到 /usr/local/bin）。
$ErrorActionPreference = "Stop"
$taskRepositoryRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $taskRepositoryRoot ".env"

function Read-DotEnv {
    param([Parameter(Mandatory)][string]$Path)
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
            $values[$matches[1]] = $matches[2].Trim().Trim('"')
        }
    }
    return $values
}

$environment = Read-DotEnv -Path $envFile
foreach ($key in @("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")) {
    if (-not $environment.ContainsKey($key) -or -not $environment[$key]) {
        throw ".env 缺少 $key，无法刷新测试库。"
    }
}

# Windows 侧通常没有 docker CLI（docker 在 WSL 里），自动退回 `wsl -e docker`。
if (Get-Command docker -ErrorAction SilentlyContinue) {
    $docker = @("docker")
}
elseif (Get-Command wsl -ErrorAction SilentlyContinue) {
    $docker = @("wsl", "-e", "docker")
}
else {
    throw "找不到 docker CLI，也无法通过 wsl 调用 docker。"
}

Push-Location $taskRepositoryRoot
try {
    & $docker[0] $docker[1..($docker.Count - 1)] compose -f compose.infra.yml up -d --wait db
    if ($LASTEXITCODE -ne 0) {
        throw "无法启动 db 容器，请检查 compose.infra.yml 与 .env。"
    }
    & $docker[0] $docker[1..($docker.Count - 1)] compose -f compose.infra.yml exec -T db sh /usr/local/bin/prepare-test-database
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to prepare the isolated test database."
    }
}
finally {
    Pop-Location
}
