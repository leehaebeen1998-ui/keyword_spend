# 프로그램 로직 상세 (Process)

## 전체 실행 흐름

```
run.bat
  └─ python main.py
       └─ QApplication + MainWindow (PySide6)
            └─ [실행 버튼 클릭]
                 └─ OrchestratorWorker (QThread)
                      ├─ 1. _preflight()         저장 경로 검증
                      ├─ 2. kill_chrome()         기존 Chrome 종료
                      ├─ 3. launch Chrome         전용 프로필로 실행
                      ├─ 4. connect Playwright    launch_persistent_context
                      └─ 5. _run_all()            매체 × 계정 순차 실행
                               └─ downloader.run(context, start, end)
                                    ├─ check_login()
                                    ├─ navigate_to_report()
                                    ├─ set_period()
                                    ├─ trigger_download() → tmp_path
                                    └─ move_download() → 최종 저장
```

---

## Chrome 실행 방식

```python
# 전용 프로필 경로 (기본 Chrome User Data Dir 아님 → 원격 디버깅 허용)
profile_dir = <script_dir>/chrome_profile/

# 기존 Chrome 프로세스 종료 (충돌 방지)
taskkill /F /IM chrome.exe /T

# Playwright launch_persistent_context
pw.chromium.launch_persistent_context(
    user_data_dir=profile_dir,
    executable_path=chrome.exe,
    ignore_default_args=["--disable-extensions", "--use-mock-keychain"],
    headless=False,
)
```

**포인트**: `chrome_profile/`은 사용자의 기본 Chrome 프로필이 아니므로 `--remote-debugging-pipe` 제한 없음. `--disable-extensions` 제거로 Chrome Password Manager 활성화.

---

## 매체별 로직

### Naver 검색광고

| 단계 | 방법 |
|------|------|
| 계정 전환 | URL에 account_id 포함: `/manage/ad-accounts/{id}/sa/reports` |
| 보고서 찾기 | `get_by_text(report_name)` 또는 `a[href*='/sa/reports/rtt-']` |
| 날짜 설정 | `button.ad-cms-btn-lg:has(span[style*="width: 90px"])` 클릭 → `[data-year][data-month] li[data-day] button` 캘린더 클릭 |
| 다운로드 | `button.ad-cms-btn-variant-text:has-text('다운로드')` |
| 날짜 형식 | YYYY.MM.DD. (점 포함), 캘린더 data-month는 0-indexed |

### Google Ads

| 단계 | 방법 |
|------|------|
| 계정 전환 | MCC 드롭다운 → account_name 텍스트 매칭 |
| 보고서 찾기 | 사이드바 → 보고서 에디터 → 저장된 보고서 클릭 |
| 날짜 설정 | 맞춤 기간 → ISO 형식 input 입력 |
| 다운로드 | 다운로드 아이콘 → Excel 형식 선택 |

### Meta Ads

| 단계 | 방법 |
|------|------|
| 계정 전환 | URL: `?act={account_id}&business_id={business_id}` |
| 날짜 설정 | MM/DD/YYYY 형식 input 입력 |
| 다운로드 | `[data-surface='am/lib:export_button']` |

### Kakao 키워드광고

| 단계 | 방법 |
|------|------|
| 계정 전환 | URL 경로: `/{account_id}/report` |
| 날짜 설정 | 달력 UI 클릭 또는 input fallback |
| 다운로드 | `button.btn_gm.gm_line:has(span.ico_download)` |

### ADN

| 단계 | 방법 |
|------|------|
| 계정 전환 | 계정 목록 테이블 → account_name 행 → "구버전" 버튼 |
| 날짜 설정 | YYYYMMDD 직접 입력 + jQuery change 이벤트 dispatch |
| 다운로드 | 직접 URL `/report/report_dailys.php` |

### 모비온 (배너 / 일자별)

| 단계 | 방법 |
|------|------|
| 로그인 | Chrome Password Manager autofill (비밀번호 코드 저장 금지) |
| 계정 전환 | "광고주 로그인" 모달 |
| 날짜 설정 | daterangepicker 달력 클릭 |

### X (Twitter) Ads

| 단계 | 방법 |
|------|------|
| 이동 | 분석 페이지 → Ads 탭 |
| 내보내기 | 다이얼로그 → 날짜 설정 → 제출 |
| fallback | 이전 다운로드 목록에서 재다운로드 |

---

## 파일 저장 구조

```
save_root_path/
└─ 브랜드명/
   └─ 매체/
      └─ YYYYMMDD/           실행일 기준 폴더
         └─ 일별 로우/
            ├─ naver_thlaw_01_raw_20260615_20260621.csv
            └─ naver_thlaw_02_raw_20260615_20260621.csv
```

파일명 규칙: `{media}_{account_name}_raw_{start}_{end}.{ext}`
동일 파일명이 있으면 기존 파일을 삭제하지 않고 `_002`, `_003` suffix로 누적 저장.

---

## 재시도 로직

```python
max_attempts = config["retry"]["max_attempts"]  # 기본 2회

for attempt in range(1, max_attempts + 1):
    try:
        # 다운로드 시도
        ...
        return DownloadResult(success=True)
    except LoginRequiredError:
        return skip("로그인 필요")   # 재시도 없음
    except EmptyDataError:
        return skip("데이터 없음")   # 재시도 없음
    except Exception:
        if attempt < max_attempts:
            sleep(random 2~4초)
```

---

## 다중 계정 처리

```python
# (매체, 계정) 쌍으로 진행 단위 구성
units = [(media, account) for media in enabled
                          for account in media_cfg["accounts"]]

for media_code, account in units:
    downloader = build_downloader(media_code, config, account)
    result = downloader.run(context, start_date, end_date)
```

진행률 = 완료된 (매체, 계정) 쌍 수 / 전체 쌍 수

---

## 보안 설계

| 항목 | 방침 |
|------|------|
| 비밀번호 저장 | **절대 금지** — config.json, 코드, 환경변수 어디에도 저장 안 함 |
| 로그인 세션 | Chrome 프로필 쿠키 재사용 (`chrome_profile/`) |
| 모비온 PW | Chrome Password Manager autofill 전용 |
| 자동화 감지 | `ignore_default_args=["--enable-automation"]` 고려 가능 |

---

## 셀렉터 관리

- 매체별로 `selectors/*.yaml`에 외부화
- UI 변경 시 코드 수정 없이 YAML만 수정
- 주요 셀렉터는 YAML 내 주석으로 HTML 구조 설명 포함

---

## 디버그 스크린샷

실패 시 `logs/debug/{media}_{label}_{timestamp}.png` + `.html` 자동 저장.

`html` 파일에서 실제 DOM 구조를 분석해 셀렉터 수정 가능.
