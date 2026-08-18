[CmdletBinding()]
param(
    [Alias("Service")]
    [ValidateSet("all", "backend", "frontend", "mcp")]
    [string[]]$Services = @("all"),
    [switch]$Restart
)

$ErrorActionPreference = "Stop"
$env:PYTHONUNBUFFERED = "1"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$frontendRoot = Join-Path $projectRoot "frontend"
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$logDirectory = Join-Path $projectRoot "data\logs"
$legacyLogDirectory = Join-Path $logDirectory "legacy"
$runId = Get-Date -Format "yyyyMMdd-HHmmssfff"
$runLogDirectory = Join-Path (Join-Path $logDirectory "runs") $runId
$requestedServices = if ($Services -contains "all") {
    @("backend", "frontend", "mcp")
} else {
    @($Services | Select-Object -Unique)
}

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $runLogDirectory -Force | Out-Null

function Get-PortProcess {
    param([int]$Port)

    return Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
}

function Stop-ProjectService {
    param(
        [string]$Name,
        [int]$Port
    )

    $listener = Get-PortProcess -Port $Port
    if (-not $listener) {
        return
    }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
    $belongsToProject = $false
    $candidate = $process
    for ($depth = 0; $depth -lt 5 -and $candidate; $depth++) {
        if ($candidate.CommandLine -and $candidate.CommandLine -like "*$projectRoot*") {
            $belongsToProject = $true
            break
        }
        if (-not $candidate.ParentProcessId) {
            break
        }
        $candidate = Get-CimInstance Win32_Process -Filter "ProcessId=$($candidate.ParentProcessId)"
    }
    if (-not $belongsToProject) {
        throw "Port $Port is owned by external process $($listener.OwningProcess); refusing to stop it."
    }
    Stop-Process -Id $listener.OwningProcess
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        if (-not (Get-PortProcess -Port $Port)) {
            Write-Output "$Name stopped (PID $($listener.OwningProcess))"
            return
        }
        Start-Sleep -Milliseconds 250
    }
    throw "$Name did not stop before the timeout."
}

function Move-LegacyRootLogs {
    $legacyLogs = @(Get-ChildItem -LiteralPath $projectRoot -File -Filter "*.log")
    if (-not $legacyLogs.Count) {
        return
    }
    New-Item -ItemType Directory -Path $legacyLogDirectory -Force | Out-Null
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    foreach ($log in $legacyLogs) {
        $destinationName = "{0}-{1}{2}" -f $log.BaseName, $timestamp, $log.Extension
        $destination = Join-Path $legacyLogDirectory $destinationName
        try {
            Move-Item -LiteralPath $log.FullName -Destination $destination
            Write-Output "moved legacy log: $($log.Name) -> data/logs/legacy/$destinationName"
        } catch {
            Write-Warning "Could not move in-use log $($log.Name): $($_.Exception.Message)"
        }
    }
}

function Wait-ForPort {
    param(
        [string]$Name,
        [int]$Port
    )

    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        $listener = Get-PortProcess -Port $Port
        if ($listener) {
            Write-Output "$Name started (PID $($listener.OwningProcess), port $Port)"
            return
        }
        Start-Sleep -Milliseconds 250
    }
    throw "$Name did not listen on port $Port before the timeout."
}

function Start-ProjectProcess {
    param(
        [string]$Name,
        [int]$Port,
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory
    )

    $listener = Get-PortProcess -Port $Port
    if ($listener) {
        Write-Output "$Name already running (PID $($listener.OwningProcess), port $Port)"
        return
    }
    Start-Process `
        -FilePath $FilePath `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $runLogDirectory "$Name.out.log") `
        -RedirectStandardError (Join-Path $runLogDirectory "$Name.err.log") | Out-Null
    Wait-ForPort -Name $Name -Port $Port
}

if ($Restart) {
    foreach ($serviceName in $requestedServices) {
        switch ($serviceName) {
            "backend" { Stop-ProjectService -Name "backend" -Port 8000 }
            "frontend" { Stop-ProjectService -Name "frontend" -Port 5173 }
            "mcp" { Stop-ProjectService -Name "mcp" -Port 8766 }
        }
    }
}

Move-LegacyRootLogs

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python virtual environment not found: $pythonPath"
}

if ($requestedServices -contains "backend") {
    $hostPortLine = Get-Content (Join-Path $projectRoot ".env") |
        Where-Object { $_ -match "^POSTGRES_HOST_PORT=" } |
        Select-Object -First 1
    if ($hostPortLine) {
        $env:POSTGRES_PORT = $hostPortLine.Split("=", 2)[1].Trim()
    }
    Start-ProjectProcess `
        -Name "backend" `
        -Port 8000 `
        -FilePath $pythonPath `
        -ArgumentList @("-m", "uvicorn", "crawler.api.main:app", "--host", "0.0.0.0", "--port", "8000") `
        -WorkingDirectory $projectRoot
}

if ($requestedServices -contains "frontend") {
    $nodeDirectory = Split-Path (Get-Command npm.cmd).Source
    $nodePath = Join-Path $nodeDirectory "node.exe"
    $vitePath = Join-Path $projectRoot "node_modules\vite\bin\vite.js"
    Start-ProjectProcess `
        -Name "frontend" `
        -Port 5173 `
        -FilePath $nodePath `
        -ArgumentList @($vitePath, "--host", "0.0.0.0") `
        -WorkingDirectory $frontendRoot
}

if ($requestedServices -contains "mcp") {
    Start-ProjectProcess `
        -Name "mcp" `
        -Port 8766 `
        -FilePath $pythonPath `
        -ArgumentList @(
            "-m", "crawler.mcp", "--transport", "streamable-http",
            "--host", "127.0.0.1", "--port", "8766"
        ) `
        -WorkingDirectory $projectRoot
}

Write-Output "logs: $runLogDirectory"
