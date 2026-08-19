# -*- coding: utf-8 -*-
"""브랜드별 일일 자동 실행 러너 (작업 스케줄러용).

매일 08:00(월~금)에 Windows 작업 스케줄러가 이 스크립트를 호출한다.
브랜드를 하나씩 순차로 처리하고, 실패가 하나라도 있으면 이메일로 알린다.

GUI의 [예약 등록] 대신 이 러너를 쓰는 이유 (2026-08-19 확인):
1. GUI의 예약 등록은 브랜드와 무관하게 항상 같은 파일
   (upload_processor_schedule.json) 하나에 설정을 덮어쓴다. 브랜드를 2개
   이상 등록하면 모든 예약 작업이 '마지막에 등록한 브랜드'를 처리한다.
   → 여기서는 브랜드마다 upload_processor_schedule_<브랜드>.json 을 따로 쓴다.
2. 예약 실행 경로(scheduled_upload_processor)는 login_command를 그대로
   실행하는데, 로그인 봇(로그인.bat)은 "Enter를 누르세요"에서 멈추는 대화형
   스크립트다. 무인 실행에서는 반드시 실패하거나 멈춘다.
   → 여기서는 login_command를 비워서 로그인 봇을 실행하지 않는다.
      (네이버는 API로 전환되어 로그인이 필요 없고, 구글 등 브라우저 매체는
       기존에 저장된 Chrome 프로필 세션을 그대로 사용한다.)
3. 브랜드가 Chrome 자동화 프로필을 공유하므로 동시 실행하면 충돌한다.
   → 순차 실행한다.

사용법:
    python daily_auto_run.py                  # daily_auto_run.json 의 브랜드 실행
    python daily_auto_run.py --dry-run        # 실행 없이 설정만 점검/출력
    python daily_auto_run.py --brands "법무법인 태하"
    python daily_auto_run.py --no-alert       # 실패해도 메일 보내지 않음
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# 작업 스케줄러로 실행하면 stdout이 콘솔이 아니라서 cp949로 인코딩된다.
# 한글/기호 로그가 UnicodeEncodeError로 실행 전체를 죽이지 않도록 UTF-8로 고정한다.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

APP_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = APP_DIR.parent
DOWNLOADER_APP = PACKAGE_ROOT / "bots" / "report-downloader" / "ad_report_downloader"
RUNNER_CONFIG = APP_DIR / "daily_auto_run.json"
RUNNER_LOG = APP_DIR / "daily_auto_run.log"
BRAND_TIMEOUT_SEC = 5400          # 브랜드 1개당 최대 90분
MAX_LOG_BYTES = 5 * 1024 * 1024

sys.path.insert(0, str(APP_DIR))

from index_classifier.brand_settings import load_profiles          # noqa: E402
from index_classifier.schedule_rules import default_download_window  # noqa: E402


# ── 로깅 ─────────────────────────────────────────────────────────────────────
def log(message: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(line.encode(enc, "replace").decode(enc), flush=True)
    try:
        _rotate_log()
        with RUNNER_LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _rotate_log() -> None:
    if RUNNER_LOG.exists() and RUNNER_LOG.stat().st_size > MAX_LOG_BYTES:
        backup = RUNNER_LOG.with_suffix(".1.log")
        if backup.exists():
            backup.unlink()
        RUNNER_LOG.replace(backup)


# ── 브랜드 목록 ──────────────────────────────────────────────────────────────
def load_brand_list(explicit: str) -> tuple[list[str], bool]:
    """(브랜드 목록, 알림 사용 여부)."""
    if explicit:
        return [b.strip() for b in explicit.split(",") if b.strip()], True
    if RUNNER_CONFIG.exists():
        data = json.loads(RUNNER_CONFIG.read_text(encoding="utf-8-sig"))
        brands = [str(b).strip() for b in data.get("brands", []) if str(b).strip()]
        return brands, bool(data.get("alert_on_failure", True))
    # 설정 파일이 없으면 등록된 프로필 전체
    return sorted(load_profiles().keys()), True


# ── 브랜드별 예약 설정 파일 생성 ─────────────────────────────────────────────
def _slug(name: str) -> str:
    keep = [c if (c.isalnum() or c in "-_") else "_" for c in name.strip()]
    return "".join(keep)[:60] or "brand"


def write_schedule_config(brand: str, profile) -> Path:
    """브랜드 전용 스케줄 설정 파일을 만든다(GUI의 _write_schedule_config와 동일 형식).

    login_command는 의도적으로 비운다 — 위 docstring 2번 참고.
    """
    config = {
        "brand": brand,
        "download_folder": profile.download_folder,
        "rules_path": profile.rules_path,
        "upload_csv": "",           # scheduled_upload_processor가 날짜 기준으로 재계산
        "template_path": profile.template_path,
        "output_path": "",          # 위와 동일
        "output_root": profile.output_root,
        "login_command": "",        # 무인 실행 — 대화형 로그인 봇을 부르지 않는다
        "downloader_command": profile.downloader_command,
        "downloader_brand": profile.downloader_brand,
        "schedule_mode": "일반",     # 화~금 전일 / 월요일 금·토·일 3일치
        "start_time": "08:00",
        "custom_start": "",
        "custom_end": "",
    }
    path = APP_DIR / f"upload_processor_schedule_{_slug(brand)}.json"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def validate_profile(brand: str, profile) -> list[str]:
    problems: list[str] = []
    if profile is None:
        return [f"'{brand}' 브랜드 설정이 없습니다 (프로그램에서 브랜드를 먼저 등록하세요)"]
    if not profile.download_folder:
        problems.append("다운로드 폴더가 비어 있음")
    if not profile.rules_path or not Path(profile.rules_path).exists():
        problems.append(f"규칙 파일 없음: {profile.rules_path}")
    if profile.template_path and not Path(profile.template_path).exists():
        problems.append(f"템플릿 파일 없음: {profile.template_path}")
    if not profile.downloader_command:
        problems.append("다운로더 명령이 비어 있음")
    return problems


# ── 실행 ─────────────────────────────────────────────────────────────────────
def run_brand(brand: str, config_path: Path) -> tuple[bool, str]:
    """scheduled_upload_processor 를 별도 프로세스로 실행. (성공여부, 요약)."""
    script = APP_DIR / "scheduled_upload_processor.py"
    brand_log = config_path.with_suffix(".log")
    before = brand_log.stat().st_size if brand_log.exists() else 0

    started = time.monotonic()
    try:
        result = subprocess.run(
            [sys.executable, "-B", str(script), str(config_path)],
            cwd=str(APP_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=BRAND_TIMEOUT_SEC,
        )
        code = result.returncode
        stderr_tail = (result.stderr or "").strip().splitlines()[-5:]
    except subprocess.TimeoutExpired:
        elapsed = int(time.monotonic() - started)
        return False, f"{BRAND_TIMEOUT_SEC}초 제한 초과로 중단 ({elapsed}초 경과)"

    elapsed = int(time.monotonic() - started)
    new_lines = _tail_since(brand_log, before)
    if code == 0:
        summary = _pick(new_lines, ("[완료] 템플릿 반영", "[완료] 업로드 CSV 생성"))
        return True, f"{elapsed}초 · {summary}"

    detail = _pick(new_lines, ("[오류]",)) or " / ".join(stderr_tail) or f"종료 코드 {code}"
    return False, f"{elapsed}초 · {detail}"


def _tail_since(path: Path, offset: int, limit: int = 60) -> list[str]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            f.seek(offset)
            return f.read().splitlines()[-limit:]
    except Exception:
        return []


def _pick(lines: list[str], prefixes: tuple[str, ...]) -> str:
    for prefix in prefixes:
        hits = [ln.strip() for ln in lines if ln.strip().startswith(prefix)]
        if hits:
            return hits[-1]
    return lines[-1].strip() if lines else ""


# ── 알림 ─────────────────────────────────────────────────────────────────────
def send_alert(subject: str, body: str) -> None:
    """예산 감시에서 쓰는 이메일 설정을 그대로 재사용해 발송한다."""
    try:
        if str(DOWNLOADER_APP) not in sys.path:
            sys.path.insert(0, str(DOWNLOADER_APP))
        from budget import settings as budget_settings   # type: ignore
        from budget import notifier as budget_notifier   # type: ignore

        cfg = budget_settings.load(create_if_missing=False)
        results = budget_notifier.notify_all(
            cfg, subject=subject, body=body, short_text=subject, log=None
        )
        if not results:
            log("[알림] 설정된 알림 채널이 없습니다 (예산알림_설정.bat에서 이메일을 켜세요)")
            return
        for r in results:
            ok = getattr(r, "ok", None)
            detail = getattr(r, "detail", "") or getattr(r, "message", "")
            log(f"[알림] {getattr(r, 'channel', '?')}: {'성공' if ok else '실패'} {detail}")
    except Exception as exc:
        log(f"[알림] 발송 실패: {type(exc).__name__}: {exc}")


# ── main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description="브랜드별 일일 자동 실행")
    parser.add_argument("--brands", default="", help="쉼표로 구분한 브랜드명 (생략 시 daily_auto_run.json)")
    parser.add_argument("--dry-run", action="store_true", help="실행하지 않고 설정만 점검")
    parser.add_argument("--no-alert", action="store_true", help="실패해도 알림을 보내지 않음")
    args = parser.parse_args()

    brands, alert_enabled = load_brand_list(args.brands)
    if args.no_alert:
        alert_enabled = False

    window = default_download_window()
    log("=" * 60)
    log(f"[시작] 일일 자동 실행 — 대상 {len(brands)}개: {', '.join(brands) or '(없음)'}")
    log(f"  수집 기간: {window.start_yyyymmdd} ~ {window.end_yyyymmdd} ({window.reason})")
    if args.dry_run:
        log("  ** 점검 모드 — 실제 실행하지 않습니다 **")

    if not brands:
        log("[오류] 실행할 브랜드가 없습니다. daily_auto_run.json을 확인하세요.")
        return 1

    profiles = load_profiles()
    results: list[tuple[str, bool, str]] = []

    for brand in brands:
        profile = profiles.get(brand)
        problems = validate_profile(brand, profile)
        if problems:
            for p in problems:
                log(f"[{brand}] 설정 문제: {p}")
            results.append((brand, False, "; ".join(problems)))
            continue

        config_path = write_schedule_config(brand, profile)
        log(f"[{brand}] 설정 파일: {config_path.name}")
        if args.dry_run:
            log(f"[{brand}] 템플릿: {profile.template_path or '(없음 — 스프레드시트 전용)'}")
            log(f"[{brand}] 다운로더: {profile.downloader_command}")
            log(f"[{brand}] 다운로더 브랜드: {profile.downloader_brand or '(자동 별칭)'}")
            results.append((brand, True, "점검 통과"))
            continue

        log(f"[{brand}] 실행 시작")
        ok, summary = run_brand(brand, config_path)
        log(f"[{brand}] {'완료' if ok else '실패'}: {summary}")
        results.append((brand, ok, summary))

    failures = [(b, s) for b, ok, s in results if not ok]
    log(f"[종료] 성공 {len(results) - len(failures)} / 실패 {len(failures)}")

    if failures and alert_enabled and not args.dry_run:
        subject = f"[키워드 소진] 자동 실행 실패 {len(failures)}건 ({datetime.now():%m-%d %H:%M})"
        lines = [
            f"수집 기간: {window.start_yyyymmdd} ~ {window.end_yyyymmdd}",
            "",
            "실패한 브랜드:",
        ]
        lines += [f"  - {b}: {s}" for b, s in failures]
        ok_list = [b for b, ok, _ in results if ok]
        if ok_list:
            lines += ["", "정상 처리된 브랜드: " + ", ".join(ok_list)]
        lines += ["", f"자세한 로그: {RUNNER_LOG}"]
        send_alert(subject, "\n".join(lines))

    return 0 if not failures else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # 러너 자체가 죽어도 알림은 남긴다
        log(f"[치명] 러너 예외: {type(exc).__name__}: {exc}")
        try:
            send_alert(
                f"[키워드 소진] 자동 실행 중단 ({datetime.now():%m-%d %H:%M})",
                f"러너가 예외로 중단되었습니다.\n\n{type(exc).__name__}: {exc}\n\n로그: {RUNNER_LOG}",
            )
        finally:
            raise
