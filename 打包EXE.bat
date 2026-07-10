@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "WEB_APP_NAME=CompetitorMonitorWeb"
set "TASK_APP_NAME=CompetitorMonitorTaskRunner"
set "PYTHONNOUSERSITE=1"
set "PYTHONUSERBASE=%CD%\.py_user_base"

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Please install Python or add it to PATH.
  pause
  exit /b 1
)

echo Checking runtime dependencies...
python -c "import openpyxl, yaml, rebrowser_playwright" >nul 2>nul
if errorlevel 1 (
  echo Installing runtime dependencies...
  python -m pip install -r competitor_monitor\requirements.txt
  if errorlevel 1 (
    echo Failed to install runtime dependencies.
    pause
    exit /b 1
  )
)

python -m pip show pyinstaller >nul 2>nul
if errorlevel 1 (
  echo Installing PyInstaller...
  python -m pip install pyinstaller
  if errorlevel 1 (
    echo Failed to install PyInstaller.
    pause
    exit /b 1
  )
)

for /f "delims=" %%I in ('python -c "import pathlib, rebrowser_playwright; print(pathlib.Path(rebrowser_playwright.__file__).resolve().parent / 'driver')"') do set "REBROWSER_PLAYWRIGHT_DRIVER=%%I"
if not exist "%REBROWSER_PLAYWRIGHT_DRIVER%\node.exe" (
  echo rebrowser_playwright driver was not found: %REBROWSER_PLAYWRIGHT_DRIVER%
  pause
  exit /b 1
)

echo Building Web console exe...
python -m PyInstaller --noconfirm --clean --onedir --noconsole --name "%WEB_APP_NAME%" --paths "competitor_monitor" --add-data "web_frontend;web_frontend" --add-data "competitor_monitor\config.example.yaml;competitor_monitor" --add-data "%REBROWSER_PLAYWRIGHT_DRIVER%;rebrowser_playwright\driver" "competitor_monitor\web_server.py"
if errorlevel 1 (
  echo Web console build failed.
  pause
  exit /b 1
)

echo Building background task runner exe...
python -m PyInstaller --noconfirm --clean --onedir --noconsole --name "%TASK_APP_NAME%" --paths "competitor_monitor" --add-data "competitor_monitor\config.example.yaml;competitor_monitor" --add-data "%REBROWSER_PLAYWRIGHT_DRIVER%;rebrowser_playwright\driver" "competitor_monitor\run_web_task.py"
if errorlevel 1 (
  echo Task runner build failed.
  pause
  exit /b 1
)

echo Copying frontend and config template beside the Web console exe...
xcopy /E /I /Y web_frontend "dist\%WEB_APP_NAME%\web_frontend" >nul
if not exist "dist\%WEB_APP_NAME%\competitor_monitor" mkdir "dist\%WEB_APP_NAME%\competitor_monitor"
copy /Y "competitor_monitor\config.example.yaml" "dist\%WEB_APP_NAME%\competitor_monitor\config.example.yaml" >nul

echo Copying config template beside the task runner exe...
if not exist "dist\%TASK_APP_NAME%\competitor_monitor" mkdir "dist\%TASK_APP_NAME%\competitor_monitor"
copy /Y "competitor_monitor\config.example.yaml" "dist\%TASK_APP_NAME%\competitor_monitor\config.example.yaml" >nul

echo.
echo Build completed.
echo Web console: dist\%WEB_APP_NAME%\%WEB_APP_NAME%.exe
echo Task runner: dist\%TASK_APP_NAME%\%TASK_APP_NAME%.exe
echo.
echo Before production use, place your Excel file and edit competitor_monitor\config.yaml in the runtime folder.
pause
