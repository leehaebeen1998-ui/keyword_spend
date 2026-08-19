# -*- coding: utf-8 -*-
"""이식 설정 적용 — 새 PC에서 프로그램을 쓸 수 있게 만드는 2단계.

portable_export.py가 모아 둔 `portable_settings\\`를 읽어, 예전 PC 기준으로
저장돼 있던 절대 경로를 **이 PC의 설치 위치로 바꿔서** 복원한다.

  - 양식 파일 → <설치폴더>\\templates\\ 로 복사하고 브랜드 설정이 그곳을 보게 함
  - 예전 프로그램 경로(C:\\Temp\\ks 등) → 지금 설치 경로로 치환
    (로그인/다운로더 명령, 다운로드 폴더, 규칙 파일 경로)
  - 결과 저장 폴더(output_root)는 이 PC의 임시 폴더 기준으로 재계산
  - brand_profiles.json 을 %LOCALAPPDATA%\\BrandUploadProcessor 에 기록
  - daily_auto_run.json 등 부가 설정 복원

사용법:
    python portable_import.py               # 적용
    python portable_import.py --dry-run     # 무엇이 바뀌는지만 출력
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

APP_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = APP_DIR.parent
IMPORT_DIR = PACKAGE_ROOT / "portable_settings"
TEMPLATE_DEST = PACKAGE_ROOT / "templates"

sys.path.insert(0, str(APP_DIR))
from index_classifier.brand_settings import BRAND_PROFILES_PATH  # noqa: E402


def log(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(msg.encode(enc, "replace").decode(enc), flush=True)


def rewrite_path(value: str, old_root: str, new_root: str) -> str:
    """예전 설치 경로로 시작하는 값을 새 설치 경로로 바꾼다 (대소문자 무시)."""
    text = str(value or "").strip()
    if not text or not old_root:
        return text
    old = old_root.rstrip("\\/")
    if text.lower().startswith(old.lower()):
        return new_root.rstrip("\\/") + text[len(old):]
    return text


def default_output_root() -> str:
    return str(Path(tempfile.gettempdir()) / "BrandUploadProcessor" / "outputs")


def main() -> int:
    parser = argparse.ArgumentParser(description="이식 설정 적용")
    parser.add_argument("--dry-run", action="store_true", help="적용하지 않고 변경 내용만 출력")
    args = parser.parse_args()

    log("=" * 60)
    log("이식 설정 적용")
    log(f"  설치 위치: {PACKAGE_ROOT}")
    log("=" * 60)

    manifest_path = IMPORT_DIR / "manifest.json"
    profiles_path = IMPORT_DIR / "brand_profiles.json"
    if not manifest_path.exists() or not profiles_path.exists():
        log(f"[오류] 이식 설정이 없습니다: {IMPORT_DIR}")
        log("       예전 PC에서 이식패키지_만들기.bat 을 먼저 실행해 번들을 만들어야 합니다.")
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    old_root = str(manifest.get("source_root") or "")
    new_root = str(PACKAGE_ROOT)
    # 설치 폴더 밖(사용자 폴더)을 가리키던 경로도 이 PC 기준으로 옮긴다.
    # 예전 PC와 윈도우 계정 이름이 다르면 %LOCALAPPDATA%/%USERPROFILE% 경로가
    # 통째로 어긋나기 때문이다.
    root_map: list[tuple[str, str]] = [(old_root, new_root)]
    for key, env in (("source_localappdata", "LOCALAPPDATA"),
                     ("source_user_profile", "USERPROFILE")):
        old_value = str(manifest.get(key) or "")
        new_value = os.environ.get(env, "")
        if old_value and new_value and old_value.lower() != new_value.lower():
            root_map.append((old_value, new_value))
    log(f"예전 설치 위치: {old_root}")
    log(f"만든 시각     : {manifest.get('created_at')}")
    log("")

    data = json.loads(profiles_path.read_text(encoding="utf-8-sig"))
    brands = data.get("brands", [])
    template_by_brand = {t["brand"]: t["stored"] for t in manifest.get("templates", [])}
    rules_by_brand = {r["brand"]: r["stored"] for r in manifest.get("rules", [])}

    changes: list[str] = []
    for brand in brands:
        name = str(brand.get("name") or "")

        # 1) 양식 파일 → <설치폴더>\templates\
        stored = template_by_brand.get(name)
        if stored:
            new_template = TEMPLATE_DEST / stored
            if str(brand.get("template_path") or "") != str(new_template):
                changes.append(f"[{name}] 양식: {brand.get('template_path')} → {new_template}")
                brand["template_path"] = str(new_template)
        elif str(brand.get("template_path") or "").strip():
            changes.append(f"[{name}] ! 양식 파일이 패키지에 없습니다 — 새 PC에서 직접 지정 필요")

        # 2) 번들 밖 규칙 파일 → 설치폴더 안으로
        stored_rule = rules_by_brand.get(name)
        if stored_rule:
            new_rule = APP_DIR / "examples" / stored_rule
            changes.append(f"[{name}] 규칙: {brand.get('rules_path')} → {new_rule}")
            brand["rules_path"] = str(new_rule)

        # 3) 예전 설치 경로로 시작하는 값들 치환
        for key in ("rules_path", "download_folder", "login_command",
                    "downloader_command", "upload_csv", "output_root",
                    "spreadsheet_credentials_path"):
            before = str(brand.get(key) or "")
            after = before
            for src_root, dst_root in root_map:
                moved = rewrite_path(after, src_root, dst_root)
                if moved != after:
                    after = moved
                    break
            if before != after:
                changes.append(f"[{name}] {key}: {before} → {after}")
                brand[key] = after

        # 4) 그래도 남은 결과 저장 폴더는 이 PC의 임시 폴더 기준으로
        before_root = str(brand.get("output_root") or "")
        if before_root and not Path(before_root).parent.exists():
            after_root = default_output_root()
            changes.append(f"[{name}] output_root: {before_root} → {after_root}")
            brand["output_root"] = after_root

        # 5) 지난 실행 산출물 경로는 의미가 없으므로 비운다
        if brand.get("upload_csv"):
            brand["upload_csv"] = ""

    log(f"변경 사항 {len(changes)}건")
    for c in changes:
        log(f"   {c}")

    if args.dry_run:
        log("\n(--dry-run 모드 — 실제로 적용하지 않았습니다)")
        return 0

    # ── 적용 ────────────────────────────────────────────────────────────────
    TEMPLATE_DEST.mkdir(parents=True, exist_ok=True)
    for item in manifest.get("templates", []):
        src = IMPORT_DIR / "templates" / item["stored"]
        if src.exists():
            shutil.copy2(src, TEMPLATE_DEST / item["stored"])
    for item in manifest.get("rules", []):
        src = IMPORT_DIR / item["stored"]
        if src.exists():
            (APP_DIR / "examples").mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, APP_DIR / "examples" / item["stored"])

    BRAND_PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    if BRAND_PROFILES_PATH.exists():
        backup = BRAND_PROFILES_PATH.with_name("brand_profiles.backup.json")
        shutil.copy2(BRAND_PROFILES_PATH, backup)
        log(f"\n기존 설정 백업: {backup}")
    tmp = BRAND_PROFILES_PATH.with_name(BRAND_PROFILES_PATH.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, BRAND_PROFILES_PATH)
    log(f"브랜드 설정 저장: {BRAND_PROFILES_PATH}")

    src_daily = IMPORT_DIR / "daily_auto_run.json"
    if src_daily.exists():
        shutil.copy2(src_daily, APP_DIR / "daily_auto_run.json")
        log(f"자동 실행 대상 복원: {APP_DIR / 'daily_auto_run.json'}")

    # ── 점검 ────────────────────────────────────────────────────────────────
    log("")
    log("=" * 60)
    log("점검")
    todo: list[str] = []

    cfg_path = (PACKAGE_ROOT / "bots" / "report-downloader"
                / "ad_report_downloader" / "config.json")
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
        api = cfg.get("naver_api", {})
        has_key = bool(api.get("api_key")) and bool(api.get("secret_key"))
        log(f"  네이버 API 키: {'있음' if has_key else '없음'}")
        if not has_key:
            todo.append("config.json 의 naver_api.api_key / secret_key 입력 "
                        "(광고시스템 > 도구 > API 사용 관리)")
        total = missing_cid = 0
        for b in cfg.get("brands", []):
            for a in (b.get("media") or {}).get("naver", {}).get("accounts", []):
                total += 1
                if not a.get("customer_id"):
                    missing_cid += 1
        log(f"  네이버 계정 매핑: {total - missing_cid}/{total} customer_id 있음")
        if missing_cid:
            todo.append(f"customer_id 없는 네이버 계정 {missing_cid}개 확인")
    else:
        log("  ! 다운로더 config.json 이 없습니다")
        todo.append("bots\\report-downloader 폴더가 제대로 풀렸는지 확인")

    py = PACKAGE_ROOT / "python" / "python.exe"
    log(f"  번들 파이썬: {'있음' if py.exists() else '없음'}")
    if not py.exists():
        todo.append("번들 파이썬이 없습니다 — 전체 배포 zip으로 다시 설치하세요")

    for brand in brands:
        tp = str(brand.get("template_path") or "")
        if tp and not Path(tp).exists():
            todo.append(f"'{brand.get('name')}' 양식 파일을 프로그램에서 다시 지정")

    todo += [
        "로그인.bat 실행 — 구글 등 브라우저 매체 로그인 (네이버는 API라 불필요)",
        "예산알림_설정.bat 실행 — 메일 비밀번호는 PC마다 다시 저장해야 함 (DPAPI)",
        "일일자동실행_등록.bat 실행 — 08시 자동 실행 예약 (쓸 경우)",
    ]

    log("")
    log("남은 작업")
    for i, t in enumerate(todo, 1):
        log(f"  {i}. {t}")
    log("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
