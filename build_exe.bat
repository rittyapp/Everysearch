@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo === Everysearch EXE ビルド ===
echo 作業フォルダ: %CD%
echo.

REM 起動中の EXE があると上書きできない
taskkill /F /IM Everysearch.exe >nul 2>&1

echo [1/3] アイコン生成...
py -3 build_icon.py
if errorlevel 1 (
  echo ERROR: build_icon.py に失敗しました
  goto :error
)
if not exist "everysearch.ico" (
  echo ERROR: everysearch.ico がありません
  goto :error
)

echo [2/3] PyInstaller で EXE 作成...
py -3 -m PyInstaller --noconfirm --clean --windowed --onefile --name Everysearch --icon everysearch.ico --add-data "everysearch.ico;." everything_gui_search.py
if errorlevel 1 (
  echo ERROR: PyInstaller に失敗しました
  echo   py -3 -m pip install pyinstaller pillow
  echo   を試してください。EXE を閉じた状態かも確認してください。
  goto :error
)

if not exist "dist\Everysearch.exe" (
  echo ERROR: dist\Everysearch.exe が生成されませんでした
  goto :error
)

echo [3/3] 同梱ファイルを dist へコピー...
copy /Y "everysearch.ico" "dist\everysearch.ico" >nul
copy /Y "README.MD" "dist\README.MD" >nul
if not exist "dist\icons" mkdir "dist\icons"
xcopy /Y /Q "icons\*" "dist\icons\" >nul

echo.
echo ==============================
echo  完了しました
echo  %CD%\dist\Everysearch.exe
echo ==============================
echo.
pause
exit /b 0

:error
echo.
echo ビルドに失敗しました。
pause
exit /b 1
