@echo off
title Tattoo Bot
cd /d C:\Projects\tattoo_bot
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

echo ========================================
echo   Tattoo Bot - tatoo_asbest_best_bot
echo ========================================
echo.
echo Killing old instances...

REM Убиваем все python.exe запущенные из этой директории (main.py и его subprocess'ы)
powershell -NoProfile -Command ^
  "$procs = Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'tattoo_bot' }; foreach ($p in $procs) { Write-Host ('Killing PID: ' + $p.ProcessId); Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }; Start-Sleep -Seconds 2"

echo.
echo Starting bot...
echo ----------------------------------------

python main.py

echo.
echo ----------------------------------------
echo Bot stopped. Press any key...
pause >nul
