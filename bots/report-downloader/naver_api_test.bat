@echo off
chcp 65001 > nul
REM ============================================================
REM  Naver API downloader one-shot test (safe: separate output)
REM  - brand: config.json active_brand (Taeha daily)
REM  - media: naver only, date: yesterday
REM  - results + manifest go to downloads_api_test\ so the normal
REM    pipeline (downloads\ + manifest.json) is NOT touched.
REM ============================================================
set "PACKAGE_ROOT=%~dp0..\.."
set "PYTHON_EXE=%PACKAGE_ROOT%\python\python.exe"
set "TEST_ROOT=%PACKAGE_ROOT%\downloads_api_test"
if not exist "%PYTHON_EXE%" (
  echo [ERROR] bundled python was not found: %PYTHON_EXE%
  pause
  exit /b 1
)
cd /d "%~dp0ad_report_downloader"
for /f %%i in ('"%PYTHON_EXE%" -B -c "import datetime;print((datetime.date.today()-datetime.timedelta(days=1)).strftime('%%Y%%m%%d'))"') do set "YDAY=%%i"
echo [INFO] test date: %YDAY%
"%PYTHON_EXE%" -B -c "import json,pathlib,os; p=pathlib.Path('config.json'); d=json.loads(p.read_text(encoding='utf-8-sig')); d['save_root_path']=os.path.abspath(r'%TEST_ROOT%'); q=pathlib.Path('config_api_test.json'); q.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8'); print('test config ready. api_key set:', bool(d.get('naver_api',{}).get('api_key')))"
"%PYTHON_EXE%" -B cli.py --config config_api_test.json --start %YDAY% --end %YDAY% --media naver --manifest-out "%TEST_ROOT%" > "naver_api_test.log" 2>&1
set "DL_EXIT=%ERRORLEVEL%"
type "naver_api_test.log"
echo.
if "%DL_EXIT%"=="0" (
  echo [OK] test finished. files under %TEST_ROOT%
) else (
  echo [ERROR] test failed with exit code %DL_EXIT%. See naver_api_test.log
)
pause
