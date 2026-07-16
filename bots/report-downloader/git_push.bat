@echo off
cd /d "C:\report-downloader"

set GIT="C:\Program Files\Git\cmd\git.exe"

if exist ".git\index.lock" del /f ".git\index.lock"

%GIT% add -A
%GIT% status --short

set /p msg=Commit message (enter for auto update): 
if "%msg%"=="" set msg=auto update

%GIT% commit -m "%msg%"
%GIT% pull --rebase origin main
%GIT% push origin main

echo Done!
pause
