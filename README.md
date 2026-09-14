# 박사논문 판결문 코딩 워크벤치

> "딥페이크 디지털 성범죄의 양형 결정요인 연구: 사실인정의 불확실성이 사법적
> 판단에 미치는 영향" 박사학위논문 전용 도구.

성폭력처벌법 제14조의2 판결문(약 134건)을 코딩북 v1.1 규칙에 따라 반자동으로
코딩하고, 상대위치·이탈방향 등 파생변수를 자동 계산하여 연구자의 xlsx
코딩시트에 그대로 저장한다. Windows와 macOS 어디에서나 동일하게 동작한다.

---

## 특징

- **판결문 자동 코딩 초안 생성.** PDF/DOCX/TXT 판결문을 넣으면 Claude Opus 5가
  코딩북의 43개 변수를 초안으로 채워준다.
- **규칙 1(추론 제한) · 규칙 2(경합범 처리) 엄격 적용.** 명시 없는 항목은
  -99/9로 결측 처리, 추론한 변수는 자동으로 `inferred_vars`에 기재되며,
  양형기준 관련 변수는 '허위영상물 등의 반포 등' 유형만 코딩된다.
- **파생변수 자동 계산.**
  - `guideline_rel_position`, `area_rel_position`
  - `guideline_deviation` (진정이탈)
  - `deviation_direction` (진정/부진정 × 상향/하향, 임계값 0.15)
  - `appeal_duration`, `law_period`
- **연구자의 기존 xlsx 코딩시트를 그대로 사용.** 컬럼 순서와 이름을 인식하여
  같은 case_id는 덮어쓰고, 저장 시 자동으로 `.bak` 백업이 만들어진다.
- **크로스플랫폼.** Python 표준 라이브러리 Tkinter로 GUI를 만들었기 때문에
  Windows/macOS 모두 별도 GUI 프레임워크 설치가 필요 없다.

---

## 사전 준비

1. **Python 3.10 이상**
   - Windows: <https://www.python.org/downloads/windows/> 에서 설치.
     설치 시 "Add Python to PATH" 체크 필수.
   - macOS: <https://www.python.org/downloads/macos/> 또는 Homebrew (`brew install python@3.12`).
2. **Anthropic API 키** (Claude Opus 5 사용)
   - <https://console.anthropic.com/> 에서 발급.
   - 아래처럼 환경변수로 저장:
     - macOS 터미널:
       ```bash
       export ANTHROPIC_API_KEY="sk-ant-..."
       # 영구 저장하려면 ~/.zshrc 또는 ~/.bash_profile 에 위 줄을 추가
       ```
     - Windows PowerShell (관리자 아님):
       ```powershell
       setx ANTHROPIC_API_KEY "sk-ant-..."
       ```
       이후 **새 PowerShell 창**에서 실행해야 반영된다.
3. **연구자의 코딩시트 xlsx** (v1.1 이상). 없다면 도구가 새로 만들 수도 있으나,
   기존 파일을 사용하는 것을 권장한다.

---

## 실행 방법

### macOS

```bash
cd /path/to/crime
./run.sh
```

처음 실행 시 `.venv/` 가상환경이 생성되고 필요한 패키지가 자동 설치된다.

### Windows

파일 탐색기에서 `run.bat` 더블 클릭, 또는

```cmd
cd C:\path\to\crime
run.bat
```

### 수동 실행 (선택)

```bash
python3 -m venv .venv
source .venv/bin/activate      # Windows는 .venv\Scripts\activate
pip install -r requirements.txt
python -m paper_writer
```

---

## 사용 흐름

1. 앱 실행 후 상단 **"1. 코딩시트 열기"** 로 xlsx 파일 지정.
2. **"2. 판결문 열기"** 로 판결문 파일(.pdf/.docx/.txt) 선택.
3. **"3. AI 코딩 초안 추출"** 클릭 → Claude가 스트리밍으로 답변, 오른쪽 폼이
   자동으로 채워진다. 추론된 변수는 `inferred_vars`에 표시된다.
4. 오른쪽 폼에서 값을 검토·수정한다. 자동계산 필드(rel_position, deviation
   direction 등)는 저장 시 다시 계산된다.
5. **"4. 저장"** 클릭 → xlsx에 upsert 되고 `.bak` 백업 파일이 함께 생성된다.

---

## 파일 구조

```
crime/
├── README.md                 # 이 파일
├── requirements.txt          # 파이썬 의존성
├── run.sh                    # macOS/Linux 실행 스크립트
├── run.bat                   # Windows 실행 스크립트
├── .gitignore
├── docs/
│   └── proposal.md           # 연구계획서 마크다운 사본 (Claude 컨텍스트)
├── data/                     # (사용자의 xlsx를 여기 두는 것을 권장)
└── paper_writer/
    ├── __init__.py
    ├── __main__.py           # `python -m paper_writer` 진입점
    ├── app.py                # Tkinter GUI
    ├── codebook.py           # 코딩북 v1.1 (기계 판독 정의)
    ├── analyzer.py           # rel_position, deviation_direction, law_period
    ├── extractor.py          # Claude API 추출기
    ├── pdf_reader.py         # PDF/DOCX/TXT → 텍스트
    └── xlsx_io.py            # 코딩시트 read/upsert/save
```

---

## 이 도구가 하지 않는 것

- **통계 분석 자체는 수행하지 않는다.** OLS, 순서형 로짓, 분수회귀, Cox 회귀
  등은 R/Stata/Python에서 별도로 수행한다. 이 도구는 그 입력이 되는
  **깨끗한 코딩시트**를 만드는 역할까지 한다.
- **판결문 원문 수집을 대신하지 않는다.** 로앤비/케이스노트 등에서 판결문을
  받아오는 부분은 연구자가 수동으로 수행한다.
- **코더 간 신뢰도 검증은 수동으로 수행한다.** 도구는 `coder_id` 값을 기록만
  하며, 향후 버전에서 이중코딩/κ 산출 지원을 검토한다.

---

## 알려진 제약

- Claude 응답이 코딩북 규칙을 위반할 수 있으므로 **저장 전 반드시 검토**한다.
- 판결문이 스캔 PDF(이미지)일 경우 pypdf가 텍스트를 뽑지 못한다. OCR을 별도로
  거쳐야 한다.
- 판결문 텍스트가 20만 자를 초과하면 앞부분만 전달된다 (`extractor.py` 상수로
  조정 가능).

---

## 개발 참고

로컬 개발용 검증은 실제 API 호출 없이도 코딩북·분석기 계층에서 수행할 수 있다.

```bash
python -c "from paper_writer import codebook, analyzer, xlsx_io; print('OK')"
```

Anthropic API 호출은 Claude Opus 5(`claude-opus-5`) + adaptive thinking +
스트리밍으로 이루어지며, 코딩북 v1.1의 두 규칙이 시스템 프롬프트에 내장되어
있다.
