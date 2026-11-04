#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"
$SecretPath = Join-Path $env:ProgramData "forge-fleet-venus-autologon.secret"
$bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$pass = [Convert]::ToBase64String($bytes) -replace '[+/=]', 'x'
if ($pass.Length -lt 20) { $pass = ($pass + "Aa1!Zz9@") }

net user forge $pass | Out-Null
Set-Content -Path $SecretPath -Value $pass -Encoding ascii -NoNewline
icacls $SecretPath /inheritance:r /grant:r "${env:COMPUTERNAME}\forge:(R)" "Administrators:(F)" "SYSTEM:(F)" | Out-Null

& (Join-Path $env:ProgramData "install-venus-wsl-autostart.ps1") -WindowsPassword $pass
& (Join-Path $env:ProgramData "forge-fleet-venus-boot.ps1")

Write-Host "Auto-logon configured for forge. Password stored in $SecretPath (forge read-only)."
$wl = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" -ErrorAction SilentlyContinue
Write-Host "AutoAdminLogon=$($wl.AutoAdminLogon) DefaultUserName=$($wl.DefaultUserName)"
