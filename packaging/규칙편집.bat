@echo off
chcp 65001 > nul
cd /d "%~dp0app"

if not exist "..\python\python.exe" (
  echo [오류] 내장 Python을 찾을 수 없습니다. 설치.bat을 먼저 실행해 주세요.
  pause
  exit /b 1
)

"%~dp0python\python.exe" -B "%~dp0app\upload_rule_editor_gui.py" "%~dp0app\examples\brand-upload-rules.example.csv"
pause
