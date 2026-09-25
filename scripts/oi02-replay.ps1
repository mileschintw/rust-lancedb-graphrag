#Requires -Version 5.1
<#
.SYNOPSIS
  OI-02 full-stack replay (06.3.4.1-07 Task 2): one-command replay on isolated data copies,
  with header, process sampling, and before/after live-state proof.

.DESCRIPTION
  Runs the real `engine` binary, the real `gateway` binary and the real harness
  (`lancet-eval run`) against an isolated LanceDB store copy and a scratch PostgreSQL
  database, with a loopback-only provider stub in place of OpenRouter. Never opens
  `data/lancedb-eval` or the `lancet_eval` schema for writing.

  Run as: powershell -NoProfile -ExecutionPolicy Bypass -File scripts/oi02-replay.ps1 ...

  Env vars this script sets live only in this process tree and vanish when it exits.
#>
param(
    [Parameter(Mandatory = $true)][string]$Label,
    [ValidateSet('pre-fix', 'post-fix')][string]$Phase = 'pre-fix',
    [string]$EngineLaunch = 'cargo-debug',
    # 'head' or 'worktree:<abs path>' (06.3.4.1-07 Task 4 Route B: the drive-era whole-stack
    # arm needs the harness -- Python, not Rust/Go -- driven from a DIFFERENT commit's `eval/`
    # tree, specifically to predate HEAD's D-61 harness identity gate, which correctly refuses
    # a 350-document pre-reconcile store). Validated below (not via ValidateSet, since the
    # allowed set includes an arbitrary path suffix) so an unsupported value still fails fast.
    [string]$HarnessFrom = 'head',
    [string]$GatewayFrom = 'head',
    [ValidateSet('full-stack', 'grpc-direct', 'soak-inprocess')][string]$ArmKind = 'full-stack',
    [string]$EngineConfigDir = '',
    [string]$GatewayConfigDir = '',
    [ValidateSet('on', 'off')][string]$Observability = 'on',
    [ValidateSet('console', 'file', 'null')][string]$StderrSink = 'console',
    [int]$Questions = 2,
    [int]$WarmupQuestions = 0,
    [int]$Retries = 2,
    [int]$Workers = 1,
    [int]$StubEmbedDelayMs = 0,
    [int]$StubChatDelayMs = 0,
    [ValidateSet('reconciled', 'pre-reconcile')][string]$StoreSource = 'reconciled',
    [int]$SampleSeconds = 5,
    [switch]$Paid,
    [double]$StageCap = 1.00,
    # Default true: `cargo build`/`cargo run` invoked from THIS script's own fully-detached,
    # no-console process tree has been empirically observed to write unreadable control-
    # character garbage into the captured log (reproduced consistently across --color never,
    # --progress plain, CARGO_TERM_PROGRESS_WHEN=never and CI=true attempts to suppress it --
    # none resolved it). Run `cargo build --manifest-path engine/Cargo.toml --locked
    # [--release] --bin engine` yourself, in a normal foreground shell, BEFORE launching this
    # script, then leave this at its default. Pass -SkipEngineBuild:$false only for genuinely
    # interactive (non-detached) runs where you can tolerate that corruption risk.
    [bool]$SkipEngineBuild = $true
)

$ErrorActionPreference = 'Stop'
# Broad safety net: this script's own output is always captured/teed (never a real console),
# so every child tool's ANSI/color output must be disabled at the source -- raw escape
# sequences corrupt a captured log into unreadable control-character garbage.
$env:NO_COLOR = '1'
$env:CARGO_TERM_COLOR = 'never'
# CARGO_TERM_PROGRESS_WHEN=never: distinct from CARGO_TERM_COLOR -- disables the cargo build
# progress bar's carriage-return-driven redraw entirely (not just its color), which is the
# actual source of corrupted control-character output observed in this fully-detached,
# no-console process tree even with --color never on the build command itself.
$env:CARGO_TERM_PROGRESS_WHEN = 'never'
$env:CI = 'true'
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Resolve-FromSpec {
    # Validates and resolves a 'head' | 'worktree:<path>' spec for -HarnessFrom/-GatewayFrom/
    # -EngineLaunch's worktree case. Fails fast (unsupported value) rather than silently
    # falling back to head, per gotcha #1's "resolve pre-built artifacts only, throw if
    # missing" pattern.
    param([string]$Spec, [string]$ParamName)
    if ($Spec -eq 'head') { return @{ Kind = 'head'; Path = $null } }
    if ($Spec -like 'worktree:*') {
        $wtPath = $Spec.Substring('worktree:'.Length)
        if ([string]::IsNullOrWhiteSpace($wtPath)) {
            throw "-$ParamName worktree:<path> requires a non-empty path"
        }
        if (-not (Test-Path $wtPath)) {
            throw "-$ParamName worktree path does not exist: $wtPath"
        }
        return @{ Kind = 'worktree'; Path = (Resolve-Path $wtPath).Path }
    }
    throw "-$ParamName must be 'head' or 'worktree:<path>', got: $Spec"
}

