@echo off
chcp 932 >nul
setlocal
cd /d "%~dp0"
echo.
echo === Everysearch setup ===
if not exist "%~dp0..\dist\Everysearch.exe" (
  echo ERROR: dist\Everysearch.exe missing
  echo Run build_exe2.bat first.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
set EC=%ERRORLEVEL%
echo.
if %EC% neq 0 (
  echo SETUP FAILED %EC%
) else (
  echo SETUP OK - use Desktop shortcut Everysearch
)
pause
exit /b %EC%