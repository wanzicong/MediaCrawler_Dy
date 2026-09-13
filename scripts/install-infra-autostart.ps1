[CmdletBinding()]
param(
    [string]$TaskName = "MediaCrawler-Infra",
    [string]$Distro = "Ubuntu",
    [switch]$Remove
)

# 注册/卸载登录自启动任务：登录 Windows 后自动执行 scripts/infra-keepalive.sh，
# 把 WSL 发行版钉住并拉起 db / minio，避免后端在开发过程中遇到
# "connection timeout expired"（WSL 回收发行版会连带停掉容器）。
#
# 任务直接运行 wsl.exe（而不是再包一层 PowerShell）：任务实例本身就是那个常驻
# 会话，窗口隐藏、时长不限，进程退出时还会自动重试 3 次。

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$keepAliveScript = Join-Path $PSScriptRoot "infra-keepalive.sh"

function ConvertTo-WslPath {
    param([Parameter(Mandatory)][string]$WindowsPath)

    if ($WindowsPath -match '^([A-Za-z]):\\(.*)$') {
        $drive = $matches[1].ToLowerInvariant()
        $rest = $matches[2].Replace('\', '/')
        return "/mnt/$drive/$rest"
    }
    throw "无法把 Windows 路径转换为 WSL 路径：$WindowsPath"
}

if ($Remove) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Output "未找到计划任务 $TaskName，无需删除"
        return
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Output "已删除计划任务 $TaskName"
    return
}

if (-not (Test-Path -LiteralPath $keepAliveScript)) {
    throw "缺少脚本：$keepAliveScript"
}

$wslScriptPath = ConvertTo-WslPath -WindowsPath $keepAliveScript
$action = New-ScheduledTaskAction `
    -Execute "wsl.exe" `
    -Argument "-d $Distro -e bash $wslScriptPath"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -Hidden

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "登录后拉起 WSL 里的基础服务（db / minio）并保持发行版常驻；卸载用本脚本 -Remove" `
    -Force | Out-Null

Write-Output "已注册登录自启动任务：$TaskName"
Write-Output "  执行：wsl.exe -d $Distro -e bash $wslScriptPath"
Write-Output "  立即验证：Start-ScheduledTask -TaskName $TaskName"
Write-Output "  查看状态：Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
Write-Output "  卸载：.\scripts\install-infra-autostart.ps1 -Remove"
