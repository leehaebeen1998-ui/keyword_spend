# -*- coding: utf-8 -*-
"""이식용 설정 내보내기 — 다른 PC로 프로그램을 통째로 옮기기 위한 1단계.

배포 번들(배포번들_만들기.bat)은 프로그램·파이썬·봇만 담고, 아래 것들은
번들 바깥(사용자 폴더)에 있어서 빠진다. 그대로 새 PC에서 풀면 브랜드가
하나도 없는 빈 프로그램이 된다.

  - %LOCALAPPDATA%\\BrandUploadProcessor\\brand_profiles.json (브랜드 설정)
  - 각 브랜드의 엑셀 양식 파일 (보통 다운로드/임시 폴더)
  - app\\daily_auto_run.json (08시 자동 실행 대상)
  - 업로드 규칙 CSV (번들 안이면 그대로, 밖이면 따로 챙겨야 함)

이 스크립트는 그것들을 번들 루트의 `portable_settings\\` 폴더로 모으고,
원래 경로를 manifest.json에 기록한다. 그 뒤 배포 번들을 만들면 설정까지
한 zip에 들어가고, 새 PC에서는 portable_import.py가 경로를 새 설치 위치로
바꿔서 복원한다.

사용법:
    python portable_export.py            # 수집만
    python portable_export.py --list     # 무엇이 수집될지만 출력
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

APP_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = APP_DIR.parent
EXPORT_DIR = PACKAGE_ROOT / "portable_settings"
TEMPLATE_DIR = EXPORT_DIR / "templates"

sys.path.insert(0, str(APP_DIR))
from index_classifier.brand_settings import BRAND_PROFILES_PATH  # noqa: E402


def log(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(msg.encode(enc, "replace").decode(enc), flush=True)


def _safe_file_name(path: Path) -> str:
    keep = [c if (c.isalnum() or c in " .-_()[]") else "_" for c in path.name]
    return "".join(keep) or "template"


def main() -> int:
    parser = argparse.ArgumentParser(description="이식용 설정 내보내기")
    parser.add_argument("--list", action="store_true", help="수집 대상만 출력하고 끝냄")
    parser.add_argument("--build-bundle", action="store_true",
                        help="수집 후 배포번들_만들기.bat 까지 이어서 실행")
    args = parser.parse_args()

    log("=" * 60)
    log("이식용 설정 수집")
    log(f"  프로그램 루트: {PACKAGE_ROOT}")
    log(f"  저장 위치    : {EXPORT_DIR}")
    log("=" * 60)

    if not BRAND_PROFILES_PATH.exists():
        log(f"[오류] 브랜드 설정 파일이 없습니다: {BRAND_PROFILES_PATH}")
        log("       프로그램(run.bat)에서 브랜드를 한 번 저장한 뒤 다시 실행하세요.")
        return 1

    profiles_raw = json.loads(BRAND_PROFILES_PATH.read_text(encoding="utf-8-sig"))
    brands = profiles_raw.get("brands", [])
    log(f"브랜드 {len(brands)}개: {', '.join(b.get('name', '?') for b in brands)}")

    # 양식 파일 수집 계획
    template_plan: list[tuple[str, Path, str]] = []   # (브랜드, 원본, 저장이름)
    missing: list[str] = []
    used_names: set[str] = set()
    for brand in brands:
        raw = str(brand.get("template_path") or "").strip()
        if not raw:
            continue
        src = Path(raw)
        if not src.exists():
            missing.append(f"{brand.get('name')}: {raw}")
            continue
        stored = _safe_file_name(src)
        base, ext = os.path.splitext(stored)
        n = 2
        while stored in used_names:
            stored = f"{base}_{n}{ext}"
            n += 1
        used_names.add(stored)
        template_plan.append((str(brand.get("name")), src, stored))

    extra_plan: list[tuple[str, Path]] = []
    for label, path in (
        ("daily_auto_run.json", APP_DIR / "daily_auto_run.json"),
        ("budget_config.json", PACKAGE_ROOT / "bots" / "report-downloader"
                               / "ad_report_downloader" / "budget_config.json"),
    ):
        if path.exists():
            extra_plan.append((label, path))

    # 번들 밖에 있는 규칙 CSV
    rules_plan: list[tuple[str, Path, str]] = []
    for brand in brands:
        raw = str(brand.get("rules_path") or "").strip()
        if not raw:
            continue
        src = Path(raw)
        try:
            src.relative_to(PACKAGE_ROOT)
            continue          # 번들 안 → 번들에 이미 포함됨
        except ValueError:
            pass
        if src.exists():
            stored = _safe_file_name(src)
            rules_plan.append((str(brand.get("name")), src, stored))

    log("")
    log(f"양식 파일 {len(template_plan)}개")
    for name, src, stored in template_plan:
        size = src.stat().st_size / 1024 / 1024
        log(f"   - [{name}] {src.name} ({size:.1f} MB)")
    for m in missing:
        log(f"   ! 양식 파일 없음 — {m}")
    if rules_plan:
        log(f"규칙 파일(번들 밖) {len(rules_plan)}개")
        for name, src, _ in rules_plan:
            log(f"   - [{name}] {src}")
    log(f"추가 설정 {len(extra_plan)}개: {', '.join(l for l, _ in extra_plan)}")

    if args.list:
        log("\n(--list 모드 — 실제 복사하지 않았습니다)")
        return 0

    # 수집 실행
    if EXPORT_DIR.exists():
        shutil.rmtree(EXPORT_DIR)
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)

    shutil.copy2(BRAND_PROFILES_PATH, EXPORT_DIR / "brand_profiles.json")
    for _, src, stored in template_plan:
        shutil.copy2(src, TEMPLATE_DIR / stored)
    for _, src, stored in rules_plan:
        shutil.copy2(src, EXPORT_DIR / stored)
    for label, src in extra_plan:
        shutil.copy2(src, EXPORT_DIR / label)

    manifest = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_root": str(PACKAGE_ROOT),
        "source_user_profile": os.environ.get("USERPROFILE", ""),
        "source_localappdata": os.environ.get("LOCALAPPDATA", ""),
        "templates": [
            {"brand": name, "original": str(src), "stored": stored}
            for name, src, stored in template_plan
        ],
        "rules": [
            {"brand": name, "original": str(src), "stored": stored}
            for name, src, stored in rules_plan
        ],
        "extras": [label for label, _ in extra_plan],
        "missing_templates": missing,
    }
    (EXPORT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    total = sum(f.stat().st_size for f in EXPORT_DIR.rglob("*") if f.is_file())
    log("")
    log(f"[완료] {EXPORT_DIR} ({total/1024/1024:.1f} MB)")
    if missing:
        log("주의: 위에 '양식 파일 없음'으로 표시된 브랜드는 새 PC에서 양식을 다시 지정해야 합니다.")

    builder = PACKAGE_ROOT / "배포번들_만들기.bat"
    if not args.build_bundle:
        log("")
        log("다음 단계: 배포번들_만들기.bat 을 실행하면 이 설정까지 한 zip에 담깁니다.")
        return 0

    if not builder.exists():
        log(f"\n[오류] 번들 빌더를 찾을 수 없습니다: {builder}")
        return 1

    # 배치 파일명이 한글이라 .bat 안에서 부르면 cmd 파싱 문제가 생긴다.
    # 파이썬에서 직접 실행하면 파일명 인코딩 문제가 없다.
    log("")
    log("=" * 60)
    log("배포 번들 생성 시작 — 수 분 걸립니다 (파이썬·브라우저 런타임 포함)")
    log("=" * 60)
    import subprocess
    try:
        proc = subprocess.run(
            ["cmd", "/c", str(builder)],
            cwd=str(PACKAGE_ROOT),
            input="\r\n",
            text=True,
        )
    except Exception as exc:
        log(f"[오류] 번들 빌더 실행 실패: {type(exc).__name__}: {exc}")
        return 1
    if proc.returncode != 0:
        log(f"[오류] 번들 빌더가 코드 {proc.returncode} 로 끝났습니다.")
        return proc.returncode

    zips = sorted(PACKAGE_ROOT.glob("keyword_spend_full_*.zip"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    log("")
    if zips:
        newest = zips[0]
        log(f"[완료] 이식 패키지: {newest}  ({newest.stat().st_size/1024/1024:.0f} MB)")
    log("이 zip을 새 PC로 옮긴 뒤, 압축을 풀고 다음 순서로 실행하세요:")
    log("  1) install.bat")
    log("  2) 이식설정_적용.bat")
    log("  3) 로그인.bat (구글 등 브라우저 매체)")
    log("  4) 일일자동실행_등록.bat (08시 자동 실행을 쓸 경우)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