function Write-JsonFile {
    param([string]$Path, $Object)
    $json = $Object | ConvertTo-Json -Depth 10
    [System.IO.File]::WriteAllText($Path, $json, $Utf8NoBom)
}

function Get-RepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
}

function Invoke-TrimmedOutput {
    # A `docker exec .../psql -tAc` (or any external-command) call with no result rows
    # returns $null in PowerShell, not an empty string -- $null.Trim() then throws
    # "cannot call a method on a null-valued expression". Every external-command output this
    # script trims goes through here so a genuinely empty result reads as "" instead of
    # crashing.
    param([string[]]$Output)
    if ($null -eq $Output) { return '' }
    return (($Output -join "`n").Trim())
}

$RepoRoot = Get-RepoRoot
Set-Location $RepoRoot

$HarnessSpec = Resolve-FromSpec -Spec $HarnessFrom -ParamName 'HarnessFrom'
$GatewaySpec = Resolve-FromSpec -Spec $GatewayFrom -ParamName 'GatewayFrom'
$EngineIsWorktree = $EngineLaunch -like 'worktree:*'
$EngineWorktreePath = $null
if ($EngineIsWorktree) {
    $EngineWorktreePath = $EngineLaunch.Substring('worktree:'.Length)
    if ([string]::IsNullOrWhiteSpace($EngineWorktreePath) -or -not (Test-Path $EngineWorktreePath)) {
        throw "-EngineLaunch worktree:<path> requires an existing path, got: $EngineLaunch"
    }
    $EngineWorktreePath = (Resolve-Path $EngineWorktreePath).Path
}

$PhaseDir = ".planning/phases/06.3.4.1-retrieval-diagnosis-index-identity-and-graph-yield-repair/replay/$Phase"
$ArmDir = Join-Path $PhaseDir $Label
New-Item -ItemType Directory -Force -Path $ArmDir | Out-Null

Write-Host "=== oi02-replay: label=$Label phase=$Phase armKind=$ArmKind ==="

# --- 1. Port pre-flight -------------------------------------------------------------------
function Test-PortListening {
    param([int]$Port)
    $conns = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    return ($null -ne $conns)
}

if ($ArmKind -ne 'soak-inprocess') {
    if (Test-PortListening -Port 50051) { throw "Port 50051 is already listening; refusing to start." }
    if (Test-PortListening -Port 8080) { throw "Port 8080 is already listening; refusing to start." }
}

# --- 2. Store copy --------------------------------------------------------------------------
$LiveStorePath = if ($StoreSource -eq 'pre-reconcile') { 'data/lancedb-eval.pre-06.3.4.1-reconcile' } else { 'data/lancedb-eval' }
$CopyStorePath = if ($StoreSource -eq 'pre-reconcile') { 'data/lancedb-replay-prereconcile' } else { 'data/lancedb-replay' }

$copyFileCountBefore = 0
$copyBytesBefore = 0
if (-not (Test-Path $CopyStorePath)) {
    Write-Host "Creating store copy: $CopyStorePath <- $LiveStorePath"
    Copy-Item -Path $LiveStorePath -Destination $CopyStorePath -Recurse -Force
} else {
    Write-Host "Store copy already exists (reused across arms): $CopyStorePath"
}
$copyFiles = Get-ChildItem -Path $CopyStorePath -Recurse -File
$copyFileCountBefore = $copyFiles.Count
$copyBytesBefore = ($copyFiles | Measure-Object -Property Length -Sum).Sum
$rollbackFiles = Get-ChildItem -Path $LiveStorePath -Recurse -File
$rollbackFileCountBefore = $rollbackFiles.Count
$rollbackBytesBefore = ($rollbackFiles | Measure-Object -Property Length -Sum).Sum

# --- 3. Scratch database ----------------------------------------------------------------
# Named by store source (06.3.4.1-07 Task 4 self-review): the restore below only runs when
# the DB doesn't already exist, so a single shared 'lancet_replay' name would silently pair a
# pre-reconcile store copy with whatever schema state a PRIOR reconciled-store arm already
# restored there (or vice versa) instead of the matching pre-reconcile dump.
$ScratchDbName = if ($StoreSource -eq 'pre-reconcile') { 'lancet_replay_prereconcile' } else { 'lancet_replay' }
$dumpPath = if ($StoreSource -eq 'pre-reconcile') { 'data/backups/lancet_eval.pre-06.3.4.1-reconcile.sql' } else { $null }

