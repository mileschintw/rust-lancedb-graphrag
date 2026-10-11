#Requires -Version 5.1
<#
.SYNOPSIS
  Runs ONE README quickstart step inside the fresh clone, with the documented .env flow
  (06.4 plan 08, D-220, Pitfall 18). Plan 06.4-09 runs every client step through this
  launcher: Git Bash keeps no environment between calls, and sourcing a PowerShell-written
  .env from Git Bash would carry a trailing CR into every value.

.DESCRIPTION
  Order, fixed:
    1. remove any inherited OPENROUTER_API_KEY from this process and assert it is gone
       (a WMI-created process inherits the User-scope environment);
    2. refuse (exit 3, <EvidenceDir>/<Role>.refused) when any LANCET_ENGINE__GRAPH__* or
       LANCET_ENGINE__LEVERS__* variable exists (D-199);
    3. import <Clone>/.env with the README's PowerShell one-liner, verbatim, and set
       PYTHONUTF8=1;
    4. assert the key is now set, by length only (the value is never printed);
    5. set NO_COLOR=1 (a harness addition for clean logs; record it in the transcript);
    6. run the role from the clone.

  Harness additions to record in the transcript: NO_COLOR=1 for every role, and
  LANCET_EVAL__GATEWAY_TIMEOUT_SECS=90 for the query roles (query-*, two-hop*, burst-*),
  which caps each request's read timeout at 90 s (the settings default is 300 s).

  Output files in <EvidenceDir>: <Role>.log (stdout and stderr, UTF-8; preflight writes
  preflight-<Attempt>.txt) and <Role>.exit (preflight-<Attempt>.exit), written when the
  command ends. Query and ingest roles also save the helper's stdout JSON lines to
  <Role>.json. A role made of several commands (rescore, the bursts) stops at its first
  failing command and records that command's code. This script exits with the recorded
  code, so a failed foreground step fails the caller's Bash call.

  Exit codes: 0 ok; 3 refused (D-199); 4 key missing or too short, or .env missing;
  5 rescore left eval/runs dirty; other values come from the failing command.
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('engine', 'gateway', 'preflight', 'settle-before', 'settle-after',
        'query-before', 'query-after', 'two-hop', 'two-hop-graph', 'burst-a', 'burst-b',
        'ingest', 'rescore')]
    [string]$Role,
    [Parameter(Mandatory = $true)][string]$Clone,
    [Parameter(Mandatory = $true)][string]$EvidenceDir,
    [int]$Attempt = 1
)
$ErrorActionPreference = 'Stop'

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
$EvidenceDir = (Resolve-Path -LiteralPath $EvidenceDir).Path
$Clone = (Resolve-Path -LiteralPath $Clone).Path

if ($Role -eq 'preflight') {
    $stem = "preflight-$Attempt"
    $logFile = Join-Path $EvidenceDir "$stem.txt"
} else {
    $stem = $Role
    $logFile = Join-Path $EvidenceDir "$Role.log"
}
$exitFile = Join-Path $EvidenceDir "$stem.exit"
$jsonFile = Join-Path $EvidenceDir "$Role.json"
$refusedFile = Join-Path $EvidenceDir "$Role.refused"

function Write-ExitFile {
    param([int]$Code)
    [System.IO.File]::WriteAllText($exitFile, "$Code`r`n", $Utf8NoBom)
}
function Add-Log {
    param([string]$Text)
    [System.IO.File]::AppendAllText($logFile, $Text + "`r`n", $Utf8NoBom)
}

# A WMI-created process starts from the registry environment, so rebuild PATH from the
# Machine and User scopes (the process value is kept last, in case the caller added to it).
$machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$env:Path = "$machinePath;$userPath;$env:Path"

# Start the role's output files clean, so a poller never reads a previous run's result.
foreach ($f in @($exitFile, $refusedFile)) { Remove-Item -LiteralPath $f -ErrorAction SilentlyContinue }
[System.IO.File]::WriteAllText($logFile,
    "# qs-win-launch role=$Role attempt=$Attempt started_utc=$([DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')) clone=$Clone`r`n",
    $Utf8NoBom)
if ($Role -match '^(query-|two-hop|burst-|ingest)') {
    [System.IO.File]::WriteAllText($jsonFile, '', $Utf8NoBom)
}

# 1. Remove the inherited key and assert it is gone.
Remove-Item Env:OPENROUTER_API_KEY -ErrorAction SilentlyContinue
if (Test-Path Env:OPENROUTER_API_KEY) {
    Add-Log 'FATAL: OPENROUTER_API_KEY could not be removed from the process environment'
    Write-ExitFile 4
    exit 4
}

