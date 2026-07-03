@echo off
cd /d "%~dp0"

if not exist "%~dp0python\python.exe" (
  echo [ERROR] bundled python was not found.
  echo Please download keyword-spend-processor_*.zip, not Source code zip.
  pause
  exit /b 1
)

if not exist "%~dp0app\upload_processor_gui.py" (
  echo [ERROR] app files were not found.
  pause
  exit /b 1
)

"%~dp0python\python.exe" -B "%~dp0app\upload_processor_gui.py"
pause
