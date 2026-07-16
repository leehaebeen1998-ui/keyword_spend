@echo off
chcp 65001 > nul
set "PACKAGE_ROOT=%~dp0..\.."
set "PYTHON_EXE=%PACKAGE_ROOT%\python\python.exe"
set "PLAYWRIGHT_BROWSERS_PATH=%PACKAGE_ROOT%\ms-playwright"
if not exist "%PYTHON_EXE%" (
  echo [ERROR] bundled python was not found: %PYTHON_EXE%
  pause
  exit /b 1
)
"%PYTHON_EXE%" -B "%~dp0login_chrome.py"
