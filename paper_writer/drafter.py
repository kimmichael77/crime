"""섹션 초안 생성기 — Claude Opus 5.

한 섹션의 초안을 만들 때 다음을 자동으로 컨텍스트에 넣는다:
  1. 연구계획서 전문 (docs/proposal.md, 존재 시)
  2. 이 섹션의 guidance + 연구자 노트
  3. 관련 자료(Library)에서 검색된 선행연구·판례 발췌
  4. 결과 섹션이면 코딩시트 기술통계 요약
  5. 이미 확정된 다른 섹션의 요약 (일관성 유지)

원칙:
  - 자료에 없는 사실은 만들어내지 말 것 → 시스템 프롬프트로 강제
  - 인용은 (조혜민, 2025) 같은 국문 학술 형식
  - 판결문 인용은 "제주지방법원 2023고합220 판결" 식으로 정확히
  - 부족한 자리는 [출처 필요] / [코딩 결과 필요] 표시
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Iterable, Optional

import anthropic

from .library import Library, Source
from .writing_project import (
    Project, Section, section_by_key, read_section,
    write_section, section_file,
)


MODEL = "claude-opus-5"


SYSTEM_PROMPT = """\
당신은 한국 형사법학 · 범죄학 박사학위논문 초안을 작성하는 조교이다.
논문 주제는 "딥페이크 디지털 성범죄의 양형 결정요인 연구: 사실인정의
불확실성이 사법적 판단에 미치는 영향"이며, 연구계획서에 정의된 이론적
개념과 방법론을 그대로 사용한다.

작성 원칙 (엄격 준수):

1. 사실 근거의 제한
   - 컨텍스트로 주어진 자료(연구계획서, 선행연구 발췌, 판례, 코딩 결과)에
     명시된 사실만 사용한다.
   - 확인되지 않은 통계 수치, 판례 인용, 저자·연도는 절대 만들어내지 않는다.
   - 필요한 자리에는 "[출처 필요]" 또는 "[코딩 결과 필요]"라고 명시적으로
     표시하여 연구자가 채워넣을 수 있게 한다.

2. 학술적 문체
   - 서술체(-이다/-된다). 구어체·이모지·불필요한 강조 표시 금지.
   - 문단은 명확한 주제문으로 시작하고, 뒷받침 문장·근거·소결 순서로 전개.
   - 각 문단은 4~8문장, 문장은 대체로 40~80자.

3. 인용 형식
   - 국문 저자: (조혜민, 2025), (한민경, 2024), (김한균, 2014)
   - 영문 저자: (Albonetti, 1991), (Steffensmeier et al., 1998)
   - 판례: "제주지방법원 2023. 5. 12. 선고 2023고합220 판결" (판결문에 나온 그대로)
   - 법조문: "성폭력범죄의 처벌 등에 관한 특례법 제14조의2 제1항"

4. 논문의 이론적 축을 흐트리지 말 것
   - '사실인정의 불확실성(uncertainty in fact-finding)'이 핵심 가설이다.
   - 초점관심 / 불확실성 회피 / 통제균형 이론은 통제 프레임이지 병렬 나열이 아니다.
   - '진정이탈'과 '부진정이탈'은 김한균(2014)의 개념이며, 부진정 하향이탈의
     조작적 정의는 rel_position ≤ 0.15이다.

5. 분량 감각
   - 요청된 섹션의 estimated_pages를 참고해 A4 기준 그 분량에 맞게 서술.
   - 억지로 늘리지 말고, 자료가 부족하면 [출처 필요]로 남길 것.

