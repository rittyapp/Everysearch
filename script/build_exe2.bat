@echo off
chcp 932 >nul
setlocal
cd /d "%~dp0.."
set "ROOT=%CD%"

echo === Everysearch EXE ビルド ===
echo 作業フォルダ: %ROOT%
echo.

REM 起動中の EXE があると上書きできない
taskkill /F /IM Everysearch.exe >nul 2>&1

echo [1/3] アイコン生成...
py -3 "%ROOT%\script\build_icon.py"
if errorlevel 1 (
  echo ERROR: build_icon.py に失敗しました
  goto :error
)
if not exist "%ROOT%\assets\everysearch.ico" (
  echo ERROR: assets\everysearch.ico がありません
  goto :error
)

echo [2/3] PyInstaller で EXE 作成...
REM --specpath を使うため、--icon / --add-data は絶対パスで渡す
py -3 -m PyInstaller --noconfirm --clean --windowed --onefile --name Everysearch --icon "%ROOT%\assets\everysearch.ico" --add-data "%ROOT%\assets\everysearch.ico;." --hidden-import win32timezone --distpath "%ROOT%\dist" --workpath "%ROOT%\build" --specpath "%ROOT%\build" "%ROOT%\src\everything_gui_search.py"
if errorlevel 1 (
  echo ERROR: PyInstaller に失敗しました
  echo   py -3 -m pip install pyinstaller pillow pywin32
  echo   を試してください。EXE が実行中でないかも確認してください。
  goto :error
)

if not exist "%ROOT%\dist\Everysearch.exe" (
  echo ERROR: dist\Everysearch.exe が見つかりませんでした
  goto :error
)

echo [3/3] README を dist へコピー...
copy /Y "%ROOT%\README.MD" "%ROOT%\dist\README.MD" >nul

echo.
echo ==============================
echo  完了しました
echo  %ROOT%\dist\Everysearch.exe
echo ==============================
echo.
pause
exit /b 0

:error
echo.
echo ビルドに失敗しました。
pause
exit /b 1
