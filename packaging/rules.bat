@echo off
cd /d "%~dp0"

if not exist "%~dp0python\python.exe" (
  echo [ERROR] bundled python was not found.
  echo Please download keyword-spend-processor_*.zip, not Source code zip.
  pause
  exit /b 1
)

"%~dp0python\python.exe" -B "%~dp0app\upload_rule_editor_gui.py" "%~dp0app\examples\brand-upload-rules.example.csv"
pause
