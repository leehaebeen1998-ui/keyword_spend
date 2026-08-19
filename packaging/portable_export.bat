@echo off
chcp 65001 > nul
rem ============================================================
rem  Export settings for moving this program to another PC,
rem  then build the full distribution zip.
rem  Keep this file ASCII only.
rem ============================================================
set "PACKAGE_ROOT=%~dp0"
set "PYTHON_EXE=%PACKAGE_ROOT%python\python.exe"
if not exist "%PYTHON_EXE%" (
  echo [ERROR] bundled python was not found: %PYTHON_EXE%
  pause
  exit /b 1
)
cd /d "%PACKAGE_ROOT%app"
"%PYTHON_EXE%" -B portable_export.py --build-bundle %*
echo.
pause
