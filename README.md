# 박사논문 워크벤치

> "딥페이크 디지털 성범죄의 양형 결정요인 연구: 사실인정의 불확실성이 사법적
> 판단에 미치는 영향" 박사학위논문 전용 도구.

**세 가지를 하나의 앱에서 처리한다:**

1. **판결문 코딩** — 판결문(PDF/DOCX/TXT)을 넣으면 Claude Opus 5가 코딩북
   v1.1 규칙에 따라 46개 변수를 초안으로 추출. `rel_position`,
   `deviation_direction` 등 파생변수는 자동 계산. 사용자의 기존 xlsx 코딩시트에
   그대로 upsert (.bak 자동 백업).
2. **자료 라이브러리 (NotebookLM 스타일)** — 선행연구·판례·법조문·통계보고서
   PDF/DOCX를 프로젝트 폴더에 축적. 검색·태그·인용 관리. 400페이지 학위논문의
   근거자료 저장소.
3. **논문 섹션 초안** — 28개 표준 섹션(초록·서론·이론·방법·결과·논의·결론·
   참고문헌; A4 예상 354쪽) 별로 Claude가 초안 작성. **자료 라이브러리 안의
   내용만을 근거로**, [출처 필요] · 국문 학술 인용 규칙을 지키며 서술.

Windows와 macOS 모두 별도 GUI 프레임워크 없이(Tkinter 표준 라이브러리) 동일하게
동작한다.

---

## 특징

### 판결문 코딩
- Claude Opus 5 (adaptive thinking, streaming)로 표 4의 46개 변수 자동 초안 추출
- 규칙 1(추론 제한) · 규칙 2(경합범 처리) 시스템 프롬프트에 내장
- 파생변수 자동 계산: `guideline_rel_position`, `area_rel_position`,
  `guideline_deviation`, `deviation_direction`(임계값 0.15), `appeal_duration`,
  `law_period`
- 기존 xlsx 코딩시트의 컬럼 순서를 자동 인식해 upsert. 저장 시 `.bak` 백업

### 자료 라이브러리 (NotebookLM 스타일)
- 자료(선행연구·판례·법조문·통계보고서·이론서·기타) 등록 시 PDF/DOCX 텍스트를
  자동 추출해 검색 가능하게 인덱싱
- 인용 형식 관리 — 본문용(예: 조혜민(2025))과 참고문헌용 서지정보를 각각 저장
- 태그·종류·연도·저자 검색
- 지금까지 등록된 자료의 참고문헌 목록을 `references.md`로 자동 export

### 노트북 QA
- 사용자가 등록한 자료 안에서만 답변 — 없는 사실은 만들어내지 않는다
- 답변에 근거 자료 ID를 [조혜민-2025] 형식으로 인용
- 대화 히스토리 저장 (프로젝트 폴더 안의 `conversations/`)
- 특정 자료 pin 가능 (반드시 참조하도록 지시)
- 주제 브리핑 문서 자동 생성

### 섹션 초안
- 28개 표준 섹션 (A4 예상 354쪽) — 사용자 편집 가능
- 각 섹션 초안 생성 시 자동 컨텍스트: (i) 연구계획서 전문 (ii) 이 섹션의
  guidance + 연구자 노트 (iii) 관련 자료 발췌 (iv) 결과 섹션이면 코딩시트
  기술통계 요약 (v) 이미 확정된 다른 섹션의 발췌 (일관성 유지)
- 초안 → 수정 지시 반영 반복. 매 저장마다 자동 버전 관리
- 전체 섹션을 이어붙여 `draft_paper.md` 한 파일로 export

---

## 사전 준비

1. **Python 3.10 이상**
2. **Anthropic API 키** — `ANTHROPIC_API_KEY` 환경변수로 설정
   - Windows PowerShell: `setx ANTHROPIC_API_KEY "sk-ant-..."` (새 창에서 실행)
   - macOS 터미널: `export ANTHROPIC_API_KEY="sk-ant-..."`
3. **연구자의 코딩시트 xlsx** (선택 — 코딩·결과 섹션에서 사용)

---

## 실행

### GUI로 실행 (Windows/macOS 공통)

```bash
# macOS
./run.sh

# Windows
run.bat
```

처음 실행 시 `.venv/`가 만들어지고 의존성이 자동 설치된다.

### CLI로 실행 (배치·자동화용)

