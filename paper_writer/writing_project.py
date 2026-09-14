"""논문 프로젝트 상태 관리 — 섹션 구조와 각 섹션의 초안·버전.

프로젝트 폴더 구조:
  <project>/
    project.json          — 프로젝트 메타 (제목, 목차, 최근 편집)
    library.db            — Library가 사용
    sources/              — Library가 사용
    sections/
      01_서론_문제제기.md         — 현재 확정본
      01_서론_문제제기.versions/  — 이전 버전들
        v001_2026-09-14T10-15.md
        v002_2026-09-14T14-02.md
      02_서론_연구목적.md
      ...
    references.md         — 참고문헌 목록 (Library에서 export)
    draft_paper.md        — 전체 섹션 이어붙인 최종 초안
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


# 박사학위논문 표준 구조 — 사용자가 project.json에서 자유롭게 수정 가능
DEFAULT_OUTLINE: list[dict] = [
    {"key": "abstract", "title": "초록",
     "guidance": "본 연구의 배경·목적·자료·방법·핵심발견·기여를 A4 1쪽 분량으로 압축. "
                 "결과 수치를 인용하되 해석은 최소화.",
     "estimated_pages": 2},

    {"key": "01_서론_문제제기", "title": "I. 서론 - 1. 문제제기",
     "guidance": "딥페이크 디지털 성범죄가 최근 사회문제로 대두된 배경, "
                 "입법 대응(2024.9 개정)의 흐름, 그러나 사법현장에서의 실증 검증이 "
                 "부족하다는 연구공백을 지적. 마지막 문단에서 본 연구가 이 공백을 "
                 "어떻게 채우는지 예고.",
     "estimated_pages": 8},
    {"key": "02_서론_연구목적", "title": "I. 서론 - 2. 연구목적 및 연구질문",
     "guidance": "연구질문 1(사실인정의 불확실성 → 양형), 2(부진정 하향이탈), "
                 "보조 1·2를 명료히 제시. 각 질문의 이론적·정책적 필요성을 짧게 부연.",
     "estimated_pages": 4},
    {"key": "03_서론_연구의의", "title": "I. 서론 - 3. 연구의 의의",
     "guidance": "학술적·방법론적·정책적 의의 세 층위로 구분해 서술. "
                 "부진정 하향이탈의 계량화라는 방법론적 기여를 강조.",
     "estimated_pages": 4},

    {"key": "04_이론_사실인정불확실성", "title": "II. 이론적 배경 - 1. 사실인정의 불확실성 가설",
     "guidance": "Albonetti(1991)의 불확실성 회피이론을 딥페이크 맥락에 어떻게 "
                 "재개념화하는지 상세 논증. 실촬영물 대비 매체 진위 판단이 추가된다는 점. "
                 "한민경(2024)의 아헤가오 사건, 제주2023고합220의 양형이유를 근거로.",
     "estimated_pages": 20},
    {"key": "05_이론_초점관심", "title": "II. 이론적 배경 - 2. 통제 프레임 1: 초점관심이론",
     "guidance": "Steffensmeier, Ulmer, Kramer(1998). 비난가능성·지역사회보호·실질적제약 "
                 "세 관심. 본 연구에서는 가해자 특성이 어떻게 통제변수로 작동하는지.",
     "estimated_pages": 12},
    {"key": "06_이론_불확실성회피", "title": "II. 이론적 배경 - 3. 통제 프레임 2: 불확실성 회피이론",
     "guidance": "Albonetti(1991)의 일반 개념 vs 본 연구의 '사실인정의 불확실성' 특수형. "
                 "왜 이것이 별개의 하위유형인지, 어떤 변수로 조작화하는지.",
     "estimated_pages": 12},
    {"key": "07_이론_통제균형", "title": "II. 이론적 배경 - 4. 통제 프레임 3: 통제균형이론",
     "guidance": "Tittle(1995), 김중곤(2024)의 DFSA 적용 사례. 본 연구에서는 "
                 "relationship_power_dynamic으로 조작화.",
     "estimated_pages": 10},
    {"key": "08_이론_선행연구", "title": "II. 이론적 배경 - 5. 국내 선행연구 검토",
     "guidance": "배상균(2025), 조혜민(2025), 한민경(2024), 김중곤(2024), 김한균(2014)을 "
                 "각각 다룬 것 / 본 연구와의 차이 / 본 연구가 참고한 방법론적 요소로 구조화.",
     "estimated_pages": 25},
    {"key": "09_이론_연구공백", "title": "II. 이론적 배경 - 6. 연구 공백 및 본 연구의 기여",
     "guidance": "세 층위의 차별화(가설·이론구조·변수지위 구분). "
                 "표로 정리하면 좋음.",
     "estimated_pages": 6},

    {"key": "10_방법_자료", "title": "III. 연구방법 - 1. 자료",
     "guidance": "성폭력처벌법 제14조의2, 로앤비 참조조문 검색 약 134건. "
                 "설계 변경(처리기간→양형)의 근거를 반드시 상세히.",
     "estimated_pages": 10},
    {"key": "11_방법_양형기준이탈", "title": "III. 연구방법 - 2. 양형기준 이탈 분석 설계",
     "guidance": "김한균(2014)의 진정/부진정 개념, 상대위치의 조작적 정의(0.15 임계), "
                 "전체범위·영역 기준의 강건성 확인.",
     "estimated_pages": 12},
    {"key": "12_방법_검색전략", "title": "III. 연구방법 - 3. 검색 전략과 제외 기준",
     "guidance": "로앤비 참조조문 + 케이스노트 교차검증. 제외 기준 5가지. "
                 "표로 정리.",
     "estimated_pages": 8},
    {"key": "13_방법_변수", "title": "III. 연구방법 - 4. 변수 정의",
     "guidance": "코딩북 v1.1 46개 변수를 카테고리별로 서술. 확정변수와 가설변수 구분. "
                 "규칙 1(추론 제한), 규칙 2(경합범 처리) 명시.",
     "estimated_pages": 30},
    {"key": "14_방법_파일럿", "title": "III. 연구방법 - 5. 파일럿 코딩 절차 및 결과",
     "guidance": "4단계 절차. 파일럿 15건의 결과 3가지 확인(기재율 33.3%, 경합범, "
                 "항소심 정보제약)과 그 설계 함의.",
     "estimated_pages": 12},
    {"key": "15_방법_분석기법", "title": "III. 연구방법 - 6. 분석기법",
     "guidance": "OLS, 순서형 로짓, 분수회귀/베타회귀, Cox 회귀. 각 기법의 선택 근거. "
                 "모형진단, 코더 간 신뢰도(κ).",
     "estimated_pages": 15},

    {"key": "16_결과_기술통계", "title": "IV. 분석결과 - 1. 기술통계",
     "guidance": "표본 특성. 형종·형량 분포. 자동 생성된 data_summary 결과를 서술로 풀어냄. "
                 "표 여러 개 필요.",
     "estimated_pages": 20, "needs_data": True},
    {"key": "17_결과_주분석1", "title": "IV. 분석결과 - 2. 주분석 1: 양형 결정요인 (OLS + 순서형 로짓)",
     "guidance": "선고형량 OLS, 형종 순서형 로짓. 사실인정의 불확실성 관련 변수의 "
                 "계수·유의도 서술. 통제변수와의 상대적 크기 비교.",
     "estimated_pages": 25, "needs_data": True},
    {"key": "18_결과_주분석2", "title": "IV. 분석결과 - 3. 주분석 2: 양형기준 이탈 (로짓 + 분수회귀)",
     "guidance": "진정이탈, 부진정 하향이탈 로짓. rel_position 분수회귀. "
                 "임계값 민감도 분석.",
     "estimated_pages": 20, "needs_data": True},
    {"key": "19_결과_보조분석", "title": "IV. 분석결과 - 4. 보조 분석 (Cox 회귀)",
     "guidance": "항소심 표본 상소심 소요기간 Cox 회귀. Schoenfeld 잔차 진단.",
     "estimated_pages": 10, "needs_data": True},
    {"key": "20_결과_강건성", "title": "IV. 분석결과 - 5. 강건성 확인",
     "guidance": "임계값 변경, 단일죄 사건 한정, 영향력 사례 진단.",
     "estimated_pages": 10, "needs_data": True},

    {"key": "21_논의_결과해석", "title": "V. 논의 - 1. 결과 해석",
     "guidance": "각 핵심 발견을 사실인정의 불확실성 가설과 대조. 이론 예측과 부합/불부합.",
     "estimated_pages": 20, "needs_data": True},
    {"key": "22_논의_이론적함의", "title": "V. 논의 - 2. 이론적 함의",
     "guidance": "Albonetti(1991) 이론의 확장, 김한균(2014) 부진정이탈 개념의 계량화 성과.",
     "estimated_pages": 12},
    {"key": "23_논의_정책적함의", "title": "V. 논의 - 3. 정책적 함의",
     "guidance": "합성 정교함 감안 양형 관행 재검토, 디지털포렌식 감정 역량 확충. "
                 "양형위원회에 대한 제언.",
     "estimated_pages": 12},

    {"key": "24_결론_요약", "title": "VI. 결론 - 1. 연구 요약",
     "guidance": "연구질문별 발견 요약.",
     "estimated_pages": 6},
    {"key": "25_결론_한계", "title": "VI. 결론 - 2. 연구의 한계",
     "guidance": "판결문 자료의 선택편향, 공소제기일 미기재, 결측, 표본 규모, "
                 "양형기준 미기재율, 경합범 형량 분리.",
     "estimated_pages": 8},
    {"key": "26_결론_후속연구", "title": "VI. 결론 - 3. 후속 연구 제언",
     "guidance": "실촬영물 대조 설계, 검사 구형 자료 접근, 판사 심층 인터뷰 등.",
     "estimated_pages": 6},

    {"key": "99_참고문헌", "title": "VII. 참고문헌",
     "guidance": "Library에서 자동 생성.",
     "estimated_pages": 15},
]


@dataclass
class Section:
    key: str
    title: str
    guidance: str = ""
    estimated_pages: int = 5
    needs_data: bool = False
    notes: str = ""       # 연구자 노트 (초안 생성 시 함께 반영)
    status: str = "미착수" # "미착수" | "초안" | "수정중" | "확정"


@dataclass
class Project:
    dir: Path
    title: str
    sections: list[Section] = field(default_factory=list)
    updated_at: str = ""

    @property
    def sections_dir(self) -> Path:
        return self.dir / "sections"

    @property
    def json_path(self) -> Path:
        return self.dir / "project.json"


def _sanitize_key(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9_가-힣.-]+", "_", key)


def load_or_create(project_dir: str | Path,
                   title: str = "박사학위논문 (제목 미정)") -> Project:
    d = Path(project_dir)
    d.mkdir(parents=True, exist_ok=True)
    (d / "sections").mkdir(exist_ok=True)

    jp = d / "project.json"
    if jp.exists():
        data = json.loads(jp.read_text(encoding="utf-8"))
        sections = [Section(**s) for s in data.get("sections", [])]
        return Project(dir=d, title=data.get("title", title),
                       sections=sections, updated_at=data.get("updated_at", ""))

    sections = [Section(**dict(s)) for s in DEFAULT_OUTLINE]
    proj = Project(dir=d, title=title, sections=sections)
    save(proj)
    return proj


def save(project: Project) -> None:
    project.updated_at = datetime.now().isoformat(timespec="seconds")
    data = {
        "title": project.title,
        "updated_at": project.updated_at,
        "sections": [asdict(s) for s in project.sections],
    }
    project.json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def section_by_key(project: Project, key: str) -> Section:
    for s in project.sections:
        if s.key == key:
            return s
    raise KeyError(f"섹션을 찾을 수 없습니다: {key}")


def section_file(project: Project, section: Section) -> Path:
    return project.sections_dir / f"{_sanitize_key(section.key)}.md"


def versions_dir(project: Project, section: Section) -> Path:
    p = project.sections_dir / f"{_sanitize_key(section.key)}.versions"
    p.mkdir(exist_ok=True, parents=True)
    return p


def read_section(project: Project, key: str) -> str:
    section = section_by_key(project, key)
    fp = section_file(project, section)
    return fp.read_text(encoding="utf-8") if fp.exists() else ""


def write_section(project: Project, key: str, content: str,
                  version: bool = True) -> Path:
    section = section_by_key(project, key)
    fp = section_file(project, section)
    if version and fp.exists():
        vdir = versions_dir(project, section)
        stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        n = len(list(vdir.glob("v*.md"))) + 1
        shutil.copy2(fp, vdir / f"v{n:03d}_{stamp}.md")
    fp.write_text(content, encoding="utf-8")
    if section.status == "미착수":
        section.status = "초안"
    save(project)
    return fp


def list_versions(project: Project, key: str) -> list[Path]:
    section = section_by_key(project, key)
    return sorted(versions_dir(project, section).glob("v*.md"))


def compile_full_draft(project: Project) -> Path:
    """모든 섹션을 순서대로 이어붙여 draft_paper.md 생성."""
    parts: list[str] = [f"# {project.title}\n"]
    for s in project.sections:
        fp = section_file(project, s)
        if fp.exists():
            body = fp.read_text(encoding="utf-8").strip()
            parts.append(f"\n\n## {s.title}\n\n{body}")
        else:
            parts.append(f"\n\n## {s.title}\n\n_(미작성)_")
    out = project.dir / "draft_paper.md"
    out.write_text("\n".join(parts), encoding="utf-8")
    return out


def compile_references(project: Project, refs: list[str]) -> Path:
    lines = ["# 참고문헌\n"]
    for r in refs:
        lines.append(f"- {r}")
    out = project.dir / "references.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
