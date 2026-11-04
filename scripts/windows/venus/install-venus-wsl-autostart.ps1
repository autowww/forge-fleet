#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Keep Venus Fleet in WSL up across reboot (Windows + WSL2).

  Root cause on headless SSH-only hosts: tasks registered as "Interactive only" at startup
  never run until a console/RDP logon. This script re-registers tasks, adds a PowerShell
  SSH profile hook, optional auto-logon, and a WSL systemd *system* unit for Fleet.

.PARAMETER WindowsPassword
  Optional. When set, registers AtStartup tasks to run as forge whether logged on or not,
  and can enable AutoAdminLogon for forge (headless boot).
#>
param(
    [string]$WindowsPassword = "",
    [string]$Distro = "Ubuntu",
    [string]$RunAsUser = "forge"
)

$ErrorActionPreference = "Stop"
$ProgramData = $env:ProgramData
$BootScript = Join-Path $ProgramData "forge-fleet-venus-boot.ps1"
$PortProxyScript = Join-Path $ProgramData "forge-fleet-venus-portproxy.ps1"
$RepoBoot = Join-Path $PSScriptRoot "forge-fleet-venus-boot.ps1"
$RepoPort = Join-Path $PSScriptRoot "forge-fleet-venus-portproxy.ps1"

if ((Resolve-Path $RepoBoot).Path -ne (Resolve-Path $BootScript).Path) {
    Copy-Item -Force $RepoBoot $BootScript
}
if ((Resolve-Path $RepoPort).Path -ne (Resolve-Path $PortProxyScript).Path) {
    Copy-Item -Force $RepoPort $PortProxyScript
}

# Keep WSL VM alive once started.
$WslConfig = Join-Path $env:USERPROFILE ".wslconfig"
@"
[wsl2]
vmIdleTimeout=-1
"@ | Set-Content -Encoding ascii $WslConfig

function Register-ForgeTask {
    param(
        [string]$Name,
        [string]$Execute,
        [string]$Arguments,
        [string]$User,
        [string]$Password,
        [ValidateSet("Interactive", "Password")]
        [string]$LogonType = "Interactive",
        [object[]]$Triggers
    )
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue
    $action = New-ScheduledTaskAction -Execute $Execute -Argument $Arguments
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Hours 72) `
        -MultipleInstances IgnoreNew
    if ($LogonType -eq "Password" -and $Password) {
        Register-ScheduledTask -TaskName $Name -Action $action -Trigger $Triggers -Settings $settings `
            -User $User -Password $Password -RunLevel Highest | Out-Null
    } else {
        $principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Highest
        Register-ScheduledTask -TaskName $Name -Action $action -Trigger $Triggers -Settings $settings `
            -Principal $principal | Out-Null
    }
}

$bootTrigger = @(New-ScheduledTaskTrigger -AtStartup -RandomDelay (New-TimeSpan -Minutes 1))
$logonTrigger = @(New-ScheduledTaskTrigger -AtLogOn -User $RunAsUser)

if ($WindowsPassword) {
    Register-ForgeTask -Name "ForgeFleetVenusBoot" -Execute "powershell.exe" `
        -Arguments "-NoProfile -ExecutionPolicy Bypass -File `"$BootScript`"" `
        -User $RunAsUser -Password $WindowsPassword -LogonType Password -Triggers $bootTrigger
} else {
    Register-ForgeTask -Name "ForgeFleetVenusBoot" -Execute "powershell.exe" `
        -Arguments "-NoProfile -ExecutionPolicy Bypass -File `"$BootScript`"" `
        -User $RunAsUser -LogonType Interactive -Triggers ($bootTrigger + $logonTrigger)
}

# Legacy task names (keep hold + portproxy in sync).
Register-ForgeTask -Name "ForgeFleetWSLHold" -Execute "wsl.exe" `
    -Arguments "-d $Distro -e sleep 86400" -User $RunAsUser -LogonType Interactive -Triggers $logonTrigger
Register-ForgeTask -Name "ForgeFleetVenusWsl" -Execute "wsl.exe" `
    -Arguments "-d $Distro -e /home/forge/start-fleet-venus.sh" -User $RunAsUser -LogonType Interactive -Triggers $logonTrigger
Unregister-ScheduledTask -TaskName "ForgeFleetVenusPortProxy" -Confirm:$false -ErrorAction SilentlyContinue
$ppAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$PortProxyScript`""
$ppSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 72)
$ppPrincipal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest -LogonType ServiceAccount
Register-ScheduledTask -TaskName "ForgeFleetVenusPortProxy" -Action $ppAction -Trigger @(New-ScheduledTaskTrigger -AtStartup) -Settings $ppSettings -Principal $ppPrincipal | Out-Null

# PowerShell profile: any SSH / console session for forge kicks WSL + Fleet (detached hold survives SSH exit).
$profileDir = Join-Path $env:USERPROFILE "Documents\WindowsPowerShell"
New-Item -ItemType Directory -Force -Path $profileDir | Out-Null
$profilePath = Join-Path $profileDir "Microsoft.PowerShell_profile.ps1"
$marker = "# forge-fleet-venus-autostart"
if (-not (Test-Path $profilePath) -or -not (Select-String -Path $profilePath -Pattern ([regex]::Escape($marker)) -Quiet)) {
    @"

$marker
try {
  `$boot = Join-Path `$env:ProgramData 'forge-fleet-venus-boot.ps1'
  if (Test-Path `$boot) { Start-Process powershell.exe -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File', `$boot) -WindowStyle Hidden }
} catch { }
"@ | Add-Content -Encoding utf8 $profilePath
}

if ($WindowsPassword) {
    $RegPath = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
    Set-ItemProperty -Path $RegPath -Name AutoAdminLogon -Value "1"
    Set-ItemProperty -Path $RegPath -Name DefaultUserName -Value $RunAsUser
    Set-ItemProperty -Path $RegPath -Name DefaultPassword -Value $WindowsPassword
    $domain = $env:COMPUTERNAME
    Set-ItemProperty -Path $RegPath -Name DefaultDomainName -Value $domain
    Write-Host "AutoAdminLogon enabled for $RunAsUser@$domain (reboot required)."
}

Write-Host "Installed $BootScript and scheduled tasks. Run boot script once now:"
Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File `"$BootScript`""
