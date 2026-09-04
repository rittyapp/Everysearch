@echo off
chcp 932 >nul
setlocal
cd /d "%~dp0.."
set "ROOT=%CD%"

echo === Everysearch EXE �r���h ===
echo ��ƃt�H���_: %ROOT%
echo.

REM �N������ EXE ������Ə㏑���ł��Ȃ�
taskkill /F /IM Everysearch.exe >nul 2>&1

echo [1/3] �A�C�R������...
py -3 "%ROOT%\script\build_icon.py"
if errorlevel 1 (
  echo ERROR: build_icon.py �Ɏ��s���܂���
  goto :error
)
if not exist "%ROOT%\assets\everysearch.ico" (
  echo ERROR: assets\everysearch.ico ������܂���
  goto :error
)

echo [2/3] PyInstaller �� EXE �쐬...
REM --specpath ���g�����߁A--icon / --add-data �͐�΃p�X�œn��
py -3 -m PyInstaller --noconfirm --clean --windowed --onefile --name Everysearch --icon "%ROOT%\assets\everysearch.ico" --add-data "%ROOT%\assets\everysearch.ico;." --add-data "%ROOT%\version.txt;." --hidden-import win32timezone --hidden-import app_paths --hidden-import self_update --distpath "%ROOT%\dist" --workpath "%ROOT%\build" --specpath "%ROOT%\build" "%ROOT%\src\everything_gui_search.py"
if errorlevel 1 (
  echo ERROR: PyInstaller �Ɏ��s���܂���
  echo   py -3 -m pip install pyinstaller pillow pywin32
  echo   �������Ă��������BEXE �����s���łȂ������m�F���Ă��������B
  goto :error
)

if not exist "%ROOT%\dist\Everysearch.exe" (
  echo ERROR: dist\Everysearch.exe ��������܂���ł���
  goto :error
)

echo [3/3] README / version.txt to dist...
copy /Y "%ROOT%\README.MD" "%ROOT%\dist\README.MD" >nul
if exist "%ROOT%\version.txt" (
  copy /Y "%ROOT%\version.txt" "%ROOT%\dist\version.txt" >nul
) else (
  echo 1.3.0> "%ROOT%\dist\version.txt"
)

echo.
echo ==============================
echo  BUILD OK
echo  %ROOT%\dist\Everysearch.exe
echo  Next: script\setup.bat
echo ==============================
echo.
pause
exit /b 0

:error
echo.
echo �r���h�Ɏ��s���܂����B
pause
exit /b 1
