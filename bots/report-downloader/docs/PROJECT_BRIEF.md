# PROJECT_BRIEF — 광고 보고서 자동 다운로더

> Codex/Claude 인수인계용 문서. 프로젝트의 목적·구조·규칙·역할 분담·향후 계획을 한 곳에 정리합니다.
> GitHub: https://github.com/leehaebeen1998-ui/report-downloader

---

## 1. 프로젝트 목적

광고 대행사 실무에서 매주 반복되는 보고서 수작업을 자동화합니다.

담당자가 **네이버·구글·메타·카카오·ADN·모비온·X(Twitter)** 7개 광고 매체에 직접 접속해 CSV/Excel 로우 데이터를 내려받는 작업을 단 한 번의 클릭으로 대체합니다.

- 대상 사용자: 광고 대행사 담당자 (비개발자)
- 실행 환경: Windows 10/11 데스크탑
- 핵심 가치: **시간 절약 + 휴먼 에러 제거 + 보안 (비밀번호 미저장)**

---

## 2. 현재 구현된 기능

### 인프라

| 항목 | 상태 | 설명 |
|------|------|------|
| PySide6 GUI | ✅ | 매체 선택, 기간 설정, 실행 로그, 진행률 표시 |
| OrchestratorWorker | ✅ | QThread 기반 — Chrome 실행 후 (매체 × 계정) 순차 실행 |
| Chrome 프로필 세션 | ✅ | `chrome_profile/`에 1회 로그인 → 이후 자동 세션 재사용 |
| BaseDownloader | ✅ | 추상 클래스 — 재시도 루프, 스크린샷, 파일 이동 포함 |
| 셀렉터 YAML 외부화 | ✅ | `selectors/*.yaml` — 코드 수정 없이 UI 변경 대응 |
| 디버그 스크린샷 | ✅ | 실패 시 `logs/debug/` 에 PNG + HTML 자동 저장 |
| 보안 설계 | ✅ | 비밀번호 코드·파일 미저장, Chrome Password Manager 활용 |

### 매체별 구현 현황

| 매체 | 로그인 | 계정 전환 | 날짜 설정 | 다운로드 | 통합 테스트 |
|------|--------|-----------|-----------|----------|-------------|
| **Naver** | ✅ | ✅ (URL account_id) | ✅ (캘린더 클릭) | ✅ (CSV) | ✅ 5계정 정상 |
| **Google** | ✅ | ✅ (MCC 드롭다운) | ✅ (ISO input) | ✅ (Excel) | ✅ 3계정 정상 |
| **Meta** | 🔴 미해결 | ✅ (act= 파라미터) | ✅ (MM/DD/YYYY) | ✅ | ⬜ 테스트 필요 |
| **Kakao** | ⏸️ 스킵 | ✅ (URL account_id) | ✅ (달력) | ✅ | ⬜ 2차 인증 필요 |
| **ADN** | 🟡 진행 중 | ✅ (구버전 버튼) | ✅ (YYYYMMDD) | ✅ | ⬜ 테스트 필요 |
| **모비온 배너** | ⏸️ 미시작 | ✅ (광고주 모달) | ✅ (daterangepicker) | ✅ | ⬜ 테스트 필요 |
| **모비온 일자별** | ⏸️ 미시작 | ✅ (광고주 모달) | ✅ (daterangepicker) | ✅ | ⬜ 테스트 필요 |
| **X(Twitter)** | ⏸️ 미시작 | - (단일 계정) | ✅ (다이얼로그) | ✅ | ⬜ 테스트 필요 |

---

## 3. 개발 규칙

### 3-1. 보안 (절대 금지)

```
❌ config.json에 password 필드 추가
❌ .py 파일에 비밀번호 하드코딩
❌ 환경변수에 비밀번호 저장
❌ chrome_profile/ 디렉토리를 GitHub에 커밋
```

로그인 방식은 **Chrome 프로필 쿠키 재사용**만 허용합니다. 예외: 모비온은 Chrome Password Manager autofill 전용.

