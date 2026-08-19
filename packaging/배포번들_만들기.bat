@echo off
chcp 65001 > nul
setlocal
rem ============================================================
rem   keyword_spend - Full runnable bundle builder
rem   Put this file at the program root (same folder as run.bat)
rem   Output: a single .zip you can copy to another PC
rem
rem   Build order:
rem     1) tar.exe (fast).  Errors go to bundle_build.log
rem     2) if tar fails or the zip is suspiciously small,
rem        fall back to PowerShell Compress-Archive
rem ============================================================
cd /d "%~dp0"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "TS=%%i"
if "%TS%"=="" set "TS=manual"
set "OUT=%~dp0keyword_spend_full_%TS%.zip"
set "BUILD_LOG=%~dp0bundle_build.log"

echo Building full bundle (may take a few minutes for python/browser)...
echo Output: %OUT%
echo Log   : %BUILD_LOG%
echo.

set "TAR_OK="
where tar.exe >nul 2>&1
if errorlevel 1 (
  echo [INFO] tar.exe not found - using PowerShell instead.
  goto ps_build
)

tar -a -c -f "%OUT%" ^
  --exclude="*chrome_profile*" ^
  --exclude="*logs*" ^
  --exclude="*downloads*" ^
  --exclude="*__pycache__*" ^
  --exclude="*.log" ^
  --exclude="*.pyc" ^
  --exclude="*.tmp" ^
  --exclude="*BrowserMetrics*" ^
  --exclude="*budget_secrets.dat" ^
  --exclude="*budget_alert_state.json" ^
  --exclude="*keyword_spend_full_*.zip" ^
  --exclude="*keyword_spend_code_*.zip" ^
  app bots python ms-playwright run.bat install.bat rules.bat README.md ^
  daily_auto_run.bat daily_auto_run_register.bat daily_auto_run_check.bat ^
  > "%BUILD_LOG%" 2>&1
if errorlevel 1 goto tar_failed

rem -- sanity check: a real bundle is far larger than 10 MB ----
for %%A in ("%OUT%") do set "OUT_SIZE=%%~zA"
if "%OUT_SIZE%"=="" set "OUT_SIZE=0"
if %OUT_SIZE% LSS 10485760 goto tar_failed
set "TAR_OK=1"
goto done

:tar_failed
echo [WARN] tar build failed or produced a bad zip. Details:
echo ------------------------------------------------------------
type "%BUILD_LOG%" 2>nul
echo ------------------------------------------------------------
echo Falling back to PowerShell Compress-Archive...
echo.
if exist "%OUT%" del /q "%OUT%"

:ps_build
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$root=Get-Location;" ^
  "$out='%OUT%';" ^
  "$stage=Join-Path $env:TEMP ('ks_bundle_'+[guid]::NewGuid().ToString('N'));" ^
  "New-Item -ItemType Directory -Path $stage | Out-Null;" ^
  "$targets=@('app','bots','python','ms-playwright','run.bat','install.bat','rules.bat','README.md'," ^
  "  'daily_auto_run.bat','daily_auto_run_register.bat','daily_auto_run_check.bat');" ^
  "$exDir=@('chrome_profile','logs','downloads','__pycache__','BrowserMetrics');" ^
  "$exFile=@('*.log','*.pyc','*.tmp','budget_secrets.dat','budget_alert_state.json','keyword_spend_full_*.zip','keyword_spend_code_*.zip');" ^
  "foreach($t in $targets){ $src=Join-Path $root $t; if(-not(Test-Path $src)){continue};" ^
  "  if(Test-Path $src -PathType Container){" ^
  "    robocopy $src (Join-Path $stage $t) /E /XD $exDir /XF $exFile /NFL /NDL /NJH /NJS /NP | Out-Null;" ^
  "    if($LASTEXITCODE -ge 8){ throw ('robocopy failed on '+$t) }" ^
  "  } else { Copy-Item $src (Join-Path $stage $t) } };" ^
  "if(Test-Path $out){ Remove-Item $out -Force };" ^
  "Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $out -CompressionLevel Optimal;" ^
  "Remove-Item $stage -Recurse -Force;" ^
  "Write-Host ('[PS] zip created: '+(Get-Item $out).Length+' bytes')" ^
  >> "%BUILD_LOG%" 2>&1
if errorlevel 1 (
  echo.
  echo [ERROR] PowerShell build failed as well. Details:
  echo ------------------------------------------------------------
  type "%BUILD_LOG%" 2>nul
  echo ------------------------------------------------------------
  pause
  exit /b 1
)

:done
for %%A in ("%OUT%") do set "OUT_SIZE=%%~zA"
if "%OUT_SIZE%"=="" set "OUT_SIZE=0"
if %OUT_SIZE% LSS 10485760 (
  echo.
  echo [ERROR] bundle is too small: %OUT_SIZE% bytes. Details:
  echo ------------------------------------------------------------
  type "%BUILD_LOG%" 2>nul
  echo ------------------------------------------------------------
  pause
  exit /b 1
)

set /a OUT_MB=%OUT_SIZE% / 1048576
echo.
echo [DONE] Bundle created (%OUT_MB% MB):
echo   %OUT%
echo.
echo Note: login sessions are NOT included (chrome_profile excluded).
echo Encrypted secrets (budget_secrets.dat) are NOT included either -
echo DPAPI data cannot be decrypted on another PC anyway.
echo Account settings (config.json, budget_config.json) ARE included.
echo.
echo Setup on the new PC:
echo   1) unzip, run install.bat
echo   2) run the manual Google login batch once (Google Ads sign in)
echo   3) budget alerts: re-enter the Gmail app password in the
echo      settings window, then register the schedule
echo      (see docs\budget guide section 9)
pause
