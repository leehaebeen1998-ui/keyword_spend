@echo off
chcp 65001 >nul
echo.
echo === 보고서 자동화 폴더 로컬 이동 ===
echo.
echo 이동 경로: C:\report-downloader\
echo.
echo Chrome이 실행 중이면 먼저 닫아주세요!
pause

:: 대상 폴더 생성
if not exist "C:\report-downloader" mkdir "C:\report-downloader"

:: 파일 복사 (숨김파일 포함, .git 포함)
robocopy "%~dp0." "C:\report-downloader" /E /COPYALL /XF "index.lock" /NFL /NDL /NJH /NJS

echo.
echo 복사 완료!
echo.
echo 다음 단계:
echo 1. Claude Cowork 에서 폴더를 C:\report-downloader 로 다시 선택하세요
echo 2. 기존 OneDrive 폴더는 삭제하거나 백업으로 보관하세요
echo.
pause
