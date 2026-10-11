#Requires -Version 5.1
<#
.SYNOPSIS
  Starts qs-win-launch.ps1 for a long-running role (engine, gateway or preflight) detached
  from the caller's job object (06.4 plan 08, D-220, Pitfall 12).

.DESCRIPTION
  The wrapper is created with Win32_Process Create (WMI), whose child leaves the executor's
  job object, so the services, and a long preflight, survive between Bash calls and after
  the executor exits. The command line carries no secret; the launcher reads <Clone>/.env
  itself. Appends {role, attempt, pid, started_utc, clone} to <EvidenceDir>/pids.json.
  qs-win-stop.ps1 reads that file.
#>
param(
    [Parameter(Mandatory = $true)][ValidateSet('engine', 'gateway', 'preflight')][string]$Role,
    [Parameter(Mandatory = $true)][string]$Clone,
    [Parameter(Mandatory = $true)][string]$EvidenceDir,
    [int]$Attempt = 1
)
$ErrorActionPreference = 'Stop'

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$Clone = (Resolve-Path -LiteralPath $Clone).Path
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
$EvidenceDir = (Resolve-Path -LiteralPath $EvidenceDir).Path
$launch = Join-Path $PSScriptRoot 'qs-win-launch.ps1'

# Clear the previous run's markers so a poller never reads a stale result.
$stem = if ($Role -eq 'preflight') { "preflight-$Attempt" } else { $Role }
Remove-Item -LiteralPath (Join-Path $EvidenceDir "$stem.exit"), (Join-Path $EvidenceDir "$Role.refused") `
    -ErrorAction SilentlyContinue

$commandLine = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{0}" -Role {1} -Clone "{2}" -EvidenceDir "{3}" -Attempt {4}' `
    -f $launch, $Role, $Clone, $EvidenceDir, $Attempt

$result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create `
    -Arguments @{ CommandLine = $commandLine; CurrentDirectory = $Clone }
if ($result.ReturnValue -ne 0) {
    throw "Win32_Process Create failed with return value $($result.ReturnValue)"
}

$pidsFile = Join-Path $EvidenceDir 'pids.json'
$entries = @()
if (Test-Path -LiteralPath $pidsFile) {
    $raw = [System.IO.File]::ReadAllText($pidsFile, $Utf8NoBom)
    if ($raw.Trim().Length -gt 0) { $entries = @($raw | ConvertFrom-Json) }
}
$entries += [pscustomobject]@{
    role        = $Role
    attempt     = $Attempt
    pid         = [int]$result.ProcessId
    started_utc = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
    clone       = $Clone
}
[System.IO.File]::WriteAllText($pidsFile, (ConvertTo-Json -InputObject @($entries) -Depth 4), $Utf8NoBom)

Write-Host "started role=$Role attempt=$Attempt wrapper_pid=$($result.ProcessId) evidence=$EvidenceDir"