출력은 마크다운 하나로만. 코드블록으로 감싸지 말 것.
"""


def _client() -> anthropic.Anthropic:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY 환경변수가 설정되어 있지 않습니다."
        )
    return anthropic.Anthropic()


def _load_proposal(project: Project) -> str:
    """docs/proposal.md 가 있으면 읽어 온다 (프로젝트 폴더 상위나 프로젝트 폴더 내부)."""
    candidates = [
        project.dir / "docs" / "proposal.md",
        project.dir.parent / "docs" / "proposal.md",
        Path.cwd() / "docs" / "proposal.md",
    ]
    for c in candidates:
        if c.exists():
            return c.read_text(encoding="utf-8")
    return ""


def _related_sources(lib: Library, section: Section,
                     limit: int = 6) -> list[Source]:
    """섹션 제목과 guidance에서 키워드를 뽑아 관련 자료를 검색."""
    query_terms = section.title + " " + section.guidance
    query_terms = query_terms.replace("I.", "").replace("II.", "").replace("III.", "")
    query_terms = query_terms.replace("IV.", "").replace("V.", "").replace("VI.", "")
    # 짧은 조사·접속사 제거
    stopwords = {"및", "의", "을", "를", "이", "가", "은", "는", "에",
                 "의한", "따른", "그리고", "또한", "본", "연구"}
    words = [w for w in query_terms.split() if len(w) > 1 and w not in stopwords]
    query = " ".join(words[:8])
    return lib.search(query=query, limit=limit)


def _previous_sections_digest(project: Project,
                              current_key: str,
                              max_chars: int = 3000) -> str:
    """이미 확정된 다른 섹션의 발췌를 이어붙여 일관성 컨텍스트로 제공."""
    parts: list[str] = []
    for s in project.sections:
        if s.key == current_key:
            break
        body = read_section(project, s.key).strip()
        if not body:
            continue
        head = body[:600]
        parts.append(f"### {s.title}\n{head}\n...")
    joined = "\n\n".join(parts)
    if len(joined) > max_chars:
        joined = joined[-max_chars:]
    return joined


def build_context(project: Project, lib: Library, section: Section,
                  data_summary_md: str = "",
                  extra_instructions: str = "") -> str:
    parts: list[str] = []
    proposal = _load_proposal(project)
    if proposal:
        parts.append("## 연구계획서 (전문)\n\n" + proposal)

    parts.append("## 이번에 작성할 섹션\n")
    parts.append(f"- 제목: **{section.title}**")
    parts.append(f"- 예상 분량: A4 약 {section.estimated_pages}쪽")
    parts.append(f"- 작성 지침: {section.guidance}")
    if section.notes:
        parts.append(f"- 연구자 노트: {section.notes}")

    prev = _previous_sections_digest(project, section.key)
    if prev:
        parts.append("\n## 이미 작성된 다른 섹션 (일관성 참조)\n\n" + prev)

    related = _related_sources(lib, section)
    if related:
        bundle = lib.context_bundle(related)
        parts.append("\n## 관련 자료 (이 자료 안의 정보만 사용할 것)\n\n" + bundle)

    if section.needs_data and data_summary_md:
        parts.append("\n## 코딩시트 기술통계 결과\n\n" + data_summary_md)

    if extra_instructions:
        parts.append("\n## 추가 지시사항\n\n" + extra_instructions)

    return "\n\n".join(parts)


def draft_section(project: Project, lib: Library, section_key: str,
                  data_summary_md: str = "",
                  extra_instructions: str = "",
                  on_delta: Optional[Callable[[str], None]] = None,
                  save: bool = True) -> str:
    """한 섹션의 초안을 생성하고 프로젝트에 저장."""
    section = section_by_key(project, section_key)
    context = build_context(project, lib, section,
                            data_summary_md=data_summary_md,
                            extra_instructions=extra_instructions)

    user_prompt = (
        context
        + "\n\n---\n\n위의 컨텍스트만을 근거로 '"
        + section.title
        + "' 섹션의 초안을 마크다운으로 작성하시오. "
        "제목은 `## ` 수준부터 시작하고, 하위 소제목은 `### ` 이하로 붙이시오. "
        "인용 형식과 [출처 필요] 규칙을 반드시 지키시오."
    )

    client = _client()
    parts: list[str] = []
    with client.messages.stream(
        model=MODEL,
        max_tokens=64000,
        system=SYSTEM_PROMPT,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        for delta in stream.text_stream:
            parts.append(delta)
            if on_delta:
                on_delta(delta)
    draft = "".join(parts).strip()

    if save:
        write_section(project, section_key, draft, version=True)
    return draft


def revise_section(project: Project, lib: Library, section_key: str,
                   revision_instruction: str,
                   data_summary_md: str = "",
                   on_delta: Optional[Callable[[str], None]] = None,
                   save: bool = True) -> str:
    """기존 초안을 수정 지시에 맞춰 새 버전으로 다듬는다."""
    section = section_by_key(project, section_key)
    current = read_section(project, section_key)
    if not current:
        return draft_section(project, lib, section_key,
                             data_summary_md=data_summary_md,
                             extra_instructions=revision_instruction,
                             on_delta=on_delta, save=save)

    context = build_context(project, lib, section,
                            data_summary_md=data_summary_md,
                            extra_instructions=revision_instruction)

    user_prompt = (
        context
        + "\n\n## 현재 초안\n\n"
        + current
        + "\n\n---\n\n위 수정 지시사항을 반영해 이 초안을 다듬어라. "
        "핵심 서술은 유지하되 지적된 부분을 개선하고, [출처 필요] 표시를 "
        "임의로 채우지 마시오. 결과는 전체 섹션 마크다운으로 반환."
    )

    client = _client()
    parts: list[str] = []
    with client.messages.stream(
        model=MODEL,
        max_tokens=64000,
        system=SYSTEM_PROMPT,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        for delta in stream.text_stream:
            parts.append(delta)
            if on_delta:
                on_delta(delta)
    new_draft = "".join(parts).strip()

    if save:
        write_section(project, section_key, new_draft, version=True)
    return new_draft
