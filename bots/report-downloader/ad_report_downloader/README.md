# 광고 매체 보고서 자동 다운로드 프로그램

## 개요

매체별 광고 관리자 페이지에 접속해 지정 기간의 보고서를 자동으로 다운로드하고, 매체별 폴더 구조로 정리 저장하는 Windows 데스크톱 프로그램.

- **기술 스택:** Python · Playwright · PySide6
- **인증 방식:** Chrome 로그인 프로필 재사용 (ID/PW 저장 없음)
- **지원 매체:** Naver 검색광고 · Google Ads · Meta · Kakao 광고 · ADN · 모비온 · X Ads

---

## 프로젝트 구조

```
ad_report_downloader/
├── main.py                        # 진입점
├── config_schema.py               # 설정 스키마 · 기본값 · 유효성 검사
├── config.json                    # 사용자 설정 (자동 생성)
├── requirements.txt
│
├── core/
│   ├── orchestrator.py            # QThread 워커 — 매체 순차 실행
│   └── chrome_lock_checker.py     # Chrome 프로필 점유 감지
│
├── downloader/
│   ├── base.py                    # 추상 기반 클래스 (재시도·로그·파일 이동)
│   ├── mock.py                    # 테스트용 가상 다운로더 (Phase 0)
│   ├── naver.py                   # Naver 검색광고 (1차 개발 대상)
│   ├── google.py                  # Google Ads (스텁)
│   ├── meta.py                    # Meta (스텁)
│   ├── kakao.py                   # Kakao 광고 (스텁)
│   ├── adn.py                     # ADN (스텁)
│   ├── mobion.py                  # 모비온 (스텁)
│   └── x_ads.py                   # X Ads (스텁)
│
├── selectors/                     # 매체별 CSS/XPath 셀렉터 (코드 분리)
│   ├── naver.yaml
│   ├── google.yaml
│   ├── meta.yaml
│   ├── kakao.yaml
│   ├── adn.yaml
│   ├── mobion.yaml
│   └── x.yaml
│
├── ui/
│   ├── main_window.py             # 메인 윈도우
│   ├── media_panel.py             # 매체 체크박스 + 상태 아이콘
│   ├── log_panel.py               # 실시간 로그 패널
│   └── settings_dialog.py        # 전역/매체별 설정 다이얼로그
│
├── utils/
│   ├── logger.py                  # 파일 로그 + UI 콜백 연동
│   ├── config_manager.py          # config.json 읽기/쓰기
│   └── file_manager.py            # 파일명 규칙 · 폴더 생성 · 이동
│
└── logs/                          # 실행 로그 · 디버그 스크린샷 (자동 생성)
```

---

## 저장 구조

```
{저장경로}/
└── 20260617/                          ← 실행일 기준
    ├── Naver/
    │   └── naver_raw_20260601_20260617.xlsx
    ├── Google/
    │   └── google_raw_20260601_20260617.xlsx
    ├── Meta/
    ├── Kakao/
    ├── ADN/
    ├── Mobion/
    └── X/
```

파일명 규칙: `{매체코드}_raw_{시작일}_{종료일}.{원본확장자}`

---

## 설치 및 실행

```bash
# 1. 의존성 설치
pip install PySide6 playwright PyYAML

# 2. 실행
python main.py
```

> Chrome 설정이 없으면 자동으로 **테스트 모드(mock)** 로 실행됩니다.

---

## Chrome 프로필 설정

1. Chrome 주소창에 `chrome://version` 입력
2. **프로필 경로** 항목 확인 (예: `C:\Users\User\AppData\Local\Google\Chrome\User Data\Profile 3`)
3. 프로그램 설정(⚙) → Chrome 설정 탭에 입력
   - **User Data 경로:** `C:\Users\User\AppData\Local\Google\Chrome\User Data`
   - **프로필 폴더:** `Profile 3`

---

## 개발 단계

| 단계 | 범위 | 상태 |
|------|------|------|
| 0차 | 공통 골격 (UI · QThread · base.py · mock) | ✅ 완료 |
| 1차 | Naver 검색광고 다차원보고서 | ✅ 완료 |
| 2차 | Google Ads | 🔲 예정 |
| 3차 | Meta | 🔲 예정 |
| 4차 | Kakao 광고 | 🔲 예정 |
| 5차 | ADN | 🔲 예정 |
| 6차 | 모비온 | 🔲 예정 |
| 7차 | X Ads | 🔲 예정 |

---

## 설계 원칙

- **ID/PW 저장 금지** — Chrome 기존 로그인 세션만 재사용
- **Playwright는 QThread에서만 실행** — UI 스레드 블로킹 방지
- **셀렉터 외부화** — `selectors/*.yaml` 수정만으로 UI 변경 대응 (코드 배포 불필요)
- **매체 단위 실패 허용** — 1개 매체 실패 시 나머지 매체 계속 진행
- **headed 모드 강제** — 봇 탐지 리스크 최소화
- **실패 시 자동 진단 자료 저장** — `logs/debug/` 에 스크린샷 + HTML

---

## 신규 매체 추가 방법

1. `downloader/{매체}.py` 생성 — `BaseDownloader` 상속, 4개 메서드 구현 후 `IMPLEMENTED = True`
2. `selectors/{매체}.yaml` 에 실제 셀렉터 입력
3. `config_schema.py` 의 `DEFAULT_CONFIG["media"]` 및 `MEDIA_LABELS`, `MEDIA_ORDER` 에 항목 추가
4. `core/orchestrator.py` 의 `_build_downloader()` 팩토리에 분기 추가

오케스트레이터와 UI는 수정 불필요.