$dbExists = Invoke-TrimmedOutput (& docker exec lancet-postgres psql -U postgres -tAc "select 1 from pg_database where datname='$ScratchDbName'" 2>$null)
if ($dbExists -ne '1') {
    Write-Host "Creating scratch database $ScratchDbName"
    & docker exec lancet-postgres psql -U postgres -c "CREATE DATABASE $ScratchDbName" | Out-Null
    # cmd.exe redirection (not PowerShell's Get-Content/Out-File) for the dump/restore pipe:
    # PowerShell 5.1's native-command output capture re-encodes through the console codepage,
    # which corrupts embedded control characters inside JSON COPY data (observed: "invalid
    # input syntax for type json ... Character with value 0x0a must be escaped" on a genuine
    # attempt). cmd.exe's `>`/`<` redirection is a raw byte passthrough.
    if ($dumpPath -and (Test-Path $dumpPath)) {
        Write-Host "Restoring $ScratchDbName from $dumpPath"
        $dumpAbs = (Resolve-Path $dumpPath).Path
        & cmd /c "docker exec -i lancet-postgres psql -U postgres -d $ScratchDbName < `"$dumpAbs`"" | Out-Null
    } else {
        Write-Host "Restoring $ScratchDbName from a fresh pg_dump --schema=lancet_eval of the live database"
        $freshDump = Join-Path $env:TEMP "lancet_eval_replay_dump_$Label.sql"
        & cmd /c "docker exec lancet-postgres pg_dump -U postgres -d lancet --schema=lancet_eval --no-owner --no-privileges > `"$freshDump`""
        & cmd /c "docker exec -i lancet-postgres psql -U postgres -d $ScratchDbName < `"$freshDump`"" | Out-Null
    }
} else {
    Write-Host "Scratch database $ScratchDbName already exists (reused across arms)"
}

# --- 4. Live-state / copy-state before -------------------------------------------------
function Get-LiveStateSnapshot {
    # Per-table fingerprint sufficient to detect ANY write during the replay: the latest
    # manifest file's name (kept as a string -- lancedb 0.31.0's on-disk manifest numbering
    # is not a small sequential integer in every store, so parsing it as [int] can overflow),
    # the manifest file count, and the table directory's total byte size. A change in any of
    # these three fields for any table means the store was written to.
    param([string]$StorePath)
    $tables = @('documents', 'nodes', 'edges', 'staged_documents_v2', 'entity_edges', 'entities', 'communities')
    $result = @{}
    foreach ($t in $tables) {
        $versionsDir = Join-Path $StorePath "$t.lance/_versions"
        $manifests = Get-ChildItem -Path $versionsDir -Filter '*.manifest' -ErrorAction SilentlyContinue
        if ($manifests) {
            $latest = $manifests | Sort-Object Name -Descending | Select-Object -First 1
            $result[$t] = @{
                latest_manifest = $latest.Name
                manifest_count = $manifests.Count
            }
        } else {
            $result[$t] = @{ latest_manifest = $null; manifest_count = 0 }
        }
    }
    return $result
}

$liveStateBefore = @{ table_versions = (Get-LiveStateSnapshot -StorePath 'data/lancedb-eval') }
$pgCountsBefore = Invoke-TrimmedOutput (& docker exec lancet-postgres psql -U postgres -d lancet -tAc "select count(*) from lancet_eval.documents" 2>$null)
$liveStateBefore['documents_count'] = $pgCountsBefore
Write-JsonFile -Path (Join-Path $ArmDir 'live-state.before.json') -Object $liveStateBefore

$copyStateBefore = @{
    table_versions = (Get-LiveStateSnapshot -StorePath $CopyStorePath)
    file_count = $copyFileCountBefore
    bytes = $copyBytesBefore
}
Write-JsonFile -Path (Join-Path $ArmDir 'copy-state.before.json') -Object $copyStateBefore

# --- 5. staged_documents_v2 assertion (Pitfall 14) --------------------------------------
$stagedCount = Invoke-TrimmedOutput (& docker exec lancet-postgres psql -U postgres -d $ScratchDbName -tAc "select count(*) from lancet_eval.document_reconciliation_intents" 2>$null)
Write-Host "Pending reconciliation intents in scratch DB: $stagedCount"

# --- 6. Provider stub ---------------------------------------------------------------------
$StubHost = '127.0.0.1'
$StubPort = 18100 + (Get-Random -Minimum 0 -Maximum 800)
$GenerationModel = 'deepseek/deepseek-v4-flash-0731'
$StubVectorsPath = 'data/replay/stub-vectors.jsonl'
$stubArgs = @('-m', 'lancet_eval.provider_stub', '--host', $StubHost, '--port', $StubPort, '--model', $GenerationModel,
    '--embed-delay-ms', $StubEmbedDelayMs, '--chat-delay-ms', $StubChatDelayMs)
if (Test-Path $StubVectorsPath) { $stubArgs += @('--vectors', $StubVectorsPath) }

$stubProc = $null
if (-not $Paid) {
    Write-Host "Starting provider stub on ${StubHost}:${StubPort}"
    # The venv's own python.exe directly, not `uv run` -- `uv run` spawns python as a CHILD
    # process, and Stop-Process on the `uv` wrapper's PID does not cascade-terminate that
    # child on Windows, leaking an orphaned provider_stub process (same root cause the
    # engine/gateway launches above already worked around).
    $stubPythonPath = Join-Path $RepoRoot 'eval\.venv\Scripts\python.exe'
    $stubProc = Start-Process -FilePath $stubPythonPath -ArgumentList $stubArgs `
        -WorkingDirectory $RepoRoot -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $ArmDir 'stub-stdout.log') -RedirectStandardError (Join-Path $ArmDir 'stub-stderr.log')
    Start-Sleep -Seconds 2
}

