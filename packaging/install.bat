@echo off
cd /d "%~dp0"

echo [Keyword Spend Processor] install check
echo.

if not exist "%~dp0python\python.exe" (
  echo [ERROR] bundled python was not found:
  echo %~dp0python\python.exe
  echo.
  echo Please download keyword-spend-processor_*.zip, not Source code zip.
  pause
  exit /b 1
)

if not exist "%~dp0app\upload_processor_gui.py" (
  echo [ERROR] app files were not found:
  echo %~dp0app\upload_processor_gui.py
  pause
  exit /b 1
)

mkdir "%LOCALAPPDATA%\BrandUploadProcessor" > nul 2> nul
mkdir "%TEMP%\BrandUploadProcessor\outputs" > nul 2> nul

"%~dp0python\python.exe" -B -c "import tkinter, openpyxl; print('runtime ok')"
if errorlevel 1 (
  echo [ERROR] runtime check failed.
  pause
  exit /b 1
)

echo.
echo [OK] install check completed.
echo Use run.bat to start the program.
pause
