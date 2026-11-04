#Requires -RunAsAdministrator
# Restore Windows PowerShell as SSH shell if WSL default shell breaks scp/ssh.
$regPath = "HKLM:\SOFTWARE\OpenSSH"
Remove-ItemProperty -Path $regPath -Name DefaultShell -ErrorAction SilentlyContinue
Remove-ItemProperty -Path $regPath -Name DefaultShellCommandOption -ErrorAction SilentlyContinue
Restart-Service sshd -Force
Write-Host "OpenSSH default shell reset to built-in (PowerShell). sshd restarted."