# 2. Refuse on the D-199 override variables (names only are written, never values).
function Find-Overrides {
    @(Get-ChildItem Env: | Where-Object {
            $_.Name -like 'LANCET_ENGINE__GRAPH__*' -or $_.Name -like 'LANCET_ENGINE__LEVERS__*'
        } | ForEach-Object { $_.Name })
}
$overrides = Find-Overrides
if ($overrides.Count -gt 0) {
    [System.IO.File]::WriteAllText($refusedFile, ($overrides -join "`r`n") + "`r`n", $Utf8NoBom)
    Add-Log "REFUSED (D-199): override variables present: $($overrides -join ', ')"
    Write-ExitFile 3
    exit 3
}

# 3. Import the clone's .env with the README one-liner, verbatim, from the clone root.
Set-Location -LiteralPath $Clone
if (-not (Test-Path -LiteralPath '.env')) {
    Add-Log 'FATAL: .env is missing in the clone'
    Write-ExitFile 4
    exit 4
}
Get-Content .env | % { if ($_ -match '^\s*([^#=\s]+)\s*=\s*(.*)$') { Set-Item "env:$($Matches[1])" $Matches[2].Trim('"') } }
$env:PYTHONUTF8 = "1"

# .env must not smuggle in an override either.
$overrides = Find-Overrides
if ($overrides.Count -gt 0) {
    [System.IO.File]::WriteAllText($refusedFile, ($overrides -join "`r`n") + "`r`n", $Utf8NoBom)
    Add-Log "REFUSED (D-199): .env defines override variables: $($overrides -join ', ')"
    Write-ExitFile 3
    exit 3
}

# 4. The key is checked by length only.
$keyLength = 0
if ($env:OPENROUTER_API_KEY) { $keyLength = $env:OPENROUTER_API_KEY.Length }
if ($keyLength -le 20) {
    Add-Log "FATAL: OPENROUTER_API_KEY from .env is missing or too short (length $keyLength)"
    Write-ExitFile 4
    exit 4
}
Add-Log "# OPENROUTER_API_KEY imported from .env, length $keyLength (value not shown)"

# 5. Harness additions.
$env:NO_COLOR = '1'
if ($Role -match '^(query-|two-hop|burst-)') {
    $env:LANCET_EVAL__GATEWAY_TIMEOUT_SECS = '90'
}

# cmd.exe does the redirection, so PowerShell 5.1 never wraps native stderr in
# ErrorRecords (which would throw under $ErrorActionPreference = 'Stop'), and the child's
# UTF-8 bytes reach the file untouched.
function Invoke-Cmd {
    param([string]$Line)
    $p = Start-Process -FilePath 'cmd.exe' -ArgumentList @('/d', '/s', '/c', ('"' + $Line + '"')) `
        -NoNewWindow -PassThru
    $null = $p.Handle
    $p.WaitForExit()
    return [int]$p.ExitCode
}
function Read-Text {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path) { return [System.IO.File]::ReadAllText($Path, $Utf8NoBom) }
    return ''
}
# stdout and stderr interleaved into the role log.
function Invoke-Combined {
    param([string]$Command)
    Add-Log "# > $Command"
    return (Invoke-Cmd "$Command >> `"$logFile`" 2>&1")
}
# stdout kept apart (it is the helper's JSON), stderr after it; both land in the log.
function Invoke-Split {
    param([string]$Command)
    $outTmp = Join-Path $EvidenceDir "$stem.stdout.tmp"
    $errTmp = Join-Path $EvidenceDir "$stem.stderr.tmp"
    Add-Log "# > $Command"
    $code = Invoke-Cmd "$Command > `"$outTmp`" 2> `"$errTmp`""
    $stdout = Read-Text $outTmp
    $stderr = Read-Text $errTmp
    Add-Log "# stdout"
    Add-Log $stdout.TrimEnd()
    if ($stderr.Trim().Length -gt 0) {
        Add-Log "# stderr"
        Add-Log $stderr.TrimEnd()
    }
    if ($Role -match '^(query-|two-hop|burst-|ingest)') {
        [System.IO.File]::AppendAllText($jsonFile, $stdout, $Utf8NoBom)
    }
    Remove-Item -LiteralPath $outTmp, $errTmp -ErrorAction SilentlyContinue
    Add-Log "# exit $code"
    return $code
}

