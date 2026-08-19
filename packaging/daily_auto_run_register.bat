@echo off
chcp 65001 > nul
rem ============================================================
rem  Register / unregister the daily auto run task
rem
rem  Default: 08:00, Monday to Friday
rem    Tue-Fri : previous day
rem    Monday  : Friday + Saturday + Sunday (3 days)
rem
rem  Usage:
rem    double click        register with the defaults
rem    /DELETE             remove the task
rem    /TIME 09:00         change the start time
rem    /DAYS MON,TUE       change the days
rem ============================================================
setlocal

set "TASK_NAME=KeywordSpend_Daily"
set "RUNNER=%~dp0daily_auto_run.bat"
set "RUN_TIME=08:00"
set "RUN_DAYS=MON,TUE,WED,THU,FRI"

:parse
if "%~1"=="" goto after_parse
if /I "%~1"=="/DELETE" goto delete_task
if /I "%~1"=="/TIME" (
  set "RUN_TIME=%~2"
  shift
)
if /I "%~1"=="/DAYS" (
  set "RUN_DAYS=%~2"
  shift
)
shift
goto parse
:after_parse

if not exist "%RUNNER%" (
  echo [ERROR] runner not found: %RUNNER%
  pause
  exit /b 1
)

echo ============================================================
echo   Task name : %TASK_NAME%
echo   Starts at : %RUN_TIME%
echo   Days      : %RUN_DAYS%
echo   Command   : %RUNNER%
echo ============================================================
echo.

schtasks /Create /TN "%TASK_NAME%" /TR "\"%RUNNER%\"" /SC WEEKLY /D %RUN_DAYS% ^
  /ST %RUN_TIME% /RL LIMITED /F
if errorlevel 1 (
  echo.
  echo [ERROR] failed to register the scheduled task.
  pause
  exit /b 1
)

echo.
echo [OK] scheduled task registered.
echo.
echo Notes:
echo   - The PC must be powered on and signed in at %RUN_TIME%.
echo   - Naver uses the API now, so no login session is needed.
echo     Google and other media still use the saved Chrome profile;
echo     if that session expires the run fails and an e-mail is sent.
echo   - The login bot is NOT run automatically (it waits for Enter).
echo   - Log: app\daily_auto_run.log
echo.
echo To run it once right now:
echo   schtasks /Run /TN "%TASK_NAME%"
echo.
pause
exit /b 0

:delete_task
schtasks /Delete /TN "%TASK_NAME%" /F
if errorlevel 1 (
  echo [ERROR] failed to delete the scheduled task ^(maybe it was not registered^).
  pause
  exit /b 1
)
echo [OK] scheduled task removed.
pause
exit /b 0
