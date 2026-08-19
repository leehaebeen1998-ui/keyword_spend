@echo off
chcp 65001 > nul
rem  Dry run check - verifies settings without downloading anything.
call "%~dp0daily_auto_run.bat" --dry-run
echo.
pause
