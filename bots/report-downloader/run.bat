@echo off
chcp 65001 > nul
set "PACKAGE_ROOT=%~dp0..\.."
set "PYTHON_EXE=%PACKAGE_ROOT%\python\python.exe"
set "PLAYWRIGHT_BROWSERS_PATH=%PACKAGE_ROOT%\ms-playwright"
set "DOWNLOAD_ROOT=%PACKAGE_ROOT%\downloads"
if not exist "%PYTHON_EXE%" (
  echo [ERROR] bundled python was not found: %PYTHON_EXE%
  pause
  exit /b 1
)
"%PYTHON_EXE%" -B -c "import json, pathlib, os; p=pathlib.Path(r'%~dp0ad_report_downloader\config.json'); d=json.loads(p.read_text(encoding='utf-8-sig')); d['save_root_path']=os.path.abspath(r'%DOWNLOAD_ROOT%'); tmp=p.with_name(p.name+'.tmp'); tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8'); os.replace(tmp, p)"
cd /d "%~dp0ad_report_downloader"
if errorlevel 1 (
  echo [ERROR] ad_report_downloader folder was not found.
  pause
  exit /b 1
)
REM cli.py runs headless (no Qt window), reading active_brand/last_run_period
REM from config.json so that automated runs do not require a manual click.
REM To use the interactive Qt picker window instead, run "python main.py" here.
REM Output is also saved to run_downloader.log so it can be checked even if
REM this console window closes before you can read it.
"%PYTHON_EXE%" -B cli.py > "run_downloader.log" 2>&1
set "DL_EXIT=%ERRORLEVEL%"
type "run_downloader.log"
if not "%DL_EXIT%"=="0" (
  echo.
  echo [ERROR] downloader failed with exit code %DL_EXIT%. See run_downloader.log
  pause
)
