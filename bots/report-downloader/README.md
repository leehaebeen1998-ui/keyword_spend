# 광고 보고서 자동 다운로더

광고 매체(네이버·구글·메타·카카오·ADN·모비온·X)의 보고서 로우 데이터를 설정한 기간 기준으로 자동 다운로드하는 Windows 데스크탑 프로그램입니다.

## 주요 기능

- **8개 매체 지원**: Naver 검색광고 / Google Ads / Meta Ads / Kakao 키워드광고 / ADN / 모비온(배너·일자별) / X(Twitter) Ads
- **다중 계정**: 매체당 여러 계정을 순차 실행 (Naver 5개, ADN 10개, 모비온 15개 등)
- **Chrome 세션 재사용**: 전용 Chrome 프로필(`chrome_profile/`)에 1회 로그인 후 자동 세션 유지
- **ID/PW 저장 없음**: 코드·파일에 비밀번호를 일절 저장하지 않음 (Chrome Password Manager 활용)
- **PySide6 GUI**: 매체 선택, 기간 설정, 실행 로그, 진행률 표시

## 프로젝트 구조

```
report-downloader/
├── run.bat                          # 실행 진입점
├── 로그인.bat                        # 최초 1회 Chrome 프로필 로그인
├── login_chrome.py                  # 로그인 스크립트
├── README.md
├── todo.md
├── docs/
│   └── process.md                   # 프로그램 로직 상세
└── ad_report_downloader/
    ├── main.py                      # 앱 진입점
    ├── config.json                  # 사용자 설정 (계정 정보)
    ├── config_schema.py             # 기본값, 유효성 검사
    ├── chrome_profile/              # Chrome 전용 프로필 (로그인 세션)
    ├── core/
    │   ├── orchestrator.py          # QThread 워커 — Chrome 실행 + 순차 다운로드
    │   └── chrome_lock_checker.py   # Chrome 프로세스 관리
    ├── downloader/
    │   ├── base.py                  # 추상 베이스 클래스
    │   ├── naver.py                 # Naver 검색광고
    │   ├── google.py                # Google Ads
    │   ├── meta.py                  # Meta Ads
    │   ├── kakao.py                 # Kakao 키워드광고
    │   ├── adn.py                   # ADN
    │   ├── mobion_base.py           # 모비온 공통
    │   ├── mobion_banner.py         # 모비온 통합배너
    │   ├── mobion_daily.py          # 모비온 일자별
    │   └── x_ads.py                 # X(Twitter) Ads
    ├── selectors/                   # 매체별 CSS 셀렉터 YAML
    │   ├── naver.yaml
    │   ├── google.yaml
    │   ├── meta.yaml
    │   ├── kakao.yaml
    │   ├── adn.yaml
    │   ├── mobion_banner.yaml
    │   ├── mobion_daily.yaml
    │   └── x.yaml
    └── ui/
        ├── main_window.py
        ├── media_panel.py
        ├── settings_dialog.py
        └── log_panel.py
```

## 설치 방법

### 필수 조건

- Windows 10/11
- Python 3.11+
- Google Chrome 설치

### 의존성 설치

```bash
pip install playwright pyside6 pyyaml
playwright install chromium
```

### 최초 실행 (로그인)

```bash
로그인.bat
```

Chrome이 열리면 각 광고 매체에 로그인합니다. 완료 후 Enter를 누르면 세션이 저장됩니다.

### 실행

```bash
run.bat
```

## 설정 (config.json)

```json
{
  "chrome": {
    "profile_directory": "Default"
  },
  "save_root_path": "C:/Users/.../보고서",
  "media": {
    "naver": {
      "enabled": true,
      "accounts": [
        {
          "account_name": "계정명",
          "account_id": "1234567",
          "report_name": "보고서이름"
        }
      ]
    },
    "google": { "enabled": false, "accounts": [] },
    "meta":   { "enabled": false, "accounts": [] }
  }
}
```

## 보안 정책

- **ID/PW 저장 금지**: 코드 또는 설정 파일에 비밀번호를 저장하지 않습니다.
- **Chrome 세션만 사용**: 로그인 세션 쿠키를 Chrome 프로필에 보관합니다.
- **모비온 비밀번호**: Chrome Password Manager 자동 완성만 사용합니다.

## 라이선스

Private — 사내 사용 전용
