#Requires -Version 5.1
<#
.SYNOPSIS
  Detached launcher for scripts/oi02-replay.ps1 -- avoids bash/PowerShell nested-quoting
  hazards by taking real typed parameters and building the Start-Process call in-process
  (06.3.4.1-07 Task 2 execution note: replays run long, launch in background and poll).
#>
param(
    [Parameter(Mandatory = $true)][string]$LogDir,
    [Parameter(Mandatory = $true)][string]$RunName,
    # A single pipe-delimited string, not [string[]] -- powershell.exe's own -File argument
    # parser (used when launched from an external shell like bash, as opposed to PowerShell's
    # in-process comma-array-literal parsing) does not let one array parameter greedily
    # consume multiple following space-separated tokens; each bare token after the first
    # becomes a new, unmatched positional argument. A single delimited string sidesteps that
    # entirely and is unambiguous across the bash-to-powershell.exe boundary.
    [Parameter(Mandatory = $true)][string]$ReplayArgsJoined
)
$ReplayArgs = $ReplayArgsJoined -split '\|'
# Quote every VALUE token (anything not starting with '-') as a single-quoted PowerShell string
# literal before splicing it into the generated inner-script source text below. Without this,
# a value containing a comma (e.g. a -StubEmbedDelayScheduleMs schedule like
# "308,399,442,481,462,859,2043") gets re-parsed by PowerShell's own tokenizer as an ARRAY
# LITERAL when the unquoted source text is invoked, not as a single string -- binding then
# fails with "Cannot convert the value ... to type System.String" (06.3.4.1-07 Task 4 Route B
# step 4 self-review: found when the first paced-arm smoke failed before any file was written).
# Single quotes are doubled to escape a literal single quote inside the value, per PowerShell's
# own single-quoted-string escaping rule.
$QuotedReplayArgs = $ReplayArgs | ForEach-Object {
    if ($_ -match '^-') { $_ } else { "'" + ($_ -replace "'", "''") + "'" }
}

$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$outLog = Join-Path $LogDir "$RunName.out.log"
$doneMarker = Join-Path $LogDir "$RunName.done"
Remove-Item -Path $doneMarker -ErrorAction SilentlyContinue
Remove-Item -Path $outLog -ErrorAction SilentlyContinue

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$scriptPath = Join-Path $PSScriptRoot 'oi02-replay.ps1'

$innerScript = @"
Set-Location '$repoRoot'
`$ErrorActionPreference = 'Continue'
try {
    & '$scriptPath' $($QuotedReplayArgs -join ' ') *> '$outLog'
    "EXIT_CODE=`$LASTEXITCODE" | Out-File -FilePath '$doneMarker' -Encoding utf8
} catch {
    # Plain-string fields only, never `\$_ | Out-String` on the whole ErrorRecord -- PowerShell
    # 5.1's default error-record formatting can include ANSI/VT100 highlighting sequences,
    # which corrupted this log into unreadable control-character garbage whenever the wrapped
    # script threw (root-caused after multiple false leads blaming cargo/docker's own output).
    "ERROR: `$(`$_.Exception.Message)" | Out-File -FilePath '$outLog' -Append -Encoding utf8
    "STACK: `$(`$_.ScriptStackTrace)" | Out-File -FilePath '$outLog' -Append -Encoding utf8
    'EXIT_CODE=ERROR' | Out-File -FilePath '$doneMarker' -Encoding utf8
}
"@
$innerScriptPath = Join-Path $LogDir "$RunName.inner.ps1"
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($innerScriptPath, $innerScript, $Utf8NoBom)

$p = Start-Process -FilePath 'powershell.exe' `
    -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $innerScriptPath) `
    -WindowStyle Hidden -PassThru
Write-Host "Launched detached run '$RunName', pid=$($p.Id), log=$outLog, done-marker=$doneMarker"
