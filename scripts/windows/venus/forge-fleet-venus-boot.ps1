# Ensure Ubuntu WSL is up, Fleet is listening in WSL, and Windows portproxy is set.
$ErrorActionPreference = "Stop"
$Distro = "Ubuntu"

function Test-FleetHealthyInWsl {
    try {
        wsl -d $Distro -e curl -fsS -m 5 http://127.0.0.1:18766/v1/health | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

if (-not (Test-FleetHealthyInWsl)) {
    Start-Process -FilePath "wsl.exe" -ArgumentList @("-d", $Distro, "-e", "sleep", "86400") -WindowStyle Hidden | Out-Null
    Start-Sleep -Seconds 4
    $fleetStart = @"
if systemctl is-enabled forge-fleet.service >/dev/null 2>&1; then
  systemctl start forge-fleet.service || true
else
  /home/forge/start-fleet-venus.sh
fi
"@
    wsl -d $Distro -u root -e bash -lc $fleetStart | Out-Null
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        if (Test-FleetHealthyInWsl) { break }
        Start-Sleep -Seconds 2
    }
}

if (-not (Test-FleetHealthyInWsl)) {
    Write-Error "Fleet health check failed inside WSL after boot steps"
}

& "$PSScriptRoot\forge-fleet-venus-portproxy.ps1"
