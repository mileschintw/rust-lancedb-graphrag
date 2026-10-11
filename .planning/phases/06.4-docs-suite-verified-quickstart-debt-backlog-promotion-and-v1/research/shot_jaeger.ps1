# Q8: headless Chrome capture of a local Jaeger trace page (read-only; temp profile; no Grafana/Jaeger setting changed).
param([string]$TraceId, [string]$Out)
$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$prof = Join-Path $env:TEMP ("chrome-prof-" + [guid]::NewGuid().ToString("N"))
$args = @("--headless=new","--disable-gpu","--hide-scrollbars","--user-data-dir=$prof","--window-size=1600,1500","--virtual-time-budget=20000","--screenshot=$Out","http://127.0.0.1:16686/trace/$TraceId")
$p = Start-Process -FilePath $chrome -ArgumentList $args -PassThru -Wait -WindowStyle Hidden
"exit=$($p.ExitCode)"
Get-Item $Out | Select-Object Name,Length
Remove-Item -Recurse -Force $prof -ErrorAction SilentlyContinue
