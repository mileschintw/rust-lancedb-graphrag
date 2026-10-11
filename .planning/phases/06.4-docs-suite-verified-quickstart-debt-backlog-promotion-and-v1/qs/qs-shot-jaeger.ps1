# Copy of research/shot_jaeger.ps1 (06.4 plan 08). Read-only capture against 127.0.0.1.
# Headless Chrome capture of a local Jaeger trace page (temp profile removed; no Grafana or
# Jaeger setting changed). Changes from the research copy: the output's parent directory is
# created first (Chrome's --screenshot does not create directories, and plan 06.4-09 writes
# into docs/assets/, which does not exist yet), the output is resolved to a full path, and
# the argument list is not called $args.
param([string]$TraceId, [string]$Out)
$Out = [System.IO.Path]::GetFullPath($Out)
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Out) | Out-Null
$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$prof = Join-Path $env:TEMP ("chrome-prof-" + [guid]::NewGuid().ToString("N"))
$chromeArgs = @("--headless=new","--disable-gpu","--hide-scrollbars","--user-data-dir=$prof","--window-size=1600,1500","--virtual-time-budget=20000","--screenshot=$Out","http://127.0.0.1:16686/trace/$TraceId")
$p = Start-Process -FilePath $chrome -ArgumentList $chromeArgs -PassThru -Wait -WindowStyle Hidden
"exit=$($p.ExitCode)"
Get-Item $Out | Select-Object Name,Length
Remove-Item -Recurse -Force $prof -ErrorAction SilentlyContinue
