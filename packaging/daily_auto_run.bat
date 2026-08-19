@echo off
chcp 65001 > nul
rem ============================================================
rem  Daily auto run - scheduled task runner
rem  Called by Windows Task Scheduler at 08:00 (Mon-Fri).
rem  No pause. Output goes to app\daily_auto_run.log
rem  NOTE: keep this file ASCII only - cmd.exe mis-parses
rem        non-ASCII text inside batch commands.
rem ============================================================
set "PACKAGE_ROOT=%~dp0"
set "PYTHON_EXE=%PACKAGE_ROOT%python\python.exe"
set "APP_DIR=%PACKAGE_ROOT%app"
set "PLAYWRIGHT_BROWSERS_PATH=%PACKAGE_ROOT%ms-playwright"

if not exist "%PYTHON_EXE%" (
  echo [ERROR] bundled python was not found: %PYTHON_EXE%
  exit /b 1
)
if not exist "%APP_DIR%\daily_auto_run.py" (
  echo [ERROR] daily_auto_run.py was not found in %APP_DIR%
  exit /b 1
)

cd /d "%APP_DIR%"
"%PYTHON_EXE%" -B daily_auto_run.py %*
exit /b %ERRORLEVEL%
