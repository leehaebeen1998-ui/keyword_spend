@echo off
chcp 65001 > nul
cd /d C:\report-downloader

echo [1/4] lock 파일 제거...
if exist .git\index.lock del /f .git\index.lock
if exist .git\HEAD.lock del /f .git\HEAD.lock

echo [2/4] 잘못된 커밋 되돌리기 (reset HEAD~1)...
git reset HEAD~1 --mixed
if errorlevel 1 (
    echo ERROR: reset 실패
    pause
    exit /b 1
)

echo [3/4] 모비온 파일만 스테이징...
git add ad_report_downloader/downloader/mobion_base.py
git add ad_report_downloader/downloader/mobion_base_new.py
git add ad_report_downloader/downloader/mobion_banner.py
git add ad_report_downloader/downloader/mobion_daily.py
git add ad_report_downloader/selectors/mobion_banner.yaml
git add ad_report_downloader/selectors/mobion_daily.yaml
git add ad_report_downloader/config.json

echo [4/4] 커밋...
git commit -m "feat(mobion): 구 UI 복원 (manage.mobon.net) + iframe fix

- mobion_base.py: 구 UI, _switch_account iframe.mfp-iframe 수정
- mobion_base_new.py: 신규 UI 보관 (adcenter.mobon.net)
- mobion_banner.yaml / mobion_daily.yaml: old_ui_path 수정
- config.json: thlaw_01 형사 주간보고서, thlaw_02 마약 주간보고서2, thlaw_03 배너주간보고"

echo.
echo 완료! git log:
git log --oneline -3
pause
