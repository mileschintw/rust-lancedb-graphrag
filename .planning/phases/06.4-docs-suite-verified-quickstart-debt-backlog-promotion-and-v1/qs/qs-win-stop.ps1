#Requires -Version 5.1
<#
.SYNOPSIS
  Stops the processes qs-win-start.ps1 launched, or (with -PortsOnly) checks that nothing
  listens on the ports the fresh clone binds (06.4 plan 08, D-220, D-230, W-2).

.DESCRIPTION
  Default mode: reads <EvidenceDir>/pids.json (nothing to stop, exit 0, when absent). For
  each wrapper still running whose process is powershell.exe with a command line naming
  qs-win-launch.ps1 (checked with Get-CimInstance Win32_Process, so a reused PID is never
  killed), runs `taskkill /T /F /PID <pid>` from inside PowerShell. That kills the
  cargo/engine, go/gateway and uv/python preflight children, so no orphaned paid request
  continues. With -Role only that role's wrappers are killed. Unless -Role is preflight it
  then asserts that nothing listens on 8080 or 50051 and that no engine.exe runs from under
  the clone path, and exits 1 when either holds.

  -PortsOnly (W-2): kills nothing. Asserts that no process listens on 5432, 16686, 9090,
  3100, 4317, 4318, 8889, 3000, 8080 or 50051 (the clone's compose ports from
  docker-compose.yml, the gateway port and the engine gRPC port), printing each listener's
  port, PID and process name. Exit 1 if any exists.
#>
param(
    [string]$EvidenceDir,
    [string]$Role,
    [switch]$PortsOnly
)
$ErrorActionPreference = 'Stop'

function Get-Listeners {
    param([int[]]$Ports)
    $rows = @()
    $conns = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
            Where-Object { $Ports -contains $_.LocalPort })
    foreach ($key in ($conns | ForEach-Object { "$($_.LocalPort)|$($_.OwningProcess)" } | Sort-Object -Unique)) {
        $port, $ownerPid = $key -split '\|'
        $proc = Get-Process -Id ([int]$ownerPid) -ErrorAction SilentlyContinue
        $name = if ($proc) { $proc.ProcessName } else { '<unknown>' }
        $rows += [pscustomobject]@{ Port = [int]$port; Pid = [int]$ownerPid; Process = $name }
    }
    return $rows
}

if ($PortsOnly) {
    $ports = @(5432, 16686, 9090, 3100, 4317, 4318, 8889, 3000, 8080, 50051)
    $listeners = @(Get-Listeners $ports)
    if ($listeners.Count -eq 0) {
        Write-Host "PORTS FREE: nothing listens on $($ports -join ', ')"
        exit 0
    }
    foreach ($l in $listeners) {
        Write-Host ("LISTEN port={0} pid={1} process={2}" -f $l.Port, $l.Pid, $l.Process)
    }
    Write-Host "PORTS BUSY: $($listeners.Count) listener(s); a dev engine, gateway or container would answer instead of the clone"
    exit 1
}

if (-not $EvidenceDir) { throw '-EvidenceDir is required unless -PortsOnly is given' }
$pidsFile = Join-Path $EvidenceDir 'pids.json'
if (-not (Test-Path -LiteralPath $pidsFile)) {
    Write-Host 'nothing to stop: no pids.json'
    exit 0
}
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$raw = [System.IO.File]::ReadAllText($pidsFile, $Utf8NoBom)
$entries = @()
if ($raw.Trim().Length -gt 0) {
    # Unwrap the {"value":[...],"Count":n} object that Windows PowerShell 5.1 writes for a
    # one-element array, so an older pids.json still names every wrapper.
    foreach ($x in (ConvertFrom-Json -InputObject $raw)) {
        if ($x.PSObject.Properties['value'] -and $x.PSObject.Properties['Count']) { $entries += @($x.value) }
        else { $entries += $x }
    }
}
if ($Role) { $entries = @($entries | Where-Object { $_.role -eq $Role }) }

$killed = 0
foreach ($e in $entries) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($e.pid)" -ErrorAction SilentlyContinue
    if (-not $proc) { Write-Host "role=$($e.role) pid=$($e.pid): already gone"; continue }
    if ($proc.Name -ne 'powershell.exe' -or -not $proc.CommandLine -or $proc.CommandLine -notlike '*qs-win-launch.ps1*') {
        Write-Host "role=$($e.role) pid=$($e.pid): PID now belongs to another process ($($proc.Name)); not killed"
        continue
    }
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & taskkill /T /F /PID $e.pid 2>&1 | Out-Null
    $ErrorActionPreference = $previous
    Write-Host "role=$($e.role) pid=$($e.pid): killed (taskkill /T /F)"
    $killed++
}
Write-Host "stopped $killed wrapper(s)"

if ($Role -eq 'preflight') { exit 0 }

Start-Sleep -Seconds 2
$failed = $false
$left = @(Get-Listeners @(8080, 50051))
foreach ($l in $left) {
    Write-Host ("STILL LISTENING port={0} pid={1} process={2}" -f $l.Port, $l.Pid, $l.Process)
    $failed = $true
}
$clones = @($entries | ForEach-Object { $_.clone } | Where-Object { $_ } | Sort-Object -Unique)
foreach ($c in $clones) {
    $prefix = ([System.IO.Path]::GetFullPath($c)).TrimEnd('\') + '\'
    $engines = @(Get-CimInstance Win32_Process -Filter "Name='engine.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase) })
    foreach ($p in $engines) {
        Write-Host "ENGINE STILL RUNNING pid=$($p.ProcessId) path=$($p.ExecutablePath)"
        $failed = $true
    }
}
if ($failed) { exit 1 }
Write-Host 'verified: nothing listens on 8080 or 50051 and no engine.exe runs from the clone'
exit 0
