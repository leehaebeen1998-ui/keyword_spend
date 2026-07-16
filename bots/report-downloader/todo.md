# 작업 목록 (Todo)

> 상태: ✅ 완료 / 🔄 진행 중 / ⬜ 미착수 / ❌ 보류

---

## 인프라 / 공통

| 상태 | 항목 |
|------|------|
| ✅ | PySide6 GUI 기본 구조 (main_window, media_panel, log_panel) |
| ✅ | OrchestratorWorker (QThread) — Chrome 실행 + 순차 다운로드 |
| ✅ | Chrome 전용 프로필 (`chrome_profile/`) + launch_persistent_context |
| ✅ | kill_chrome_processes() — 기존 Chrome 강제 종료 |
| ✅ | BaseDownloader 추상 클래스 — retry, screenshot, file move |
| ✅ | config.json 스키마 + 설정 다이얼로그 |
| ✅ | 로그인.bat / login_chrome.py — 최초 세션 저장 |
| ✅ | 셀렉터 YAML 외부화 (selectors/*.yaml) |
| ⬜ | 전체 단위 테스트 |
| ⬜ | 실행 오류 시 알림 (Windows 토스트 또는 이메일) |

---

## Naver 검색광고

| 상태 | 항목 |
|------|------|
| ✅ | 로그인 세션 확인 (`check_login`) |
| ✅ | 보고서 목록 URL 이동 + 이름으로 클릭 |
| ✅ | 날짜 피커 버튼 클릭 (rwc-month 캘린더 감지) |
| 🔄 | 날짜 직접 클릭 (`data-year`, `data-month`, `data-day`) |
| ✅ | 다운로드 버튼 클릭 + CSV 저장 |
| ⬜ | 날짜 설정 후 실제 기간 검증 |

---

## Google Ads

| 상태 | 항목 |
|------|------|
| ✅ | MCC 드롭다운 계정 전환 |
| ✅ | 보고서 에디터 → 저장된 보고서 클릭 |
| ✅ | 캠페인/광고그룹 필터 "전체" 리셋 |
| ✅ | 다운로드 → Excel 형식 선택 |
| ⬜ | 로그인 세션 확인 + 테스트 |

---

## Meta Ads

| 상태 | 항목 |
|------|------|
| ✅ | URL `act=` 파라미터로 계정 전환 |
| ✅ | 날짜 MM/DD/YYYY 입력 |
| ✅ | 다운로드 버튼 (`data-surface='am/lib:export_button'`) |
| ⬜ | 로그인 세션 확인 + 테스트 |

---

## Kakao 키워드광고

| 상태 | 항목 |
|------|------|
| ✅ | URL `/{account_id}/report` 경로로 계정 전환 |
| ✅ | 날짜 피커 (달력 클릭 또는 input fallback) |
| ✅ | 다운로드 버튼 클릭 |
| ⬜ | 로그인 세션 확인 + 테스트 |
| ⬜ | 2번째 계정 정보 입력 (account_id 미설정) |

---

## ADN

| 상태 | 항목 |
|------|------|
| ✅ | 계정 목록 테이블 → "구버전" 버튼 클릭으로 전환 |
| ✅ | YYYYMMDD 날짜 직접 입력 + jQuery change 이벤트 |
| ✅ | 캠페인/그룹/소재 포함 체크박스 처리 |
| ⬜ | 10개 계정 account_id 입력 (현재 "입력필요") |
| ⬜ | 로그인 세션 확인 + 테스트 |

---

## 모비온 (통합배너 / 일자별)

| 상태 | 항목 |
|------|------|
| ✅ | 광고주 로그인 모달 — Chrome Password Manager autofill |
| ✅ | daterangepicker 달력 내비게이션 |
| ✅ | 계정 전환 |
| ⬜ | 15개 계정 정보 입력 (4번~15번 미설정) |
| ⬜ | 로그인 세션 확인 + 테스트 |

---

## X (Twitter) Ads

| 상태 | 항목 |
|------|------|
| ✅ | 분석 페이지 Ads 탭 이동 |
| ✅ | 내보내기 다이얼로그 — 날짜 설정 + 제출 |
| ✅ | fallback: 이전 다운로드 목록 |
| ⬜ | 로그인 세션 확인 + 테스트 |

---

## 미완성 설정값 (config.json 입력 필요)

| 매체 | 항목 |
|------|------|
| Google | 3개 계정 account_name / account_id |
| Kakao | 2번째 계정 account_id |
| ADN | 10개 계정 account_id |
| 모비온 | 4~15번째 계정 account_name / account_id |

---

## 다음 우선순위

1. 🔄 Naver 날짜 캘린더 클릭 검증 (06.15~06.21 정상 여부)
2. ⬜ Google 로그인 후 실제 다운로드 테스트
3. ⬜ Meta 로그인 후 실제 다운로드 테스트
4. ⬜ config.json 나머지 계정 정보 입력
5. ⬜ 전체 매체 통합 실행 테스트