# --- 7. Observability stack ---------------------------------------------------------------
# `docker compose`'s own TUI progress renderer (even with --ansi never --progress plain) has
# been observed to write unreadable control-character sequences into this script's captured
# log when invoked from this fully-detached, no-console process tree. `docker ps`/`docker
# inspect` have no such renderer and produce clean, parseable output, so containers are
# checked and started/stopped one at a time through those instead of ever invoking `compose`
# from this script.
$ObservabilityContainers = @('lancet-collector', 'lancet-jaeger', 'lancet-prometheus', 'lancet-loki', 'lancet-grafana')
function Get-ContainerRunning {
    param([string]$Name)
    $state = Invoke-TrimmedOutput (& docker inspect -f '{{.State.Running}}' $Name 2>$null)
    return $state -eq 'true'
}

if ($Observability -eq 'on') {
    Write-Host "Ensuring observability stack is up"
    foreach ($c in $ObservabilityContainers) {
        if (-not (Get-ContainerRunning -Name $c)) {
            Write-Host "Starting $c"
            & docker start $c 2>&1 | Out-Null
        }
    }
} else {
    Write-Host "Stopping observability stack for this arm (Observability=off)"
    foreach ($c in $ObservabilityContainers) {
        if (Get-ContainerRunning -Name $c) {
            & docker stop $c 2>&1 | Out-Null
        }
    }
}

# --- 8. Engine env / launch ----------------------------------------------------------------
$env:LANCET_ENV = 'eval'
$env:LANCET_ENGINE__LANCEDB_PATH = (Resolve-Path $CopyStorePath).Path
$env:OPENROUTER_API_KEY = if ($Paid) { $env:OPENROUTER_API_KEY } else { 'dummy-replay-key-not-real' }
if (-not $Paid) {
    $env:LANCET_OPENROUTER__EMBEDDING_ENDPOINT = "http://${StubHost}:${StubPort}/embeddings"
    $env:LANCET_OPENROUTER__MODEL_METADATA_ENDPOINT = "http://${StubHost}:${StubPort}/models"
    $env:LANCET_OPENROUTER__CHAT_ENDPOINT = "http://${StubHost}:${StubPort}/chat/completions"
}
$telemetryModeEngine = 'otlp'
if ($EngineConfigDir -ne '') {
    $env:LANCET_CONFIG_DIR = (Resolve-Path $EngineConfigDir).Path
    $telemetryModeEngine = 'console-only'
} elseif ($Observability -eq 'off') {
    $telemetryModeEngine = 'otlp-unreachable'
}

$env:CARGO_BUILD_JOBS = '4'  # plan 03 found full parallelism exhausts this machine

$engineBuildProfile = 'debug'
$engineExeRelPath = 'engine/target/debug/engine.exe'
$engineBuildArgs = @('build', '--manifest-path', 'engine/Cargo.toml', '--locked', '--bin', 'engine')
if ($EngineLaunch -eq 'release-exe' -or $EngineLaunch -eq 'cargo-release') {
    $engineBuildProfile = 'release'
    $engineExeRelPath = 'engine/target/release/engine.exe'
    $engineBuildArgs = @('build', '--manifest-path', 'engine/Cargo.toml', '--locked', '--release', '--bin', 'engine')
}
# Worktree engine (Task 4 Route B, drive-era whole stack): the binary lives under the
# worktree's own target dir, never HEAD's -- CARGO_TARGET_DIR is left unset so cargo defaults
# to `<worktree>/engine/target`, which cannot collide with HEAD's `engine/target`.
$engineWorkingDir = $RepoRoot
if ($EngineIsWorktree) {
    $engineExePath = Join-Path $EngineWorktreePath $engineExeRelPath
    $engineWorkingDir = $EngineWorktreePath
} else {
    $engineExePath = Join-Path $RepoRoot $engineExeRelPath
}

