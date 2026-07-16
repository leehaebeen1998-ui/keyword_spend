"""
Meta 쿠키 추출 (CDP 방식)
"""
import os, sys, json, subprocess, time, urllib.request

script_dir  = os.path.dirname(os.path.abspath(__file__))
output_path = os.path.join(script_dir, "ad_report_downloader", "meta_cookies.json")

CHROME_EXE  = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CHROME_DATA = os.path.expandvars(r"C:\Users\User\AppData\Local\Google\Chrome\User Data")
DEBUG_PORT  = 9222

print()
print("=" * 55)
print("  Meta 쿠키 추출 (CDP 방식)")
print("=" * 55)
print()

# ── 기존 Chrome 종료 ───────────────────────────────────────────────────────────
print("[1] Chrome 프로세스 종료 중...")
subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], capture_output=True)
subprocess.run(["taskkill", "/F", "/IM", "chromedriver.exe"], capture_output=True)
time.sleep(3)

# 싱글톤 잠금 파일 삭제 (Chrome이 이미 실행 중이라고 착각하는 것 방지)
for lock_file in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
    lock_path = os.path.join(CHROME_DATA, lock_file)
    try:
        if os.path.exists(lock_path):
            os.remove(lock_path)
            print(f"    잠금 파일 삭제: {lock_file}")
    except Exception:
        pass
print("    완료")

# ── Chrome 실행 ────────────────────────────────────────────────────────────────
print(f"[2] Chrome 실행 (포트 {DEBUG_PORT})...")
proc = subprocess.Popen([
    CHROME_EXE,
    f"--remote-debugging-port={DEBUG_PORT}",
    f"--remote-debugging-address=127.0.0.1",
    f"--user-data-dir={CHROME_DATA}",
    "--profile-directory=Default",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-session-crashed-bubble",
    "https://adsmanager.facebook.com",
])
print(f"    PID: {proc.pid}")

# ── 포트 열릴 때까지 대기 ─────────────────────────────────────────────────────
print(f"[3] 디버깅 포트 대기 중...")
port_ready = False
for i in range(20):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json", timeout=2)
        port_ready = True
        print(f"    포트 열림! ({i+1}초)")
        break
    except Exception:
        print(f"    대기 중... {i+1}/20초")
        time.sleep(1)

if not port_ready:
    print()
    print("✗ Chrome 디버깅 포트에 연결할 수 없습니다.")
    print("  방화벽이 9222 포트를 차단하고 있을 수 있습니다.")
    subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], capture_output=True)
    input("Enter를 눌러 종료...")
    sys.exit(1)

# ── 로그인 확인 ───────────────────────────────────────────────────────────────
print()
print("Chrome이 열렸습니다.")
print("adsmanager.facebook.com에 로그인된 것을 확인하세요.")
print()
input("확인 후 Enter를 누르세요...")
print()

# ── 쿠키 추출 ─────────────────────────────────────────────────────────────────
print("[4] 쿠키 추출 중...")
try:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{DEBUG_PORT}")
        contexts = browser.contexts
        print(f"    컨텍스트 수: {len(contexts)}")

        context = contexts[0] if contexts else None
        if context is None:
            raise RuntimeError("Chrome 컨텍스트 없음")

        cookies = context.cookies([
            "https://www.facebook.com",
            "https://adsmanager.facebook.com",
            "https://business.facebook.com",
        ])
        print(f"    추출된 쿠키 수: {len(cookies)}")
        browser.close()

    if not cookies:
        raise RuntimeError("Facebook 쿠키 없음 — adsmanager에 로그인 상태인지 확인")

    for c in cookies:
        if c.get("sameSite") not in ("Strict", "Lax", "None"):
            c["sameSite"] = "None"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(cookies, f, indent=2, ensure_ascii=False)

    print()
    print(f"✅ 쿠키 {len(cookies)}개 저장 완료")
    print(f"   위치: {output_path}")

except Exception as e:
    print(f"✗ 실패: {e}")
    subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], capture_output=True)
    input("Enter를 눌러 종료...")
    sys.exit(1)

subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], capture_output=True)
print("Chrome 종료 완료")
print()
print("이제 run.bat으로 자동화를 실행하세요.")
print()
input("Enter를 눌러 종료...")
