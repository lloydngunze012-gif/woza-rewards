# LAN demo: must bind 0.0.0.0 so phones on the same Wi-Fi can connect (not 127.0.0.1).
Set-Location $PSScriptRoot

$uvicorn = Join-Path $PSScriptRoot ".venv\Scripts\uvicorn.exe"
if (-not (Test-Path $uvicorn)) {
    Write-Error "Create the venv first: python -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt"
    exit 1
}

function Get-LanIPv4 {
    $candidates = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object {
            $_.IPAddress -notlike "127.*" -and
            $_.IPAddress -notlike "169.254.*" -and
            $_.PrefixOrigin -ne "WellKnown"
        } |
        Sort-Object InterfaceMetric
    foreach ($c in $candidates) {
        if ($c.InterfaceAlias -match "Wi-Fi|Wireless|WLAN") { return $c.IPAddress }
    }
    return ($candidates | Select-Object -First 1).IPAddress
}

$lan = Get-LanIPv4
Write-Host ""
Write-Host "Woza Rewards (LAN demo)" -ForegroundColor Cyan
Write-Host "  This PC:  http://127.0.0.1:8000"
if ($lan) {
    Write-Host "  Phone:    http://${lan}:8000  (same Wi-Fi; do not use 0.0.0.0 in the browser)" -ForegroundColor Green
} else {
    Write-Host "  Phone:    http://<your-Wi-Fi-IPv4>:8000  (run ipconfig)" -ForegroundColor Yellow
}
Write-Host "  Health:   http://127.0.0.1:8000/api/health"
Write-Host ""

$on8000 = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($on8000) {
    $bad = $on8000 | Where-Object { $_.LocalAddress -eq "127.0.0.1" }
    if ($bad) {
        Write-Host "Stopping old server bound to 127.0.0.1 only (phones cannot connect)..." -ForegroundColor Yellow
        $bad | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Seconds 1
    }
}

& $uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