```bash
# 프로젝트 만들기
python -m paper_writer.paper_cli init ./thesis_project --title "박사학위논문"

# 연구계획서 참고문헌 시드 (10건 자동 등록)
python -m paper_writer.paper_cli library seed ./thesis_project

# 자료 등록 (PDF 원본과 함께)
python -m paper_writer.paper_cli library add ./thesis_project \
    --id 판례-제주2023고합220 --kind 판례 \
    --title "제주지방법원 2023고합220 판결" \
    --authors "제주지방법원" --year 2023 \
    --citation "제주지방법원 2023고합220" \
    --tags "합성정교함,양형이유,딥페이크" \
    --file /path/to/judgment.pdf

# 자료 목록 / 검색
python -m paper_writer.paper_cli library list ./thesis_project

# 코딩시트 → 기술통계 마크다운
python -m paper_writer.paper_cli stats ./data/coding_sheet.xlsx --out ./results.md

# 섹션 초안 생성 (스트리밍)
python -m paper_writer.paper_cli draft ./thesis_project 04_이론_사실인정불확실성 --stream

# 결과 섹션 (코딩시트 통계 자동 포함)
python -m paper_writer.paper_cli draft ./thesis_project 16_결과_기술통계 \
    --xlsx ./data/coding_sheet.xlsx --stream

# 기존 초안 다듬기
python -m paper_writer.paper_cli revise ./thesis_project 04_이론_사실인정불확실성 \
    "제주2023고합220 판결의 양형이유 부분을 좀 더 상세히 인용해 주세요" --stream

# NotebookLM 스타일 QA (자료 안에서만 답변)
python -m paper_writer.paper_cli ask ./thesis_project \
    "한민경(2024)과 조혜민(2025)의 표본 구성 차이를 정리해줘" --stream

# 특정 자료 pin해서 질문
python -m paper_writer.paper_cli ask ./thesis_project \
    "이 판례의 양형이유 요약해줘" --pin 판례-제주2023고합220 --stream

# 주제 브리핑
python -m paper_writer.paper_cli briefing ./thesis_project "부진정 하향이탈의 조작화" --stream

# 지금까지 확정된 섹션을 한 파일로
python -m paper_writer.paper_cli compile ./thesis_project
```

---

## 프로젝트 폴더 구조

CLI/GUI가 만들고 관리하는 프로젝트 폴더:

```
thesis_project/
├── project.json                     — 섹션 목차 + 상태
├── library.db                       — 자료 인덱스 (SQLite)
├── sources/                         — 원본 파일 사본
│   ├── 조혜민-2025.pdf
│   ├── 판례-제주2023고합220.pdf
│   └── ...
├── sections/                        — 각 섹션 초안 (마크다운)
│   ├── 01_서론_문제제기.md
│   ├── 01_서론_문제제기.versions/   — 자동 버전 백업
│   │   ├── v001_2026-09-14T10-15.md
│   │   └── v002_2026-09-14T14-02.md
│   ├── 04_이론_사실인정불확실성.md
│   └── ...
├── conversations/                   — 노트북 QA 대화 히스토리
│   └── default.json
├── draft_paper.md                   — 전체 이어붙인 논문 초안
└── references.md                    — 참고문헌 자동 목록
```

---

## 파일 구조 (프로그램)

```
crime/
├── README.md                 이 파일
├── requirements.txt
├── run.sh / run.bat          Windows/macOS 실행 스크립트
└── paper_writer/
    ├── __main__.py           `python -m paper_writer` → GUI
    ├── app.py                Tkinter GUI (4개 탭)
    ├── paper_cli.py          CLI 진입점
    ├── codebook.py           코딩북 v1.1 (46개 필드)
    ├── analyzer.py           파생변수 자동 계산
    ├── extractor.py          Claude로 판결문 → 코딩 초안
    ├── xlsx_io.py            코딩시트 read/upsert
    ├── pdf_reader.py         PDF/DOCX/TXT → 텍스트
    ├── library.py            자료 라이브러리 (SQLite)
    ├── notebook.py           NotebookLM 스타일 QA · 브리핑
    ├── data_summary.py       코딩시트 → 기초 기술통계
    ├── writing_project.py    프로젝트 상태 + 섹션 관리
    └── drafter.py            섹션 초안 생성기
```

---

## 이 도구가 하는 것 / 하지 않는 것

**하는 것**
- 판결문 코딩 워크플로우 반자동화
- 선행연구·판례·법조문 자료 축적과 검색
- 축적된 자료에 근거한 대화형 QA와 논문 섹션 초안 작성
- 파생변수 자동 계산과 기초 기술통계
- 참고문헌 자동 관리

**하지 않는 것**
- **본격적인 회귀분석**은 R/Stata/Python(statsmodels)에서. 이 도구는 그 입력이
  되는 깨끗한 xlsx와 결과를 서술할 컨텍스트를 제공.
- **판결문 수집**은 연구자가 로앤비/케이스노트 등에서 직접.
- **AI가 논문을 대신 써주지 않는다.** 각 섹션 초안은 실제로는 자료 안의 근거
  기반이며, 부족한 자리는 [출처 필요]로 남겨 연구자가 채운다.
- **자료에 없는 내용은 만들어내지 않는다** — 시스템 프롬프트로 엄격히 강제.

---

## 알려진 제약

- 스캔 PDF(이미지)는 pypdf가 텍스트를 뽑지 못함 → OCR 별도 필요
- 판결문 텍스트 20만 자 초과 시 앞부분만 전달 (상수로 조정 가능)
- 노트북 QA는 자료 발췌를 매 턴 컨텍스트에 재조립 — 자료가 매우 많으면 관련도
  높은 상위 8개만 사용
- Claude 응답이 시스템 프롬프트를 위반할 가능성 → **저장 전 반드시 검토**

---

## 개발용 로컬 검증

```bash
python3 -c "from paper_writer import codebook, analyzer, library, notebook, drafter; print('OK')"
```

Anthropic API 호출은 Claude Opus 5 (adaptive thinking, streaming) 기준.
