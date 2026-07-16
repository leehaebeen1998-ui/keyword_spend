@echo off
cd /d "C:\report-downloader"
if exist ".git\index.lock" del /f ".git\index.lock"
git add -A
git status --short
git commit -m "Kakao: keyring auto-login + calendar date range fix"
git pull --rebase origin main
git push origin main
echo Done!
pause
