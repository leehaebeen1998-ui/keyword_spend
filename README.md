# 키워드별 소진내역 가공 프로그램

브랜드별 광고 raw 파일을 규칙에 따라 분류하고, 키워드별 소진내역 템플릿에 자동 반영하는 Windows용 도구입니다.

## 주요 기능

- 브랜드별 설정 관리
- 브랜드 추가 및 규칙 CSV 편집
- 다운로드 폴더 raw 파일 자동 탐색
- raw 파일이 없을 때 다운로더 자동 호출
- 실행 기준일 기준 전일 데이터 처리
- 월요일 금/토/일 보정 처리
- 비용 0 행 제외
- 비용 내림차순 정렬
- 중복 제거
- 값이 없는 시트의 기존 잔여 데이터 삭제
- `.xlsx`, `.xlsb` 템플릿 반영

## 기본 실행

개발 환경에서 실행:

```powershell
python -B upload_processor_gui.py
```

패키지 배포본에서는:

```text
설치.bat
실행.bat
```

## 외부 봇 연결

프로그램은 로그인 봇/다운로더를 직접 수정하지 않고, 명령 호출 방식으로 연결합니다.

예시:

```text
로그인 명령:   C:\report-downloader\로그인.bat
다운로더 명령: C:\report-downloader\run.bat
```

## 날짜 기준

- 화~금 실행: 전일 데이터
- 월요일 실행: 금/토/일 데이터
- 공휴일/특수 기간: 수동 기간 입력

## 규칙 파일

기본 규칙 예시:

```text
examples/brand-upload-rules.example.csv
```

규칙 편집 GUI:

```powershell
python -B upload_rule_editor_gui.py examples\brand-upload-rules.example.csv
```

## 배포 원칙

규칙과 설정은 열어두고, 실행 엔진은 패키지로 묶어 배포합니다.

GitHub 저장소에는 소스와 패키징 스크립트만 보관합니다. 내장 Python이 포함된 ZIP 배포본은 GitHub Releases에 첨부합니다.
