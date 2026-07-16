항상 docs 폴더의 문서를 먼저 읽고 작업을 시작한다.


# CLAUDE.md — 광고 보고서 자동 다운로더

Codex / Claude가 이 저장소를 이해하기 위한 안내서입니다.

---

## 프로젝트 한 줄 요약

Windows 데스크탑 앱. PySide6 GUI + Playwright(sync) 조합으로
네이버·구글·메타·카카오·ADN·모비온·X·Google Analytics 4
8개 광고 매체의 보고서 CSV/Excel을 자동 다운로드합니다.

---

## 절대 금지 (보안 정책)

- **비밀번호를 코드·설정 파일·환경변수 어디에도 저장하지 않는다.**
- 로그인은 `chrome_profile/` 쿠키 세션 재사용 방식만 허용.
- 모비온 비밀번호는 keyring 방식 전용.
- `config.json`에 `password` 필드를 추가하는 PR은 거부.

---

## 실행 환경

| 항목 | 값 |
|------|-----|
| OS | Windows 10/11 |
| Python | 3.11+ |
| 주요 의존성 | `playwright`, `pyside6`, `pyyaml` |
| Chrome | 시스템 설치본 (`C:/Program Files/Google/Chrome/...`) |
| 진입점 | `run.bat` → `ad_report_downloader/main.py` |
| 로그인 | `로그인.bat` → `login_chrome.py` |

---

## 디렉토리 구조

```
report-downloader/
├── run.bat
├── 로그인.bat
├── login_chrome.py
├── CLAUDE.md                        # ← 이 파일
├── README.md
├── todo.md
├── docs/process.md
└── ad_report_downloader/
    ├── main.py
    ├── config.json                  # 계정 정보, 저장 경로
    ├── config_schema.py             # 기본값·유효성 검사·MEDIA_ORDER
    ├── chrome_profile/
    ├── core/
    │   ├── orchestrator.py
    │   └── chrome_lock_checker.py
    ├── downloader/
    │   ├── base.py
    │   ├── naver.py                 # ✅ 5계정
    │   ├── google.py                # ✅ 3계정
    │   ├── meta.py                  # ✅ (로그인 세션 의존)
    │   ├── kakao.py                 # ✅ (2차 인증 수동 필요)
    │   ├── adn.py                   # ✅ (테스트 필요)
    │   ├── mobion_base.py
    │   ├── mobion_banner.py         # ✅
    │   ├── mobion_daily.py          # ✅ 디스플레이 전체 필터 비활성화 포함
    │   ├── x_ads.py                 # ✅ ads.x.com/manager/{account_id}/campaigns
    │   └── google_analytics.py      # ✅ GA4 탐색 분석 CSV 다운로드
    ├── selectors/
    │   ├── naver.yaml
    │   ├── google.yaml
    │   ├── meta.yaml
    │   ├── kakao.yaml
    │   ├── adn.yaml
    │   ├── mobion_banner.yaml
    │   ├── mobion_daily.yaml
    │   ├── x.yaml
    │   └── google_analytics.yaml
    ├── utils/
    │   ├── logger.py
    │   ├── file_manager.py          # WinError 32 대응: 잠긴 파일은 _2 suffix
    │   └── config_manager.py
    └── ui/
        ├── main_window.py
        ├── media_panel.py
        ├── settings_dialog.py
        └── log_panel.py
```

---

## 핵심 아키텍처

### Chrome 실행 방식

```python
kill_chrome_processes()

pw.chromium.launch_persistent_context(
    user_data_dir="ad_report_downloader/chrome_profile/",
    executable_path=chrome_exe,
    ignore_default_args=["--disable-extensions", "--use-mock-keychain"],
    headless=False,
)
```

- `chrome_profile/`은 기본 Chrome User Data Dir이 **아님**.
- `--disable-extensions` 제거 → Chrome Password Manager 활성화.

### 다운로더 추상화

```python
class BaseDownloader(ABC):
    def run(self, context, start, end) -> DownloadResult
    def check_login(self, page) -> bool
    def navigate_to_report(self, page) -> None
    def set_period(self, page, start, end) -> None
    def trigger_download(self, page, start, end) -> Path
```

새 매체 추가 시 위 4개 메서드만 구현.

### 다중 계정

```python
units = [(media, account) for media in enabled
                          for account in media_cfg["accounts"]]
for media_code, account in units:
    downloader = build_downloader(media_code, config, account)
    result = downloader.run(context, start_date, end_date)
```

---

## 매체별 구현 포인트

### Naver 검색광고 ✅
- URL: `https://ads.naver.com/manage/ad-accounts/{account_id}/sa/reports`
- 날짜 피커: `button.ad-cms-btn-lg:has(span[style*="width: 90px"])` 클릭
- 달력: `[data-year="2026"][data-month="5"] li[data-day="15"] button`
  - `data-month`는 **0-indexed** (6월 = 5)
- 다운로드: `button.ad-cms-btn-variant-text:has-text('다운로드')`

### Google Ads ✅
- MCC 드롭다운으로 계정 전환 → 보고서 에디터 → 저장된 보고서 클릭

### Meta Ads ✅
- URL `?act={account_id}` 파라미터로 계정 전환
- 날짜 입력: MM/DD/YYYY 형식
- 로그인은 chrome_profile 세션 재사용