### 3-2. 셀렉터 관리

UI 변경 시 `downloader/*.py` 코드를 수정하지 않고 `selectors/*.yaml`만 수정합니다.

```yaml
# 예: selectors/adn.yaml
download:
  button: "a.btn.btn-dark:has-text('다운로드')"
```

실패 시 `logs/debug/{media}_{label}_{timestamp}.html`로 DOM 확인 후 YAML 수정.

### 3-3. 새 매체 추가 방법

`BaseDownloader`를 상속해 4개 메서드만 구현하면 됩니다:

```python
class NewMediaDownloader(BaseDownloader):
    MEDIA_CODE = "new_media"
    IMPLEMENTED = True

    def check_login(self, page) -> bool: ...
    def navigate_to_report(self, page) -> None: ...
    def set_period(self, page, start, end) -> None: ...
    def trigger_download(self, page, start, end) -> Path: ...
```

### 3-4. 파일 저장 규칙

```
save_root_path/{브랜드명}/{Media}/{YYYYMMDD}/일별 로우/{media}_{account_name}_raw_{start}_{end}.{ext}
예) 보고서/법무법인_태하/Naver/20260623/일별 로우/naver_thlaw_01_raw_20260615_20260621.csv
```

동일 파일명은 덮어쓰지 않고 `_002`, `_003` suffix로 누적 저장합니다.

### 3-5. 핵심 아키텍처 원칙

- Playwright sync API는 **OrchestratorWorker(QThread) 내부에서만** 사용
- UI 업데이트는 **Qt Signal로만** — UI 메서드 직접 호출 금지
- 단일 BrowserContext를 모든 매체·계정이 공유 (탭 단위로 열고 닫음)
- 재시도 횟수: `config.json → retry.max_attempts` (기본 2회)

---

## 4. Claude의 역할

Claude(Cowork 데스크탑)는 **실시간 코드 수정 + 즉시 테스트** 담당입니다.

