# Judge-safe local run: listens on all interfaces so phones on the same Wi-Fi can connect.
Set-Location $PSScriptRoot
$uvicorn = Join-Path $PSScriptRoot ".venv\Scripts\uvicorn.exe"
if (-not (Test-Path $uvicorn)) {
    Write-Error "Create the venv first: python -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt"
    exit 1
}
Write-Host "Woza on http://127.0.0.1:8000 (this PC)"
Write-Host "Phones on Wi-Fi: http://<your-PC-IPv4>:8000  (run ipconfig, use Wi-Fi IPv4 — not 0.0.0.0)"
& $uvicorn app.main:app --host 0.0.0.0 --port 8000
