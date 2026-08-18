# The "one click to play" launcher for Windows -- used for development/
# testing on this machine (the real deployment target is the Endless OS
# laptop; see launch_linux.sh for that one). Starts the backend hidden in
# the background, waits until it's actually ready (it doesn't finish
# starting until it's connected to Cozmo), opens the dashboard in a
# browser "app" window (no tabs/address bar), and stops the backend when
# that window closes.
#
# Run via the double-clickable "Play with Cozmo.bat" -- not meant to be
# run directly, since PowerShell's default execution policy blocks
# double-clicked .ps1 files.

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir

Write-Host "Starting up..."

$backend = Start-Process -FilePath ".venv\Scripts\python.exe" -ArgumentList "backend\app.py" -WindowStyle Hidden -PassThru

$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:5000/api/status" -UseBasicParsing -TimeoutSec 1 | Out-Null
        $ready = $true
        break
    } catch {
        if ($backend.HasExited) { break }
        Start-Sleep -Seconds 1
    }
}

if (-not $ready) {
    Write-Host ""
    Write-Host "Cozmo isn't responding -- make sure this computer's WiFi is joined"
    Write-Host "to his hotspot and he's turned on, then try again."
    if (-not $backend.HasExited) { Stop-Process -Id $backend.Id -Force }
    Read-Host "Press Enter to close"
    exit 1
}

# Checks common install locations rather than assuming Chrome/Edge is on
# PATH -- neither is, by default, even when installed.
$candidates = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
)
$browser = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1

try {
    if ($browser) {
        # --app opens a window with no tabs/address bar. Deliberately not
        # using --kiosk here (unlike launch_linux.sh) -- this is the dev
        # machine, not the kid-facing laptop, and --kiosk hides the window
        # controls entirely, which is annoying to exit repeatedly while testing.
        Start-Process -FilePath $browser -ArgumentList "--app=http://127.0.0.1:5000", "--start-fullscreen" -Wait
    } else {
        Write-Host "No Chrome/Edge found -- opening with the default browser instead"
        Write-Host "(it'll show tabs/address bar, unlike --app mode)."
        Start-Process "http://127.0.0.1:5000"
        Read-Host "Press Enter to stop the backend and close"
    }
} finally {
    if (-not $backend.HasExited) { Stop-Process -Id $backend.Id -Force }
}