| 작업 유형 | 예시 |
|-----------|------|
| 버그 수정 | 셀렉터 오류, 로그인 체크 로직, 날짜 파싱 오류 |
| YAML 셀렉터 업데이트 | 매체 UI 변경 시 selectors/*.yaml 수정 |
| 로그 분석 | 사용자가 공유하는 실행 로그 기반 원인 파악 |
| 문서 업데이트 | CLAUDE.md, docs/*.md 최신 상태 유지 |
| Git 준비 | .gitignore 관리, 커밋 전 파일 검토 |

**작업 흐름**: 사용자가 실행 → 로그·스크린샷 공유 → Claude가 원인 분석 → 코드/YAML 수정 → 재테스트

---

## 5. Codex의 역할

Codex(GitHub Copilot Workspace)는 **복잡한 로그인 문제 + 대규모 리팩터링** 담당입니다.

| 작업 유형 | 우선순위 | 설명 |
|-----------|----------|------|
| Meta 로그인 해결 | 🔴 높음 | CDP 포트 문제 또는 undetected-chromedriver 방식 |
| ADN 로그인 검증 | 🟡 중간 | check_login 수정 후 실제 동작 테스트 |
| 모비온 로그인 구현 | 🟡 중간 | Chrome Password Manager autofill 흐름 |
| X 로그인 구현 | 🟢 낮음 | 단일 계정, 세션 방식 |
| 전체 통합 테스트 | 🟡 중간 | 7개 매체 동시 실행 검증 |

### Meta 로그인 문제 상세 (Codex 해결 필요)

```
증상: Playwright launch_persistent_context → Meta 봇 감지 차단
시도한 방법:
  1. browser_cookie3         → Chrome 127 App-Bound Encryption 실패
  2. 쿠키 파일 직접 복사      → Local State 암호화 키 불일치
  3. 직접 로그인             → Arkose Labs CAPTCHA 차단
  4. CDP connect_over_cdp   → 포트 ECONNREFUSED

권장 해결 방향:
  - undetected-chromedriver + Selenium으로 로그인 후 쿠키 추출
  - 또는 SingletonLock 삭제 후 독립 Chrome 프로세스로 CDP 연결
관련 파일: meta_cookie_import.py, downloader/meta.py
```

---

## 6. 향후 기능 계획

### 단기 (1~2주)

| 항목 | 담당 |
|------|------|
| Meta 로그인 문제 해결 | Codex |
| ADN 10개 계정 테스트 및 account_id 입력 | 사용자 + Claude |
| 모비온 로그인·다운로드 테스트 | Codex |
| X 로그인·다운로드 테스트 | Codex |
| Kakao 2차 인증 후 테스트 | 사용자 + Claude |

### 중기 (1개월)

| 항목 | 설명 |
|------|------|
| 전체 매체 통합 실행 | 7개 매체 순차 실행 → 오류 없이 완료 |
| 실행 완료 알림 | Windows 토스트 또는 이메일 알림 |
| 스케줄 실행 | Windows 작업 스케줄러 연동 (매주 월요일 자동 실행) |
| 보고서 집계 자동화 | 다운로드 후 Excel 병합·정리 스크립트 |

### 장기

| 항목 | 설명 |
|------|------|
| 단위 테스트 | 매체별 mock 기반 자동화 테스트 |
| config.json GUI 편집기 개선 | 계정 추가/삭제 UI |
| 다운로드 결과 대시보드 | 매체별 성공/실패 현황 시각화 |

---

## 7. 작업 프로세스

### 일반 버그 수정 (Claude)

```
1. 사용자: run.bat 실행 후 로그 또는 스크린샷 공유
2. Claude: logs/debug/*.html 분석 → 원인 파악
3. Claude: selectors/*.yaml 또는 downloader/*.py 수정
4. 사용자: 재실행 → 결과 확인
5. Claude: CLAUDE.md 상태 업데이트 + git_push.bat 준비
```

### 복잡한 로그인 문제 (Codex)

```
1. Claude: 문제 상황, 시도한 방법, 실패 원인을 CLAUDE.md에 기록
2. git_push.bat 실행 → GitHub 최신화
3. Codex: GitHub 저장소 분석 → 해결책 구현
4. Claude: 사용자와 함께 테스트 → 결과 CLAUDE.md에 반영
```

### 새 계정 추가

```
config.json → media.{매체}.accounts 배열에 추가:
{
  "account_name": "표시명 (파일명에 사용됨)",
  "account_id":   "매체에서 확인한 ID",
  "report_name":  "저장된 보고서 이름"
}
```

### 세션 만료 시 재로그인

```
로그인.bat 실행 → Chrome 탭에서 해당 매체 재로그인 → Enter
```

---

## 8. 파일별 역할 요약

| 파일 | 역할 |
|------|------|
| `run.bat` | 앱 실행 진입점 |
| `로그인.bat` | 최초 1회 또는 세션 만료 시 Chrome 프로필 로그인 |
| `login_chrome.py` | 로그인 스크립트 (Naver·Meta·ADN 탭 자동 오픈) |
| `config.json` | 계정 정보·저장 경로·설정값 |
| `ad_report_downloader/main.py` | PySide6 앱 시작점 |
| `core/orchestrator.py` | QThread 워커 — Chrome 실행 + 전체 다운로드 흐름 |
| `downloader/base.py` | 재시도·로깅·파일이동 공통 로직 |
| `downloader/{media}.py` | 매체별 로그인·날짜설정·다운로드 구현 |
| `selectors/{media}.yaml` | 매체별 CSS 셀렉터 (코드와 분리) |
| `CLAUDE.md` | 개발자용 전체 프로젝트 가이드 (항상 최신 유지) |
| `docs/process.md` | 실행 흐름 및 매체별 로직 상세 |
| `docs/PROJECT_BRIEF.md` | 이 파일 — Codex/Claude 인수인계용 |
| `git_push.bat` | GitHub 푸시 (git add -A → commit → push) |

---

*최종 업데이트: 2026-06-24*
*담당: leehaebeen1998@gmail.com*
