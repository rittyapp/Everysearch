@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM 利用可能な Python で起動（パス混在時もスクリプト側で Tcl/Tk を補正）
where py >nul 2>&1
if %ERRORLEVEL%==0 (
  py -3 "%~dp0everything_gui_search.py"
) else (
  python "%~dp0everything_gui_search.py"
)