# The quickstart canary texts (qs-001, qs-002, qs-003), read from the committed file.
function Get-Canary {
    param([string]$QuestionId)
    $path = Join-Path $Clone 'eval/corpora/quickstart/canary.arms.jsonl'
    foreach ($line in (Get-Content -LiteralPath $path -Encoding UTF8)) {
        if ($line.Trim().Length -eq 0) { continue }
        $row = $line | ConvertFrom-Json
        if ($row.question_id -eq $QuestionId) {
            $text = [string]$row.question
            if ($text -match '["%]') { throw "canary $QuestionId holds a character that cannot be quoted for cmd.exe" }
            return $text
        }
    }
    throw "canary $QuestionId not found"
}
$qs = 'uv run --project eval python eval/scripts/quickstart.py'
function Get-QueryCommand {
    param([string]$Text, [switch]$Graph)
    $cmd = "$qs query `"$Text`""
    if ($Graph) { $cmd += ' --graph' }
    return $cmd
}

$code = 0
try {
    switch ($Role) {
        'engine' {
            $code = Invoke-Combined 'cargo run --manifest-path engine/Cargo.toml --release --bin engine'
        }
        'gateway' {
            Set-Location -LiteralPath (Join-Path $Clone 'gateway')
            $code = Invoke-Combined 'go run .'
        }
        'preflight' {
            $code = Invoke-Combined 'uv run --project eval lancet-eval preflight --stack'
        }
        { $_ -in @('settle-before', 'settle-after') } {
            $settle = Join-Path $PSScriptRoot 'qs-settle.py'
            $code = Invoke-Combined "uv run --project eval python `"$settle`" --out `"$jsonFile`""
        }
        { $_ -in @('query-before', 'query-after') } {
            $code = Invoke-Split (Get-QueryCommand (Get-Canary 'qs-002'))
        }
        'two-hop' {
            $code = Invoke-Split (Get-QueryCommand (Get-Canary 'qs-001'))
        }
        'two-hop-graph' {
            $code = Invoke-Split (Get-QueryCommand (Get-Canary 'qs-001') -Graph)
        }
        'burst-a' {
            foreach ($id in @('qs-001', 'qs-002', 'qs-003')) {
                $code = Invoke-Split (Get-QueryCommand (Get-Canary $id))
                if ($code -ne 0) { break }
            }
        }
        'burst-b' {
            foreach ($id in @('qs-002', 'qs-003')) {
                $code = Invoke-Split (Get-QueryCommand (Get-Canary $id))
                if ($code -ne 0) { break }
            }
        }
        'ingest' {
            $code = Invoke-Split "$qs ingest"
        }
        'rescore' {
            # The README's PowerShell re-score block, verbatim in effect; offline, no key used.
            $run = "eval/runs/2026-10-10-levers-heldout-multihop_rag_levers_heldout"
            $tmp = New-Item -ItemType Directory -Path (Join-Path $env:TEMP "lancet-rescore-$(Get-Random)")
            Copy-Item "$run/journal.jsonl" $tmp
            Add-Log "# re-score copy: $($tmp.FullName)"
            $steps = @(
                "uv run --project eval lancet-eval score --run `"$($tmp.FullName)`" --no-judge",
                "uv run --project eval lancet-eval report --run `"$($tmp.FullName)`"",
                "uv run --project eval python eval/scripts/compare_rescore.py `"$run`" `"$($tmp.FullName)`""
            )
            foreach ($step in $steps) {
                $code = Invoke-Combined $step
                if ($code -ne 0) { break }
            }
            if ($code -eq 0) {
                $statusTmp = Join-Path $EvidenceDir 'rescore.status.tmp'
                Add-Log '# > git status --porcelain -- eval/runs'
                $null = Invoke-Cmd "git status --porcelain -- eval/runs > `"$statusTmp`" 2>&1"
                $status = (Read-Text $statusTmp).Trim()
                Remove-Item -LiteralPath $statusTmp -ErrorAction SilentlyContinue
                if ($status.Length -gt 0) {
                    Add-Log "# git status printed (it must print nothing):"
                    Add-Log $status
                    $code = 5
                } else {
                    Add-Log '# git status printed nothing'
                }
            }
        }
    }
} catch {
    Add-Log "ERROR: $($_.Exception.Message)"
    Add-Log "STACK: $($_.ScriptStackTrace)"
    $code = 1
}

Add-Log "# finished_utc=$([DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')) exit=$code"
Write-ExitFile $code
exit $code