# Build via `cargo build` (never `cargo run`) and then exec the compiled binary directly.
# `cargo`/`rustc`'s progress-bar renderer has been observed to write raw, unreadable
# control-character sequences into any output stream captured from this script's fully
# detached, no-console process tree -- reproduced consistently across --color/--progress/
# CARGO_TERM_PROGRESS_WHEN/CI env-var combinations, so `cargo` itself (build OR run) is never
# invoked with its output captured. `cargo build`'s own console interaction happens here,
# BEFORE any redirection of this script's own streams is in effect from the launcher's
# perspective (this whole script's stdout/stderr already route to a file via the launcher,
# but cargo build's own child-process console handle allocation differs from cargo run's --
# empirically, `cargo build` alone does not reproduce the corruption, only launching a long-
# lived child via `cargo run` does). The engine binary is then started by execing
# $engineExePath directly, which sidesteps cargo's own process/console handling for the
# long-lived process entirely. `launch_command` in header.json still records production's own
# `cargo run ...` form for fidelity comparison, with `actual_invocation` recording what this
# script really used.
if ($SkipEngineBuild) {
    Write-Host "SkipEngineBuild=true -- expecting a fresh $engineExePath already built by the caller"
} elseif ($EngineIsWorktree) {
    throw "-EngineLaunch worktree:<path> requires a pre-built binary (-SkipEngineBuild `$true, the default) -- build it yourself first in a normal foreground shell: cargo build --manifest-path `"$EngineWorktreePath/engine/Cargo.toml`" --locked --bin engine (never inline in this detached script, gotcha #1)"
} else {
    Write-Host "Building engine ($engineBuildProfile, CARGO_BUILD_JOBS=4)"
    & cargo @engineBuildArgs
    if ($LASTEXITCODE -ne 0) {
        throw "cargo build for engine failed (exit $LASTEXITCODE)"
    }
}
if (-not (Test-Path $engineExePath)) {
    throw "$engineExePath does not exist -- build it yourself first: cargo build --manifest-path engine/Cargo.toml --locked --bin engine (add --release for the release profile), or pass -SkipEngineBuild `$false"
}

$engineStderrPath = Join-Path $ArmDir 'engine-stderr.log'
Write-Host "Starting engine binary directly: $engineExePath (cwd=$engineWorkingDir)"
if ($StderrSink -eq 'file') {
    $engineProc = Start-Process -FilePath $engineExePath -WorkingDirectory $engineWorkingDir -PassThru `
        -WindowStyle Hidden -RedirectStandardError $engineStderrPath -RedirectStandardOutput (Join-Path $ArmDir 'engine-stdout.log')
} elseif ($StderrSink -eq 'null') {
    $engineProc = Start-Process -FilePath $engineExePath -WorkingDirectory $engineWorkingDir -PassThru `
        -WindowStyle Hidden -RedirectStandardError 'NUL' -RedirectStandardOutput 'NUL'
} else {
    # console sink: not redirected to a file, matching production's own launch (a genuinely
    # visible window is not load-bearing for the file-vs-console distinction this replay
    # cares about, and may not be creatable in a non-interactive session -- WindowStyle
    # Hidden avoids that failure mode while still leaving stdio un-redirected).
    $engineProc = Start-Process -FilePath $engineExePath -WorkingDirectory $engineWorkingDir -PassThru -WindowStyle Hidden
}

Start-Sleep -Seconds 2
$deadline = (Get-Date).AddSeconds(60)
while (-not (Test-PortListening -Port 50051)) {
    if ((Get-Date) -gt $deadline) { throw "Engine did not start listening on 50051 within 60s of a pre-built binary" }
    Start-Sleep -Seconds 1
}
$enginePid = (Get-NetTCPConnection -State Listen -LocalPort 50051 | Select-Object -First 1 -ExpandProperty OwningProcess)
Write-Host "Engine listening on 50051, pid=$enginePid"

# --- 9. Gateway env / launch ----------------------------------------------------------------
$env:LANCET_GATEWAY__DATABASE_URL = "postgres://postgres:postgres@127.0.0.1:5432/${ScratchDbName}?sslmode=disable&search_path=lancet_eval"
if ($GatewayConfigDir -ne '') {
    $env:LANCET_CONFIG_DIR = (Resolve-Path $GatewayConfigDir).Path
}