### Kakao ✅ (2차 인증 필요)
- 2차 인증 수동 완료 후 세션 저장 필요

### ADN ✅ (테스트 필요)
- 도메인: `manage.acrosspf.com` (로그인) → `member.acrosspf.com` (보고서)
- check_login: `manage.acrosspf.com/login` 접속 후 리디렉션으로 로그인 판별
- 계정 전환: `agency.php`의 `_jsCmLogin` 버튼 → `login_manage.php` 직접 이동
- 날짜: YYYYMMDD 직접 입력 + jQuery change 이벤트

### 모비온 배너/일자별 ✅
- `mobion_daily.py`: `trigger_download` 전에 `_deselect_display_all()` 호출
  - 셀렉터: `button.advertiser_product[data-advertiser-product='00']`
  - 디스플레이 전체 비활성화 → 인사이트 마케팅만 남김
- 로그인: Chrome Password Manager autofill

### X (Twitter) Ads ✅
- check_login: `https://ads.x.com` (base URL) 이동 후 패턴 체크
- navigate_to_report: `ads.x.com/manager/{account_id}/campaigns` 직접 이동
- 날짜 설정: Campaigns 페이지 날짜 필터 버튼 클릭 → 달력 선택
- 내보내기: `button[title='내보내기']` → `새 내보내기 생성` → `매일 보내기` → `내보내기`
- account_id: `18ce55ve4wu` (@lawyerdrug)

### Google Analytics 4 ✅
- URL: `analytics.google.com/analytics/web/#/analysis/{account_id}`
- account_id 형식: `a{ga_account_id}p{property_id}` (예: `a174946982p499720170`)
- 탐색 보고서 클릭: `div[class*='entry-title-short']:has-text('{report_name}')`
  - 대소문자 무관 매칭 (`text.lower() == report_name.lower()`)
  - URL 변경 여부로 클릭 성공 검증
- 날짜 설정:
  - `input.mat-date-range-input-inner` 는 `disabled+aria-hidden` → 클릭 불가
  - 맞춤 옵션 클릭(`force=True`) → `reach-datepicker` 다이얼로그 대기
  - `[aria-label*='YYYY년 M월 D일']` 달력 셀 직접 클릭
- 내보내기: `export_button` 셀렉터 → CSV 옵션
  - ⚠ "공유" 버튼과 별개 — 셀렉터에 "공유" 포함 금지
- **주의**: 앱 설정 저장 시 google_analytics 계정이 초기화될 수 있음
  → 저장 후 config.json 직접 확인 필요

#### GA4 계정 목록
| account_name | account_id | report_name |
|---|---|---|
| GA4_형사_NEW | a174946982p499720170 | 메타 확인용 사본 |
| GA4_마약DA전용사이트 | a174946982p523094370 | x 확인용 사본 |
| GA4_군범죄 | a174946982p445356566 | 메타 체크 사본 |
| GA4_이혼 | a174946982p358677657 | 메타 비교 사본 |

---

## 파일 저장 규칙

```
save_root_path/{브랜드명}/{Media}/{YYYYMMDD}/일별 로우/{media}_{account_name}_raw_{start}_{end}.{ext}
```

예: `보고서/법무법인_태하/Naver/20260626/일별 로우/naver_thlaw_01_raw_20260615_20260621.csv`

동일 파일명은 덮어쓰지 않고 `_002`, `_003` suffix로 누적 저장.

---

## 파일 잠금 (WinError 32) 대응

Excel에서 파일 열려 있을 때 덮어쓰기 실패 → `_2`, `_3` suffix로 대체 저장.
`utils/file_manager.py`에서 처리.

---

## 에러 발생 시 확인 순서

1. `logs/debug/` 폴더의 `.html` / `.png` 파일로 DOM 확인
2. `selectors/*.yaml` 셀렉터 수정
3. 해당 `downloader/*.py` 로직 수정
4. `orchestrator.py`는 공통 로직이므로 신중히 수정

## 자주 발생하는 문제

### __pycache__ 구버전 실행
코드 수정 후 동작이 바뀌지 않으면 pycache 삭제:
```powershell
Get-ChildItem "...\ad_report_downloader" -Recurse -Filter __pycache__ | Remove-Item -Recurse -Force
```

### git index.lock (Windows)
```powershell
Remove-Item "C:\report-downloader\.git\index.lock" -Force
```

### config.json 초기화
앱 설정 저장 시 google_analytics 섹션이 DEFAULT_CONFIG로 덮어써질 수 있음.
settings_dialog.py가 google_analytics를 인식하지 못하기 때문.
발생 시 config.json의 google_analytics.accounts를 위 계정 목록으로 복원.

---

## ADN 상세 디버그 히스토리

### 도메인 구조
- `manage.acrosspf.com/login` — 대행사 포털 로그인
- `member.acrosspf.com/agency.php` — 광고주 계정 목록
- `member.acrosspf.com/common/login_manage.php?log_id=BASE64&log_pw=BASE64&log_gbn=2` — 계정 전환
- `member.acrosspf.com/report/report_dailys.php` — 보고서

### 계정 전환 버튼 HTML
```html
<a href="javascript:;" onclick="_jsCmLogin('BASE64_ID','BASE64_PW','1')">구버전</a>
```
