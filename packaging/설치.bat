@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo [키워드별 소진내역 가공 프로그램 설치]
echo.

if not exist "python\python.exe" (
  echo [오류] 내장 Python을 찾을 수 없습니다.
  echo 압축을 다시 풀거나 배포 파일을 확인해 주세요.
  pause
  exit /b 1
)

if not exist "app\upload_processor_gui.py" (
  echo [오류] app 폴더를 찾을 수 없습니다.
  pause
  exit /b 1
)

mkdir "%LOCALAPPDATA%\BrandUploadProcessor" > nul 2> nul
mkdir "%TEMP%\BrandUploadProcessor\outputs" > nul 2> nul

"%~dp0python\python.exe" -B -c "import tkinter, openpyxl; print('runtime ok')"
if %errorlevel% neq 0 (
  echo [오류] 실행 환경 점검에 실패했습니다.
  pause
  exit /b 1
)

echo.
echo [완료] 설치 점검이 끝났습니다.
echo 다음부터는 실행.bat을 더블클릭해 주세요.
pause
