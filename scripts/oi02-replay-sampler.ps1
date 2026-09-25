#Requires -Version 5.1
<#
.SYNOPSIS
  Process sampler for scripts/oi02-replay.ps1 (06.3.4.1-07 Task 2). Runs as its own
  Start-Process child rather than a Start-Job background job -- Start-Job was empirically
  observed to produce zero samples for the whole run in this script's fully-detached process
  tree (root cause not pinned down; Start-Process is the pattern already proven reliable
  elsewhere in this script, so the sampler follows it too rather than debugging Start-Job
  further).
#>
param(
    [Parameter(Mandatory = $true)][int]$EnginePid,
    [int]$GatewayPid = 0,
    [Parameter(Mandatory = $true)][string]$Csv,
    [int]$IntervalSeconds = 5
)

while ($true) {
    try {
        $p = Get-Process -Id $EnginePid -ErrorAction SilentlyContinue
        if (-not $p) { break }
        # Any TCP state, not just Established: an OTLP gRPC export connection can be caught
        # mid-handshake (SynSent) or just-closed (TimeWait/CloseWait) by a point sample,
        # especially on a short run with few export cycles.
        $egress443 = (Get-NetTCPConnection -OwningProcess $EnginePid -ErrorAction SilentlyContinue |
            Where-Object { $_.RemotePort -eq 443 }).Count
        $otlpEngine = (Get-NetTCPConnection -OwningProcess $EnginePid -ErrorAction SilentlyContinue |
            Where-Object { $_.RemotePort -eq 4317 }).Count
        $otlpGateway = 0
        if ($GatewayPid -gt 0) {
            $otlpGateway = (Get-NetTCPConnection -OwningProcess $GatewayPid -ErrorAction SilentlyContinue |
                Where-Object { $_.RemotePort -eq 4317 }).Count
        }
        $line = "$(Get-Date -Format o),$EnginePid,$($p.WorkingSet64),$($p.PrivateMemorySize64),$($p.HandleCount),$($p.Threads.Count),$($p.TotalProcessorTime.TotalMilliseconds),$egress443,$otlpEngine,$otlpGateway"
        Add-Content -Path $Csv -Value $line
    } catch { }
    Start-Sleep -Seconds $IntervalSeconds
}
