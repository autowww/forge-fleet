#Requires -RunAsAdministrator
# Land SSH sessions in WSL Ubuntu (interactive + remote commands + scp/sftp unchanged).
param(
    [string]$Distro = "Ubuntu",
    [string]$Wrapper = "$env:ProgramData\forge-ssh-wsl.cmd"
)

$ErrorActionPreference = "Stop"
$wsl = Join-Path $env:WINDIR "System32\wsl.exe"
if (-not (Test-Path $wsl)) { throw "wsl.exe missing" }

$cmdContent = @"
@echo off
setlocal
if "%~1"=="" (
  wsl.exe -d $Distro -- bash -l
  exit /b %ERRORLEVEL%
)
wsl.exe -d $Distro -- %*
exit /b %ERRORLEVEL%
"@
Set-Content -Path $Wrapper -Value $cmdContent -Encoding ascii

$regPath = "HKLM:\SOFTWARE\OpenSSH"
if (-not (Test-Path $regPath)) { New-Item -Path $regPath -Force | Out-Null }
New-ItemProperty -Path $regPath -Name DefaultShell -Value $Wrapper -PropertyType String -Force | Out-Null
Remove-ItemProperty -Path $regPath -Name DefaultShellCommandOption -ErrorAction SilentlyContinue

Restart-Service sshd -Force
Write-Host "SSH default shell -> $Wrapper (WSL $Distro). Test: ssh venus uname -a"
