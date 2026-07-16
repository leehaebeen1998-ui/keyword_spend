"""
ad_report_downloader/cli.py — Qt 없이 다운로드 실행 후 manifest.json 출력.

인덱스+통합 봇(integrated_runner.py)에서 subprocess로 호출된다.
로그인 방식·기존 다운로더 로직은 변경 없음.

사용법:
  python cli.py --brand "법무법인 태하" --start 20260601 --end 20260615 --media naver,google_sa,kakao
  python cli.py --brand "법무법인 태하" --start 20260601 --end 20260615   # 브랜드 전체 매체
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

# stdout/stderr를 UTF-8로 강제 전환한다.
#
# 콘솔에 직접 출력할 때는 (chcp 65001 덕분에) 문제 없지만, run.bat이 출력을
# 로그 파일로 리다이렉트하거나(`> run_downloader.log`) 파이프로 캡처하면
# 파이썬은 콘솔이 아니라고 판단해 시스템 기본 코드페이지(한글 Windows는
# cp949)로 stdout을 인코딩한다. log() 안의 "⚠"/"✅"/"❌" 같은 기호는
# cp949로 표현이 안 되어 UnicodeEncodeError로 전체 다운로드가 중단됐었다.
# reconfigure로 스트림 자체를 UTF-8로 못 박아 두면 콘솔이든 파일이든
# 항상 안전하게 출력된다.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 패키지 루트를 sys.path에 추가 (cli.py가 ad_report_downloader/ 안에 있을 때)
_PKG_DIR = Path(__file__).parent
if str(_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR))

# ── 매체 코드 → 표준명 (orchestrator와 동일) ────────────────────────────────
_MEDIA_CODE_TO_NAME: dict[str, str] = {
    "naver":            "Naver",
    "google_sa":        "Google SA",
    "google_da":        "Google DA",
    "meta":             "Meta",
    "kakao":            "Kakao SA",
    "adn":              "ADN",
    "mobion_banner":    "Mobion",
    "mobion_daily":     "Mobion",
    "x":                "X",
    "google_analytics": "GA4",
    "gfa":              "GFA DB",
}

_MEDIA_ORDER = [
    "naver", "google_sa", "google_da", "meta", "kakao",
    "adn", "mobion_banner", "mobion_daily", "x", "google_analytics", "gfa",
]


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def log(media: str, message: str) -> None:
    """stdout으로 로그 출력 — subprocess 호출 측에서 실시간 캡처 가능.

    reconfigure(위)가 어떤 이유로든 안 먹힌 환경을 대비해, 인코딩 실패 시
    이모지/특수기호만 물음표로 바꿔서라도 로그 자체가 끊기지 않게 한다.
    (로그 한 줄 못 찍는다고 다운로드 전체가 죽는 것보다는 훨씬 낫다.)
    """
    line = f"[{_ts()}] [{media}] {message}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        print(line.encode(encoding, errors="replace").decode(encoding), flush=True)


def _get_accounts(media_cfg: dict) -> list[dict]:
    accounts = media_cfg.get("accounts")
    if accounts:
        return list(accounts)
    return [{
        "account_id":   media_cfg.get("account_id", "").strip(),
        "account_name": "",
        "report_name":  media_cfg.get("report_name", ""),
    }]


def _find_chrome_exe() -> str:
    import os
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    raise RuntimeError("Chrome 실행 파일을 찾을 수 없습니다. Google Chrome이 설치되어 있는지 확인하세요.")


# ── CliRunner ────────────────────────────────────────────────────────────────
class CliRunner:
    """Qt 없이 순차적으로 다운로드를 실행한다."""

    def __init__(
        self,
        config: dict,
        start_date: date,
        end_date: date,
        enabled_media: list[str],
    ):
        self.config = config
        self.start_date = start_date
        self.end_date = end_date
        self.enabled_media = enabled_media
        self.download_results: list[dict] = []

    def run(self) -> list[dict]:
        # 매체 순서 정렬
        ordered = [m for m in _MEDIA_ORDER if m in self.enabled_media]

        # (매체, 계정) 쌍 빌드
        units: list[tuple[str, dict]] = []
        for media_code in ordered:
            media_cfg = self.config.get("media", {}).get(media_code, {})
            for acct in _get_accounts(media_cfg):
                units.append((media_code, acct))

        log("SYSTEM", f"총 {len(ordered)}개 매체 / {len(units)}개 계정 실행 시작")

        # 기존 다운로더 팩토리 재사용
        from core.orchestrator import _build_downloader
        from core.chrome_profile import resolve_chrome_profile
        from playwright.sync_api import sync_playwright

        profile = resolve_chrome_profile(self.config)
        profile.user_data_dir.mkdir(parents=True, exist_ok=True)

        chrome_exe = _find_chrome_exe()
        log("SYSTEM", f"Chrome: {chrome_exe}")
        log("SYSTEM", f"프로필: {profile.label}")
        log("SYSTEM", "⚠ Chrome이 실행 중이면 먼저 닫아주세요")

        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(
                user_data_dir=str(profile.user_data_dir),
                executable_path=chrome_exe,
                headless=False,
                ignore_default_args=["--disable-extensions", "--use-mock-keychain"],
                args=[
                    *profile.launch_args(),
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-session-crashed-bubble",
                    "--disable-background-mode",
                    "--disable-blink-features=AutomationControlled",
                ],
                viewport={"width": 1280, "height": 900},
                slow_mo=100,
            )
            log("SYSTEM", "Chrome 실행 완료")
            try:
                login_blocked: set[str] = set()
                for media_code, account in units:
                    if media_code in login_blocked:
                        acct_label = account.get("account_name") or account.get("account_id") or "기본"
                        log(media_code, f"건너뜀 [{acct_label}] (로그인 필요)")
                        continue
                    self._run_one(context, media_code, account, _build_downloader, login_blocked)
            finally:
                try:
                    context.close()
                except Exception:
                    pass

        log("SYSTEM", f"다운로드 완료 — 성공 {len(self.download_results)}건")
        return self.download_results

    def _run_one(
        self, context, media_code: str, account: dict, build_fn, login_blocked: set
    ) -> None:
        acct_label = account.get("account_name") or account.get("account_id") or "기본"
        log(media_code, f"─── 시작 [{acct_label}] ───")

        downloader = build_fn(media_code, self.config, account, use_mock=False)
        result = downloader.run(context, self.start_date, self.end_date)

        if result.login_required:
            log(media_code, f"⚠ 로그인 필요 [{acct_label}] — 이후 같은 매체 건너뜀")
            login_blocked.add(media_code)
            return

        if result.skipped:
            log(media_code, f"건너뜀 [{acct_label}]: {result.skip_reason or ''}")
            return

        if result.success and result.dest_path:
            log(media_code, f"✅ 완료 [{acct_label}]: {result.dest_path}")
            self.download_results.append({
                "media":        _MEDIA_CODE_TO_NAME.get(media_code, media_code),
                "account_name": account.get("account_name", ""),
                "account_id":   account.get("account_id", ""),
                "file_path":    str(result.dest_path),
                "start_date":   self.start_date.strftime("%Y%m%d"),
                "end_date":     self.end_date.strftime("%Y%m%d"),
            })
        else:
            log(media_code, f"❌ 실패 [{acct_label}]: {result.error or '알 수 없는 오류'}")


# ── manifest 저장 ─────────────────────────────────────────────────────────────
def write_manifest(
    download_results: list[dict],
    brand: str,
    start_date: date,
    end_date: date,
    out_dir: str,
) -> str:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    manifest = {
        "brand":      brand,
        "period": {
            "start": start_date.strftime("%Y%m%d"),
            "end":   end_date.strftime("%Y%m%d"),
        },
        "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "files":      download_results,
    }
    manifest_file = out_path / "manifest.json"
    manifest_file.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log("SYSTEM", f"[manifest] ✅ 저장: {manifest_file}")
    return str(manifest_file)


# ── 인수 파싱 ─────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="report-downloader CLI (Qt 없이 실행)")
    p.add_argument("--brand",        default="",    help="브랜드 이름 (config의 brands[].name). 생략 시 config.json의 active_brand 사용")
    p.add_argument("--start",        default="",    help="시작일 YYYYMMDD. 생략 시 config.json의 last_run_period.start 사용")
    p.add_argument("--end",          default="",    help="종료일 YYYYMMDD. 생략 시 config.json의 last_run_period.end 사용")
    p.add_argument("--media",        default="",    help="매체 코드 쉼표 구분 (생략 시 전체)")
    p.add_argument("--config",       default="",    help="config.json 경로 (생략 시 자동)")
    p.add_argument("--manifest-out", default="",    help="manifest.json 저장 폴더")
    return p.parse_args()


def _resolve_brand_and_period(args: argparse.Namespace, base_config: dict) -> tuple[str, str, str]:
    """--brand/--start/--end가 생략되면 config.json에 GUI(upload_processor_gui.py)의
    `_prepare_bundled_downloader`가 미리 써 둔 active_brand/last_run_period로 채운다.

    자동화(전체 실행/예약 실행) 흐름에서는 run.bat이 인자 없이 그대로 호출되므로,
    이 fallback이 없으면 브랜드/기간을 알 수 없어 다운로드가 진행되지 않는다.
    """
    brand = str(args.brand or "").strip()
    if not brand:
        brand = str(base_config.get("active_brand") or base_config.get("brand_name") or "").strip()

    start = str(args.start or "").strip()
    end = str(args.end or "").strip()
    if not start or not end:
        period = base_config.get("last_run_period") or {}
        start = start or str(period.get("start", "")).replace("-", "")
        end = end or str(period.get("end", "")).replace("-", "")

    return brand, start, end


# 접미사 없는 짧은 브랜드명이 들어오면, "- 데일리"가 붙은 자동화용 항목이
# 실제로 존재할 때 그쪽을 우선한다.
_DAILY_BRAND_ALIASES: dict[str, str] = {
    "법무법인 오현": "법무법인 오현 - 데일리",
    "법무법인 태하": "법무법인 태하 - 데일리",
    "법무법인 일로": "법무법인 일로 - 데일리",
}


def _resolve_daily_brand_alias(brand: str, base_config: dict) -> str:
    """다운로더 봇 자체에서도 별칭(alias) 매칭을 한 번 더 적용한다.

    2026-07-13: 상위 프로그램(키워드 소진내역 가공 앱)의 `_downloader_brand_name`이
    정확 일치를 별칭 확인보다 먼저 검사하는 바람에, "법무법인 태하"라는 짧은 이름이
    config.json에 남아있는 옛 수동/주간 브랜드 항목으로 잘못 연결되어 일간 키워드
    보고서 대신 옛 주간/DA 보고서를 받아온 버그가 있었다. 그 문제는 상위 프로그램
    쪽에서 이미 고쳤지만(alias를 정확 일치보다 먼저 검사), 이 다운로더 봇을
    (--brand 인자로 직접 호출하거나 다른 자동화 스크립트가 붙는 등) 상위 프로그램을
    거치지 않고 호출하는 경로가 생겨도 같은 문제가 재발하지 않도록, 다운로더 봇
    자체에도 동일한 별칭 우선 규칙을 독립적으로 한 번 더 적용해 이중으로 방어한다.

    브랜드 목록에 "- 데일리" 항목이 실제로 있을 때만 리다이렉트하고, 없으면
    입력값을 그대로 돌려준다(예: 요청 브랜드가 원래부터 옛 주간 항목만 쓰는
    경우까지 강제로 바꾸지 않기 위함).
    """
    names = {
        str(item.get("name") or "").strip()
        for item in base_config.get("brands", [])
        if isinstance(item, dict)
    }
    alias = _DAILY_BRAND_ALIASES.get(brand)
    if alias and alias in names and alias != brand:
        log("SYSTEM", f"[별칭 매칭] 브랜드 '{brand}' -> '{alias}' (일간 자동화용 항목 우선)")
        return alias
    return brand


# ── main ─────────────────────────────────────────────────────────────────────
def main() -> None:
    args = parse_args()

    # config.json 로드
    cfg_path = Path(args.config) if args.config else _PKG_DIR / "config.json"
    with open(cfg_path, encoding="utf-8-sig") as f:
        base_config = json.load(f)

    # --brand/--start/--end 생략 시 config.json의 active_brand/last_run_period로 채움
    brand, start_str, end_str = _resolve_brand_and_period(args, base_config)
    if not brand:
        log("ERROR", "브랜드를 확인할 수 없습니다. --brand를 지정하거나 config.json의 active_brand를 설정하세요.")
        sys.exit(1)
    if not start_str or not end_str:
        log("ERROR", "기간을 확인할 수 없습니다. --start/--end를 지정하거나 config.json의 last_run_period를 설정하세요.")
        sys.exit(1)

    # 다운로더 봇 자체에서도 별칭(alias) 매칭을 한 번 더 적용 (이중 방어, 위 docstring 참고)
    brand = _resolve_daily_brand_alias(brand, base_config)

    # 브랜드 찾기
    brand_entry = next(
        (b for b in base_config.get("brands", []) if b.get("name") == brand),
        None,
    )
    if brand_entry is None:
        available = [b.get("name") for b in base_config.get("brands", [])]
        log("ERROR", f"브랜드를 찾을 수 없습니다: '{brand}'")
        log("ERROR", f"사용 가능: {available}")
        sys.exit(1)

    # 브랜드 config 구성 (기본 설정 + 브랜드별 media)
    config = dict(base_config)
    config["brand_name"] = brand
    brand_media = brand_entry.get("media")
    if brand_media:
        config["media"] = brand_media
    # brand_media가 없으면 top-level media 그대로 사용 (active_brand 일치 시)

    # 날짜 파싱
    try:
        start_date = datetime.strptime(start_str, "%Y%m%d").date()
        end_date   = datetime.strptime(end_str,   "%Y%m%d").date()
    except ValueError as e:
        log("ERROR", f"날짜 형식 오류 (YYYYMMDD 필요): {e}")
        sys.exit(1)

    # 매체 목록
    if args.media:
        enabled_media = [m.strip() for m in args.media.split(",") if m.strip()]
    else:
        enabled_media = [
            k for k, v in config.get("media", {}).items()
            if isinstance(v, dict) and v.get("enabled", True)
        ]

    log("SYSTEM", f"브랜드: {brand}")
    log("SYSTEM", f"기간: {start_str} ~ {end_str}")
    log("SYSTEM", f"매체: {', '.join(enabled_media)}")

    # 다운로드 실행
    runner = CliRunner(
        config=config,
        start_date=start_date,
        end_date=end_date,
        enabled_media=enabled_media,
    )
    download_results = runner.run()

    # manifest 저장
    manifest_dir = (
        args.manifest_out
        or config.get("manifest_output_dir", "")
        or config.get("save_root_path", ".")
    )
    if download_results:
        write_manifest(download_results, brand, start_date, end_date, manifest_dir)
    else:
        log("SYSTEM", "다운로드 결과 없음 — manifest 미생성")

    log("SYSTEM", "=== CLI 완료 ===")


if __name__ == "__main__":
    main()
