@echo off
REM OpenSSH on Windows invokes: forge-ssh-wsl.cmd [remote command args...]
setlocal
if "%~1"=="" (
  wsl.exe -d Ubuntu -- bash -l
  exit /b %ERRORLEVEL%
)
wsl.exe -d Ubuntu -- %*
exit /b %ERRORLEVEL%
