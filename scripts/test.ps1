[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArguments
)

$ErrorActionPreference = "Stop"
$taskRepositoryRoot = Split-Path -Parent $PSScriptRoot

& (Join-Path $PSScriptRoot "prepare-test-database.ps1")

Push-Location $taskRepositoryRoot
try {
    uv run pytest @PytestArguments
    if ($LASTEXITCODE -ne 0) { throw "Pytest failed." }
}
finally {
    Pop-Location
}
