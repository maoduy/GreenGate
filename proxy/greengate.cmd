@echo off
REM Force GreenGate to re-read the allowlist from the Google Sheet right now.
REM Usage:  greengate update   (or just: greengate)
setlocal
set PORT=8080
if /I "%~1"=="test" (
  powershell.exe -ExecutionPolicy Bypass -File "%ProgramFiles%\GreenGate\greengate-test.ps1" %2 %3 %4 %5
  exit /b
)
if /I "%~1"=="unlock" (
  powershell.exe -ExecutionPolicy Bypass -File "%ProgramFiles%\GreenGate\greengate-pause.ps1"
  exit /b
)
if /I "%~1"=="pause" (
  powershell.exe -ExecutionPolicy Bypass -File "%ProgramFiles%\GreenGate\greengate-pause.ps1" %2 %3
  exit /b
)
if /I "%~1"=="resume" (
  powershell.exe -ExecutionPolicy Bypass -File "%ProgramFiles%\GreenGate\greengate-pause.ps1" -Resume
  exit /b
)
if /I "%~1"=="uninstall" (
  powershell.exe -ExecutionPolicy Bypass -File "%ProgramFiles%\GreenGate\reset-clean.ps1"
  exit /b
)
if /I "%~1"=="pair" (
  "%ProgramFiles%\GreenGate\GreenGate-Agent.exe" --config "%ProgramData%\GreenGate\agent\%USERNAME%.json" pair %2 %3 %4 %5
  exit /b
)
if /I "%~1"=="consent" (
  "%ProgramFiles%\GreenGate\GreenGate-Agent.exe" --config "%ProgramData%\GreenGate\agent\%USERNAME%.json" consent %2 %3 %4
  goto :eof
)
if /I "%~1"=="drive" (
  "%ProgramFiles%\GreenGate\GreenGate-Agent.exe" --config "%ProgramData%\GreenGate\agent\%USERNAME%.json" drive %2 %3 %4
  goto :eof
)
if /I "%~1"=="agent" (
  "%ProgramFiles%\GreenGate\GreenGate-Agent.exe" --config "%ProgramData%\GreenGate\agent\%USERNAME%.json" %2 %3 %4 %5
  exit /b
)
if /I "%~1"=="status" (set ACTION=/) else (set ACTION=/update)
curl.exe -s --max-time 60 -x http://127.0.0.1:%PORT% "http://greengate.local%ACTION%"
if errorlevel 1 echo Khong ket noi duoc GreenGate tren 127.0.0.1:%PORT%.
endlocal
