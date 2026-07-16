$ErrorActionPreference = "Stop"
Set-Location "C:\report-downloader"

Write-Host "[1/4] lock 파일 제거..."
if (Test-Path ".git\index.lock") { Remove-Item ".git\index.lock" -Force }
if (Test-Path ".git\HEAD.lock")  { Remove-Item ".git\HEAD.lock"  -Force }

Write-Host "[2/4] 잘못된 커밋 취소..."
git reset HEAD~1 --mixed

Write-Host "[3/4] 모비온 파일 스테이징..."
git add ad_report_downloader/downloader/mobion_base.py
git add ad_report_downloader/downloader/mobion_base_new.py
git add ad_report_downloader/downloader/mobion_banner.py
git add ad_report_downloader/downloader/mobion_daily.py
git add ad_report_downloader/selectors/mobion_banner.yaml
git add ad_report_downloader/selectors/mobion_daily.yaml
git add ad_report_downloader/config.json

Write-Host "[4/4] 커밋..."
git commit -m "feat(mobion): 구 UI 복원 + iframe fix, 신규 UI 보관, config 업데이트"

Write-Host ""
Write-Host "완료! 최근 커밋:"
git log --oneline -3
Read-Host "엔터를 눌러 닫기"
