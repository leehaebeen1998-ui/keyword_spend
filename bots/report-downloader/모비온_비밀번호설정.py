"""
모비온 계정 비밀번호를 Windows 자격 증명 관리자에 저장하는 스크립트.
최초 1회 실행 — 비밀번호가 바뀔 때마다 재실행.

사용법:
    python 모비온_비밀번호설정.py
"""
import json
import sys
from pathlib import Path

KEYRING_SERVICE = "ad_report_downloader_mobon"

# config.json 위치 탐색 — 보고서 자동화 폴더 우선
_CANDIDATE_PATHS = [
    Path(r"C:\Users\User\OneDrive\바탕 화면\이해빈\클로드 자동화\보고서 자동화\ad_report_downloader\config.json"),
    Path(__file__).parent / "ad_report_downloader" / "config.json",
]
CONFIG_PATH = next(
    (p for p in _CANDIDATE_PATHS if p.exists()),
    _CANDIDATE_PATHS[0],
)


def main():
    try:
        import keyring
    except ImportError:
        print("[오류] keyring 패키지가 없습니다. 아래 명령으로 설치하세요:")
        print("  pip install keyring")
        input("\n엔터를 눌러 종료...")
        sys.exit(1)

    if not CONFIG_PATH.exists():
        print(f"[오류] config.json 를 찾을 수 없습니다: {CONFIG_PATH}")
        input("\n엔터를 눌러 종료...")
        sys.exit(1)

    try:
        with CONFIG_PATH.open(encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        print(f"[오류] config.json 파싱 실패: {e}")
        print(f"  경로: {CONFIG_PATH}")
        input("\n엔터를 눌러 종료...")
        sys.exit(1)

    # 모비온 계정 목록 수집 (mobion_banner + mobion_daily 합산, 중복 제거)
    account_ids: list[tuple[str, str]] = []  # (account_id, account_name)
    seen: set[str] = set()
    for media_key in ("mobion_banner", "mobion_daily"):
        for acc in config.get("media", {}).get(media_key, {}).get("accounts", []):
            acc_id = acc.get("account_id", "")
            if acc_id and acc_id not in seen:
                seen.add(acc_id)
                account_ids.append((acc_id, acc.get("account_name", acc_id)))

    if not account_ids:
        print("[안내] config.json 에 모비온 계정이 없습니다.")
        input("\n엔터를 눌러 종료...")
        sys.exit(0)

    print("=" * 60)
    print("  모비온 계정 비밀번호 설정")
    print("  (Windows 자격 증명 관리자에 저장 — 코드에 저장 안 함)")
    print("=" * 60)
    print()
    print("모든 모비온 서브계정에 동일한 2차 비밀번호를 사용한다면")
    print("첫 번째 입력 후 나머지는 엔터만 눌러도 됩니다.")
    print("※ 입력한 비밀번호가 화면에 표시됩니다 (Windows IME 호환)")
    print()

    last_pw = ""
    saved = 0

    for acc_id, acc_name in account_ids:
        existing = keyring.get_password(KEYRING_SERVICE, acc_id) or ""
        hint = " [저장됨, 엔터=유지]" if existing else " [미설정]"
        prompt = f"  {acc_name} ({acc_id}){hint}: "

        # getpass: 입력 시 화면에 표시 안 함
        pw = input(prompt)

        if pw == "" and existing:
            print(f"    → 기존 비밀번호 유지")
            continue
        if pw == "" and last_pw:
            pw = last_pw
            print(f"    → 이전 비밀번호 복사 적용")
        if pw == "":
            print(f"    → 건너뜀 (비어있음)")
            continue

        keyring.set_password(KEYRING_SERVICE, acc_id, pw)
        last_pw = pw
        saved += 1
        print(f"    → 저장 완료")

    print()
    print(f"총 {saved}개 계정 비밀번호 저장 완료.")
    print("이제 앱을 실행하면 자동으로 비밀번호를 사용합니다.")
    input("\n엔터를 눌러 종료...")


if __name__ == "__main__":
    main()
