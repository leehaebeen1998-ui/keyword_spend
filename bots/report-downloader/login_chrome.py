"""
광고 보고서 자동화 - 로그인 세션 설정
전용 Chrome 프로필(chrome_profile/)에 각 광고 플랫폼 로그인을 저장합니다.
최초 1회 또는 세션 만료 시 실행하세요.
"""
import os
import sys

# Playwright 경로 설정
script_dir = os.path.dirname(os.path.abspath(__file__))
adn_dir = os.path.join(script_dir, "ad_report_downloader")
sys.path.insert(0, adn_dir)

from playwright.sync_api import sync_playwright

# 전용 프로필 디렉토리 (run.bat과 동일 경로 사용)
profile_dir = os.path.join(adn_dir, "chrome_profile")

# Chrome 실행 파일 탐색
def find_chrome():
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None

chrome_exe = find_chrome()

print()
print("=" * 50)
print("  광고 보고서 자동화 - 로그인 세션 설정")
print("=" * 50)
print()
print(f"프로필 저장 위치: {profile_dir}")
print()
print("Chrome이 열리면 아래 사이트에 로그인하세요:")
print("  1. 네이버 검색광고")
print("  2. Google Ads")
print("  3. Meta Ads")
print("  4. ADN 대행사")
print("  5. 카카오 키워드광고 (2차 인증 필요)")
print()
print("Meta, ADN, 카카오는 반드시 열린 자동화 Chrome 창에서 로그인하세요.")
print("ADN은 '대행사' 탭을 선택한 상태로 열립니다.")
print("모든 로그인 완료 후 이 창에서 Enter를 누르면 저장됩니다.")
print()

