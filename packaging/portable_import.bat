@echo off
chcp 65001 > nul
rem ============================================================
rem  Apply settings brought from another PC.
rem  Run this after install.bat on the new machine.
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
"%PYTHON_EXE%" -B portable_import.py %*
echo.
pause
