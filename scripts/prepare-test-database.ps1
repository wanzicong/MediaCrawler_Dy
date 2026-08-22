[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$taskRepositoryRoot = Split-Path -Parent $PSScriptRoot

Push-Location $taskRepositoryRoot
try {
    docker compose --profile test run --rm test-db-prepare
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to prepare the isolated test database."
    }
}
finally {
    Pop-Location
}
