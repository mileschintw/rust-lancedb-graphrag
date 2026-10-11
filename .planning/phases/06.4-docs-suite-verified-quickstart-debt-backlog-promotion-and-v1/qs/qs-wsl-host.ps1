#Requires -Version 5.1
<#
.SYNOPSIS
  Windows-side helper for the WSL fresh-clone run (06.4 plan 10, D-220, D-231, notes 8 and 8c).

.DESCRIPTION
  Always invoke it from Git Bash with MSYS_NO_PATHCONV=1, because its arguments are POSIX paths
  (Git Bash would otherwise rewrite /home/... and /mnt/... into Windows paths).

  Three modes:

  Default  -Clone <wsl path> -EvidenceDir <wsl path>
      Starts `wsl.exe -d Ubuntu -- bash <qs>/qs-wsl-launch.sh <clone> <ev>` with Win32_Process Create
      (WMI), so the process leaves the executor's job object. Writes the wsl.exe PID to
      <ev>/host.pid (Windows form of the evidence dir). That long-lived wsl.exe keeps the distro up
      for the whole live run, and the engine and gateway it hosts outlive the executor.

  -Stop -EvidenceDir <wsl path>
      Reads <ev>/host.pid, confirms with Get-Process that the PID is a `wsl` process (a reused PID
      is never killed) and ends it with Stop-Process -Force. A no-op when host.pid is absent or the
      process is gone. Run qs-wsl-stop.sh first so the engine and gateway groups end cleanly.

  -WriteEnv -Clone <wsl path>
      Reads the User-scope OPENROUTER_API_KEY and pipes it into
      `wsl.exe -d Ubuntu -- bash <qs>/qs-wsl-write-env.sh <clone>`. The key travels on stdin only,
      never in argv or WSLENV. Only the script's printed key length is shown.

  Exit codes: 0 ok; 1 failure; 2 usage; 4 the User-scope key is missing; others come from the
  script that ran inside WSL.
#>
param(
    [string]$Clone,
    [string]$EvidenceDir,
    [switch]$Stop,
    [switch]$WriteEnv
)
$ErrorActionPreference = 'Stop'

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$wsl = Join-Path $env:SystemRoot 'System32\wsl.exe'

function ConvertTo-WinPath {
    param([string]$Path)
    if ($Path -match '^/mnt/([a-zA-Z])/(.*)$') {
        return ('{0}:/{1}' -f $Matches[1].ToUpper(), $Matches[2])
    }
    return $Path
}
function ConvertTo-WslPath {
    param([string]$Path)
    $full = ([System.IO.Path]::GetFullPath($Path)) -replace '\\', '/'
    if ($full -match '^([A-Za-z]):/(.*)$') {
        return ('/mnt/{0}/{1}' -f $Matches[1].ToLower(), $Matches[2])
    }
    return $full
}

# The folder this script lives in, as WSL sees it (the scripts run from the dev repository).
$qsWsl = ConvertTo-WslPath $PSScriptRoot

if ($Stop -and $WriteEnv) { Write-Host 'usage: -Stop and -WriteEnv are separate modes'; exit 2 }

if ($WriteEnv) {
    if (-not $Clone) { Write-Host 'usage: -WriteEnv -Clone <wsl path>'; exit 2 }
    $key = [Environment]::GetEnvironmentVariable('OPENROUTER_API_KEY', 'User')
    if (-not $key) { Write-Host 'FATAL: the User-scope OPENROUTER_API_KEY is not set'; exit 4 }
    # A PowerShell pipe appends CRLF; the WSL script strips every CR and LF.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $key | & $wsl -d Ubuntu -- bash "$qsWsl/qs-wsl-write-env.sh" $Clone
    $code = $LASTEXITCODE
    $ErrorActionPreference = $previous
    $key = $null
    exit $code
}

if (-not $EvidenceDir) { Write-Host 'usage: -Clone <wsl path> -EvidenceDir <wsl path> | -Stop -EvidenceDir <wsl path> | -WriteEnv -Clone <wsl path>'; exit 2 }
$evWin = ConvertTo-WinPath $EvidenceDir
$hostPidFile = Join-Path $evWin 'host.pid'

if ($Stop) {
    if (-not (Test-Path -LiteralPath $hostPidFile)) {
        Write-Host 'nothing to stop: no host.pid'
        exit 0
    }
    $raw = ([System.IO.File]::ReadAllText($hostPidFile, $Utf8NoBom)).Trim()
    $hostPid = 0
    if (-not [int]::TryParse($raw, [ref]$hostPid)) {
        Write-Host 'host.pid does not hold a PID; nothing stopped'
        exit 0
    }
    $proc = Get-Process -Id $hostPid -ErrorAction SilentlyContinue
    if (-not $proc) {
        Write-Host "host pid ${hostPid}: already gone"
        exit 0
    }
    if ($proc.ProcessName -ne 'wsl') {
        Write-Host "host pid ${hostPid}: now belongs to $($proc.ProcessName); not stopped"
        exit 0
    }
    Stop-Process -Id $hostPid -Force
    Write-Host "host pid ${hostPid}: wsl.exe stopped"
    exit 0
}

# Default mode: start the WSL launcher detached from this process's job object.
if (-not $Clone) { Write-Host 'usage: -Clone <wsl path> -EvidenceDir <wsl path>'; exit 2 }
New-Item -ItemType Directory -Force -Path $evWin | Out-Null
Remove-Item -LiteralPath $hostPidFile -ErrorAction SilentlyContinue

$commandLine = '"{0}" -d Ubuntu -- bash {1}/qs-wsl-launch.sh {2} {3}' -f $wsl, $qsWsl, $Clone, $EvidenceDir
$result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $commandLine }
if ($result.ReturnValue -ne 0) {
    throw "Win32_Process Create failed with return value $($result.ReturnValue)"
}
[System.IO.File]::WriteAllText($hostPidFile, "$($result.ProcessId)`r`n", $Utf8NoBom)
Write-Host "started wsl host pid=$($result.ProcessId) evidence=$EvidenceDir"
