@echo off
chcp 65001 > nul
set "PACKAGE_ROOT=%~dp0..\.."
set "PYTHON_EXE=%PACKAGE_ROOT%\python\python.exe"
if not exist "%PYTHON_EXE%" (
  echo [오류] 내장 Python을 찾을 수 없습니다: %PYTHON_EXE%
  pause
  exit /b 1
)
cd /d "%~dp0"
"%PYTHON_EXE%" -B "%~dp0모비온_비밀번호설정.py"