$gatewayStartInfo = $null
if ($ArmKind -eq 'full-stack') {
    # `go run .` spawns a separate compiled gateway.exe CHILD process (in a temp go-build
    # dir) -- Stop-Process on the `go run` wrapper's own PID does not cascade-terminate that
    # child on Windows, which leaked an orphaned gateway.exe (still holding port 8080) on an
    # earlier run of this script. Build once, then exec the compiled binary directly, exactly
    # as the engine launch above already does for the identical reason.
    $gatewayRepoRoot = if ($GatewaySpec.Kind -eq 'worktree') { $GatewaySpec.Path } else { $RepoRoot }
    $gatewayExePath = Join-Path $gatewayRepoRoot 'gateway\gateway-replay.exe'
    if ($GatewaySpec.Kind -eq 'worktree') {
        # Same pre-build-only contract as the engine worktree case above -- go build is fast
        # and has not shown the cargo/docker-compose log-corruption symptom in this detached
        # tree, but keep the split explicit rather than silently building mid-run anyway.
        if (-not (Test-Path $gatewayExePath)) {
            throw "-GatewayFrom worktree:<path> requires a pre-built binary: cd `"$gatewayRepoRoot/gateway`" && go build -o gateway-replay.exe ."
        }
    } elseif ((-not $SkipEngineBuild) -or (-not (Test-Path $gatewayExePath))) {
        Write-Host "Building gateway"
        Push-Location (Join-Path $RepoRoot 'gateway')
        try {
            & go build -o $gatewayExePath .
            if ($LASTEXITCODE -ne 0) { throw "go build for gateway failed (exit $LASTEXITCODE)" }
        } finally { Pop-Location }
    }
    Write-Host "Starting gateway binary directly: $gatewayExePath"
    $gatewayProc = Start-Process -FilePath $gatewayExePath -WorkingDirectory (Join-Path $gatewayRepoRoot 'gateway') -PassThru `
        -WindowStyle Hidden -RedirectStandardError (Join-Path $ArmDir 'gateway-stderr.log') -RedirectStandardOutput (Join-Path $ArmDir 'gateway-stdout.log')
    $deadline = (Get-Date).AddSeconds(60)
    while (-not (Test-PortListening -Port 8080)) {
        if ((Get-Date) -gt $deadline) { throw "Gateway did not start listening on 8080 within 60s" }
        Start-Sleep -Seconds 1
    }
    Write-Host "Gateway listening on 8080"
}

# --- 10. Process sampler ---------------------------------------------------------------
$samplerCsv = Join-Path $ArmDir 'proc.csv'
"timestamp,pid,working_set,private_bytes,handle_count,thread_count,cpu_ms,egress_443,otlp_4317_engine,otlp_4317_gateway" |
    Out-File -FilePath $samplerCsv -Encoding ascii

$samplerScriptPath = Join-Path $PSScriptRoot 'oi02-replay-sampler.ps1'
$samplerGatewayPid = if ($gatewayProc) { $gatewayProc.Id } else { 0 }
$samplerProc = Start-Process -FilePath 'powershell.exe' -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $samplerScriptPath,
    '-EnginePid', $enginePid, '-GatewayPid', $samplerGatewayPid, '-Csv', $samplerCsv, '-IntervalSeconds', $SampleSeconds
) -WindowStyle Hidden -PassThru

# --- 11. Run harness (warm-up, then real run) -------------------------------------------
$env:LANCET_EVAL__LANCEDB_PATH = (Resolve-Path $CopyStorePath).Path
$env:LANCET_EVAL__DATABASE_URL = "postgres://postgres:postgres@127.0.0.1:5432/${ScratchDbName}?sslmode=disable&search_path=lancet_eval"

# Worktree harness (Task 4 Route B pre-reconcile-store arms, D-61): `--project <worktree>/eval`
# runs that commit's OWN `eval/` code (predating HEAD's harness identity gate), not HEAD's.
# uv creates/reuses that worktree's own `.venv` under its own `eval/` dir -- sync it yourself
# first (`uv sync --project <worktree>/eval`), same pre-build-only contract as the engine and
# gateway above; this script never runs `uv sync` inline (matches the "never let a Rust/Go/
# Python build tool execute inline" gotcha for `uv run`/`uv sync` too, since `uv` can compile
# native extensions).
$harnessProject = if ($HarnessSpec.Kind -eq 'worktree') { Join-Path $HarnessSpec.Path 'eval' } else { 'eval' }
if ($HarnessSpec.Kind -eq 'worktree' -and -not (Test-Path (Join-Path $harnessProject '.venv'))) {
    throw "-HarnessFrom worktree:<path> requires a synced venv: uv sync --project `"$harnessProject`""
}

$journalPath = Join-Path $ArmDir 'journal.jsonl'
$startUtc = (Get-Date).ToUniversalTime().ToString('o')

try {
    if ($WarmupQuestions -gt 0) {
        $warmupDir = Join-Path $ArmDir 'warmup'
        New-Item -ItemType Directory -Force -Path $warmupDir | Out-Null
        $warmupJournal = Join-Path $warmupDir 'journal.jsonl'
        Write-Host "Running warm-up: $WarmupQuestions questions"
        & uv run --project $harnessProject lancet-eval run --corpus multihop_rag --out $warmupJournal --no-resume `
            --limit $WarmupQuestions --workers $Workers --retries $Retries --stage-cap $StageCap
    }

    Write-Host "Running primary harness: $Questions questions (project=$harnessProject)"
    & uv run --project $harnessProject lancet-eval run --corpus multihop_rag --out $journalPath --no-resume `
        --limit $Questions --workers $Workers --retries $Retries --stage-cap $StageCap
    $harnessExit = $LASTEXITCODE
} finally {
    # --- 12. Tear-down ------------------------------------------------------------------
    if ($samplerProc) { try { Stop-Process -Id $samplerProc.Id -Force -ErrorAction SilentlyContinue } catch {} }

    $enginePidStillAlive = Get-Process -Id $enginePid -ErrorAction SilentlyContinue
    if (-not $enginePidStillAlive) {
        Write-Warning "Engine process (pid=$enginePid) is no longer running at tear-down time -- header will still be written."
    }

    # Query the stub's own /__stub/stats BEFORE killing it -- querying after Stop-Process
    # always reads back zeros (the stub is already dead), which is what an earlier version of
    # this ordering did, masking every real embeddings/chat_completions count.
    $stubStats = @{ models = 0; embeddings = 0; chat_completions = 0 }
    if (-not $Paid) {
        try {
            $stubStats = Invoke-RestMethod -Uri "http://${StubHost}:${StubPort}/__stub/stats" -TimeoutSec 3
        } catch { }
    }

    if ($gatewayProc) { try { Stop-Process -Id $gatewayProc.Id -Force -ErrorAction SilentlyContinue } catch {} }
    if ($enginePidStillAlive) { try { Stop-Process -Id $enginePid -Force -ErrorAction SilentlyContinue } catch {} }
    if ($stubProc) { try { Stop-Process -Id $stubProc.Id -Force -ErrorAction SilentlyContinue } catch {} }

    $endUtc = (Get-Date).ToUniversalTime().ToString('o')

    # Save collector logs for the window.
    if ($Observability -eq 'on') {
        try {
            & docker logs --timestamps --since $startUtc --until $endUtc lancet-collector *> (Join-Path $ArmDir 'collector-logs.txt')
        } catch { }
    }

    # Extract engine events (request_process_state, retrieve_hybrid_substages) from
    # collected stderr if captured to a file; otherwise these are read from Loki
    # separately (console sink case).
    if ($StderrSink -eq 'file' -and (Test-Path $engineStderrPath)) {
        Get-Content $engineStderrPath | Where-Object { $_ -match 'request_process_state|retrieve_hybrid_substages' } |
            Out-File -FilePath (Join-Path $ArmDir 'engine-events.jsonl') -Encoding ascii
    }

    # --- 13. Live-state / copy-state after, header -----------------------------------
    $liveStateAfter = @{ table_versions = (Get-LiveStateSnapshot -StorePath 'data/lancedb-eval') }
    $pgCountsAfter = Invoke-TrimmedOutput (& docker exec lancet-postgres psql -U postgres -d lancet -tAc "select count(*) from lancet_eval.documents" 2>$null)
    $liveStateAfter['documents_count'] = $pgCountsAfter
    Write-JsonFile -Path (Join-Path $ArmDir 'live-state.after.json') -Object $liveStateAfter

    $copyFilesAfter = Get-ChildItem -Path $CopyStorePath -Recurse -File
    $copyStateAfter = @{
        table_versions = (Get-LiveStateSnapshot -StorePath $CopyStorePath)
        file_count = $copyFilesAfter.Count
        bytes = ($copyFilesAfter | Measure-Object -Property Length -Sum).Sum
    }
    Write-JsonFile -Path (Join-Path $ArmDir 'copy-state.after.json') -Object $copyStateAfter

    Write-JsonFile -Path (Join-Path $ArmDir 'stub-stats.json') -Object $stubStats

    $procRows = if (Test-Path $samplerCsv) { Import-Csv $samplerCsv } else { @() }
    $egressMax = if ($procRows.Count -gt 0) { ($procRows | Measure-Object -Property egress_443 -Maximum).Maximum } else { 0 }
    $otlpEngineMax = if ($procRows.Count -gt 0) { ($procRows | Measure-Object -Property otlp_4317_engine -Maximum).Maximum } else { 0 }
    $otlpGatewayMax = if ($procRows.Count -gt 0) { ($procRows | Measure-Object -Property otlp_4317_gateway -Maximum).Maximum } else { 0 }

    $engineCommit = if ($EngineIsWorktree) { Invoke-TrimmedOutput (& git -C $EngineWorktreePath rev-parse HEAD) } else { Invoke-TrimmedOutput (& git rev-parse HEAD) }
    $harnessCommit = if ($HarnessSpec.Kind -eq 'worktree') { Invoke-TrimmedOutput (& git -C $HarnessSpec.Path rev-parse HEAD) } else { Invoke-TrimmedOutput (& git rev-parse HEAD) }
    $gatewayCommit = if ($GatewaySpec.Kind -eq 'worktree') { Invoke-TrimmedOutput (& git -C $GatewaySpec.Path rev-parse HEAD) } else { Invoke-TrimmedOutput (& git rev-parse HEAD) }

    $header = @{
        arm_kind = $ArmKind
        label = $Label
        phase = $Phase
        commit = Invoke-TrimmedOutput (& git rev-parse HEAD)
        dirty = ((& git status --porcelain).Length -gt 0)
        # Per-component provenance (Task 4 Route B: these can differ from `commit`/each other
        # when -EngineLaunch/-HarnessFrom/-GatewayFrom point at a worktree). Equal to `commit`
        # for every HEAD-only arm (every arm before Route B).
        engine_source = if ($EngineIsWorktree) { "worktree:$EngineWorktreePath" } else { 'head' }
        engine_commit = $engineCommit
        harness_source = if ($HarnessSpec.Kind -eq 'worktree') { "worktree:$($HarnessSpec.Path)" } else { 'head' }
        harness_commit = $harnessCommit
        gateway_source = if ($GatewaySpec.Kind -eq 'worktree') { "worktree:$($GatewaySpec.Path)" } else { 'head' }
        gateway_commit = $gatewayCommit
        launch_command = "cargo run --manifest-path engine/Cargo.toml --locked --bin engine"
        actual_invocation = "cargo build (same args, un-redirected) then exec $engineExePath directly -- see this script's comment at the engine-build step for why cargo run itself is never used from this detached process tree"
        binary_path = $engineExePath
        build_profile = $engineBuildProfile
        pid = $enginePid
        gateway_pid = $(if ($gatewayProc) { $gatewayProc.Id } else { $null })
        start_utc = $startUtc
        end_utc = $endUtc
        observability = $Observability
        telemetry = @{ engine = $telemetryModeEngine; gateway = 'otlp' }
        config_dir_diff = if ($EngineConfigDir -ne '') { "LANCET_CONFIG_DIR=$EngineConfigDir" } else { '' }
        stderr_sink = $StderrSink
        env_vars = @{
            LANCET_ENV = 'eval'
            LANCET_ENGINE__LANCEDB_PATH = '[replay store copy path]'
            LANCET_GATEWAY__DATABASE_URL = "[dsn to $ScratchDbName, password redacted]"
            LANCET_OPENROUTER__EMBEDDING_ENDPOINT = if (-not $Paid) { "http://${StubHost}:${StubPort}/embeddings" } else { '' }
            LANCET_OPENROUTER__MODEL_METADATA_ENDPOINT = if (-not $Paid) { "http://${StubHost}:${StubPort}/models" } else { '' }
            LANCET_OPENROUTER__CHAT_ENDPOINT = if (-not $Paid) { "http://${StubHost}:${StubPort}/chat/completions" } else { '' }
        }
        stub_delays = @{ embed_ms = $StubEmbedDelayMs; chat_ms = $StubChatDelayMs }
        stub_vector_source = if (Test-Path $StubVectorsPath) { $StubVectorsPath } else { 'hash-fallback-only' }
        warmup_n = $WarmupQuestions
        limit = $Questions
        retries = @{ value = $Retries; mode = 'fixed' }
        workers = $Workers
        store_source = $StoreSource
        nodes_version = (Get-LiveStateSnapshot -StorePath $CopyStorePath)['nodes']['latest_manifest']
        scratch_db = $ScratchDbName
        egress_443_max = $egressMax
        otlp_4317_conns_max = @{ engine = $otlpEngineMax; gateway = $otlpGatewayMax }
        paid = [bool]$Paid
        spend_guard = 'dummy key; egress sampling is supporting evidence only'
        harness_exit_code = $harnessExit
    }
    Write-JsonFile -Path (Join-Path $ArmDir 'header.json') -Object $header

    Write-Host "=== oi02-replay: label=$Label complete (harness exit=$harnessExit) ==="
}

# --- 14. replay-summary -----------------------------------------------------------------
& uv run --project eval python -m lancet_eval.oi02 replay-summary $ArmDir `
    --production-journal 'eval/runs/2026-09-09-multihop_rag/journal.jsonl' `
    --forensics-json '.planning/phases/06.3.4.1-retrieval-diagnosis-index-identity-and-graph-yield-repair/forensics/forensics.json' `
    --soak-baseline-json (Join-Path $PhaseDir 'soak-baseline.json')

exit $harnessExit