with sync_playwright() as pw:
    context = pw.chromium.launch_persistent_context(
        user_data_dir=profile_dir,
        executable_path=chrome_exe,
        headless=False,
        ignore_default_args=["--disable-extensions", "--use-mock-keychain"],
        args=[
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-session-crashed-bubble",
            "--disable-blink-features=AutomationControlled",
        ],
        viewport={"width": 1280, "height": 900},
    )

    # 봇 감지 우회 — navigator.webdriver 숨김
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        window.chrome = {runtime: {}};
        Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
        Object.defineProperty(navigator, 'languages', {get: () => ['ko-KR', 'ko', 'en-US', 'en']});
    """)

    # 각 매체 로그인 탭 열기. 계정 정보 입력은 사용자가 직접 수행한다.
    targets = [
        ("네이버", "https://ads.naver.com"),
        ("Google", "https://ads.google.com"),
        ("Meta",   "https://adsmanager.facebook.com/adsreporting/"),
        ("ADN",    "https://manage.acrosspf.com/login"),
        ("Kakao",  "https://keywordad.kakao.com"),
        ("모비온",  "https://www.mobon.net/main/m2/"),
    ]
    pages = {}
    for name, url in targets:
        page = context.new_page()
        pages[name] = page
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except Exception as exc:
            print(f"  [주의] {name} 페이지 이동 지연: {exc}")

    # ADN 로그인 화면은 기본이 광고주 탭이므로 대행사 탭으로 전환한다.
    try:
        agency_tab = pages["ADN"].get_by_role("tab", name="대행사")
        agency_tab.wait_for(state="visible", timeout=10_000)
        agency_tab.click()
    except Exception:
        print("  [주의] ADN '대행사' 탭 자동 선택 실패 - 화면에서 직접 선택하세요.")

    # 모비온: Password Manager autofill 후 로그인 버튼 자동 클릭
    import time
    try:
        mobon_page = pages["모비온"]
        mobon_page.bring_to_front()
        time.sleep(4)  # autofill 대기 (Chrome Password Manager 반응 시간 확보)

        # 로그인 버튼이 보일 때까지 대기 후 클릭
        btn = mobon_page.locator("button#login.btn-login, button#login, button.btn-login").first
        btn.wait_for(state="visible", timeout=8_000)
        btn.click()
        # 로그인 완료 후 페이지 전환 대기
        try:
            mobon_page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            pass
        print("  [모비온] 로그인 버튼 클릭 완료")
    except Exception as e:
        print(f"  [주의] 모비온 로그인 버튼 자동 클릭 실패: {e}")
        print("  → Chrome 창에서 직접 로그인해주세요.")

    while True:
        input(">>> 모든 계정 로그인 완료 후 Enter 키를 누르세요...")
        print()
        print("로그인 상태 확인:")

        meta_url = pages["Meta"].url.lower()
        meta_ok = (
            "adsmanager.facebook.com" in meta_url
            and "/login" not in meta_url
            and "/checkpoint" not in meta_url
        )

        # ADN: 크로스 도메인 리다이렉트 후 stale 가능 → 모든 탭 검색
        adn_ok = False
        adn_display_url = pages["ADN"].url
        for p in context.pages:
            try:
                purl = p.evaluate("window.location.href")
            except Exception:
                purl = p.url
            if "acrosspf.com" in purl.lower() and "/login" not in purl.lower():
                adn_ok = True
                adn_display_url = purl
                break

        kakao_url = pages["Kakao"].url.lower()
        kakao_ok = (
            "keywordad.kakao.com" in kakao_url
            and "accounts.kakao.com" not in kakao_url
        )

        print(f"  Meta : {'확인됨' if meta_ok  else '로그인 필요'} ({pages['Meta'].url})")
        print(f"  ADN  : {'확인됨' if adn_ok   else '로그인 필요'} ({adn_display_url})")
        print(f"  Kakao: {'확인됨' if kakao_ok else '로그인 필요'} ({pages['Kakao'].url})")

        if meta_ok and adn_ok and kakao_ok:
            break
        print()
        print("로그인이 완료되지 않은 매체가 있습니다.")
        print("Chrome 창에서 로그인한 뒤 다시 확인해주세요.")

    context.close()

# ADN 비밀번호를 Windows 자격 증명 관리자에 저장 (최초 1회 / 갱신 시)
print()
print("ADN 비밀번호 저장 (Windows 자격 증명 관리자)")
print("-" * 40)
try:
    import keyring
    import getpass as _gp

    _SVC  = "ad_report_downloader_adn"
    _USER = "giomglobal"

    existing = None
    try:
        existing = keyring.get_password(_SVC, _USER)
    except Exception:
        pass

    if existing:
        ans = input("기존 저장된 ADN 비밀번호가 있습니다. 재설정하시겠습니까? [y/N]: ").strip().lower()
        if ans == "y":
            pw = _gp.getpass(f"ADN [{_USER}] 새 비밀번호: ")
            if pw:
                keyring.set_password(_SVC, _USER, pw)
                print("✓ ADN 비밀번호 재저장 완료.")
            else:
                print("미입력 — 기존 유지.")
        else:
            print("기존 비밀번호 유지.")
    else:
        pw = _gp.getpass(f"ADN [{_USER}] 비밀번호: ")
        if pw:
            keyring.set_password(_SVC, _USER, pw)
            print("✓ ADN 비밀번호가 저장되었습니다. 이후 run.bat은 자동 로그인됩니다.")
        else:
            print("미입력 — ADN 자동 로그인 비활성화.")
except ImportError:
    print("[주의] keyring 미설치 → pip install keyring 실행 후 다시 시도하세요.")
except Exception as e:
    print(f"[주의] 비밀번호 저장 실패: {e}")

# 카카오 비밀번호를 Windows 자격 증명 관리자에 저장 (최초 1회 / 갱신 시)
print()
print("카카오 비밀번호 저장 (Windows 자격 증명 관리자)")
print("-" * 40)
try:
    import keyring as _kr
    import getpass as _gp2

    _KAKAO_SVC  = "ad_report_downloader_kakao"
    _KAKAO_USER = "eodls1489@naver.com"

    existing_kakao = None
    try:
        existing_kakao = _kr.get_password(_KAKAO_SVC, _KAKAO_USER)
    except Exception:
        pass

    if existing_kakao:
        ans = input("기존 저장된 카카오 비밀번호가 있습니다. 재설정하시겠습니까? [y/N]: ").strip().lower()
        if ans == "y":
            pw = _gp2.getpass(f"카카오 [{_KAKAO_USER}] 새 비밀번호: ")
            if pw:
                _kr.set_password(_KAKAO_SVC, _KAKAO_USER, pw)
                print("✓ 카카오 비밀번호 재저장 완료.")
            else:
                print("미입력 — 기존 유지.")
        else:
            print("기존 비밀번호 유지.")
    else:
        pw = _gp2.getpass(f"카카오 [{_KAKAO_USER}] 비밀번호: ")
        if pw:
            _kr.set_password(_KAKAO_SVC, _KAKAO_USER, pw)
            print("✓ 카카오 비밀번호가 저장되었습니다. 이후 run.bat은 자동 로그인됩니다.")
        else:
            print("미입력 — 카카오 자동 로그인 비활성화.")
except ImportError:
    print("[주의] keyring 미설치 → pip install keyring 실행 후 다시 시도하세요.")
except Exception as e:
    print(f"[주의] 비밀번호 저장 실패: {e}")

print()
print("로그인 정보가 저장되었습니다!")
print("이제 run.bat을 실행하면 자동으로 로그인된 상태로 동작합니다.")
print()
input("이 창을 닫으려면 Enter를 누르세요...")
