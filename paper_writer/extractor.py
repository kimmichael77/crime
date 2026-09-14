"""Claude API extractor.

Given a judgment text, ask Claude to return a JSON row that obeys codebook v1.1
rules — especially Rule 1 (only what the judgment states, otherwise missing +
inferred_vars entry) and Rule 2 (guideline fields come from '허위영상물 등의
반포 등' 유형 only; multi_offense_* holds the '다수범죄 처리기준' range but is
never fed into rel_position).

The extractor returns a partial row — only the fields the JSON model can
actually populate. Computed fields (rel_position, deviation_direction,
law_period, appeal_duration) are filled in by analyzer.compute_all().
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Optional

import anthropic

from .codebook import FIELDS, coded_fields, is_hypothetical


MODEL = "claude-opus-5"
MAX_TOKENS = 16000

_SYSTEM = """\
당신은 형사판결문을 코딩북 v1.1 규칙에 따라 정확히 코딩하는 연구 조교이다.

이 연구의 대상은 「성폭력범죄의 처벌 등에 관한 특례법」 제14조의2(허위영상물
편집·반포등) 및 관련 죄로 처리된 판결이다. 결과는 반드시 JSON 하나로만 반환한다.

핵심 규칙 (반드시 준수):

[규칙 1] 판결문에 명시적으로 기재된 사항만 코딩한다. 명시적 기재가 없는 사항은
원칙적으로 결측(-99 또는 9) 처리한다. 예외적으로 간접 정황에 근거해 추론
코딩한 경우, 반드시 `inferred_vars`에 해당 변수명을 쉼표 구분으로 기재하고,
`coding_note`에 추론 근거를 명시한다.
예: 피고인 성별이 명시되어 있지 않지만 '자신의 여자친구 사진'이라는 서술로
남성으로 추론 → offender_gender=0, inferred_vars="offender_gender".

[규칙 2] 양형기준 관련 변수(sentencing_guideline_type, guideline_min_months,
guideline_max_months, guideline_area, area_min_months, area_max_months,
aggravating_factors, mitigating_factors)는 모두 '디지털성범죄 > 03. 허위영상물
등의 반포 등' 유형에 대한 [유형의 결정]·[권고영역 및 권고형의 범위] 기재만을
대상으로 한다. 해당 유형에 대한 기재가 판결문에 없으면 전부 결측 처리한다
(수치는 -99, 범주는 9). 다수범죄 처리기준은 multi_offense_min_months /
multi_offense_max_months에 별도 기록한다(상한 미제시 시 -99).

형종 코딩:
- 실형 → sentence_type=1, sentence_months=징역월수
- 집행유예 → sentence_type=2, sentence_months=징역월수(유예기간 아님)
- 벌금형 → sentence_type=3, sentence_months=-99
- 무죄·선고유예·면소·공소기각 → sentence_type=4, sentence_months=-99

계산변수는 절대 추출하지 말고 null로 남긴다:
- guideline_deviation, deviation_direction, guideline_rel_position,
  area_rel_position, appeal_duration, law_period

날짜는 YYYY-MM-DD (또는 확인 불가 시 null).

case_id는 지정하지 않는다 (연구자가 부여).
coder_id는 "claude-opus-5"로 기재한다.

각 필드값이 판결문의 어느 부분에서 나왔는지 coding_note에 요약해서 남기는
것을 권장한다. 규칙 1에 따라 결측 처리한 항목은 그 사유(예: "피고인 연령
미기재")를 coding_note에 반드시 기록한다.
"""


def _client() -> anthropic.Anthropic:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY 환경변수가 설정되어 있지 않습니다.\n"
            "  Windows PowerShell:  setx ANTHROPIC_API_KEY \"sk-ant-...\"\n"
            "  macOS / Linux shell: export ANTHROPIC_API_KEY=\"sk-ant-...\""
        )
    return anthropic.Anthropic()


def _field_catalog_for_prompt() -> str:
    """Compact field spec so Claude knows exactly what keys and codes to return."""
    lines: list[str] = []
    for f in coded_fields():
        marker = " *" if is_hypothetical(f.name) else ""
        line = f"- {f.name}{marker} [{f.kind}]: {f.definition}"
        if f.choices:
            codes = ", ".join(f"{k}={v}" for k, v in f.choices.items())
            line += f"  (코드: {codes})"
        if f.missing_value is not None:
            line += f"  (결측값: {f.missing_value})"
        lines.append(line)
    lines.append("- inferred_vars [text]: 규칙 1에 따라 추론 코딩한 변수명 (쉼표 구분)")
    lines.append("- coder_id [text]: 코딩 담당자 (\"claude-opus-5\"로 기재)")
    lines.append("- coding_note [text]: 결측/모호/추론 사유 요약")
    return "\n".join(lines)


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("Claude 응답에서 JSON 객체를 찾지 못했습니다.\n" + text[:400])
    return json.loads(match.group(0))


def _sanitize(row: dict) -> dict:
    """Drop keys not in the codebook, coerce empty strings to None where sensible."""
    allowed = {f.name for f in FIELDS}
    clean: dict[str, Any] = {}
    for k, v in row.items():
        if k not in allowed:
            continue
        if v == "":
            v = None
        clean[k] = v
    # Never trust the extractor with computed fields.
    for c in ("guideline_deviation", "deviation_direction",
              "guideline_rel_position", "area_rel_position",
              "appeal_duration", "law_period"):
        clean.pop(c, None)
    return clean


def extract(
    judgment_text: str,
    on_delta: Optional[Callable[[str], None]] = None,
    case_id: Optional[str] = None,
    max_input_chars: int = 200_000,
) -> dict:
    """Extract a coded row from a single judgment.

    Uses streaming so large inputs never hit an HTTP timeout.
    Returns a dict keyed by codebook field names.
    """
    if len(judgment_text) > max_input_chars:
        judgment_text = judgment_text[:max_input_chars] + "\n... [입력이 길어 절단됨]"

    user_prompt = (
        "다음 판결문을 코딩북에 따라 코딩하고 결과를 JSON 하나로 반환하시오. "
        "JSON 외의 설명은 절대 붙이지 마시오.\n\n"
        "=== 코딩할 필드 목록 ===\n"
        f"{_field_catalog_for_prompt()}\n\n"
        "=== 판결문 시작 ===\n"
        f"{judgment_text}\n"
        "=== 판결문 끝 ===\n\n"
        "JSON 형식 예시 (값은 판결문에 맞게 채울 것):\n"
        "{\n"
        '  "case_type": 1,\n'
        '  "sentence_months": 14,\n'
        '  "sentence_type": 1,\n'
        '  "sentencing_guideline_type": 2,\n'
        '  "guideline_min_months": 6,\n'
        '  "guideline_max_months": 18,\n'
        '  "guideline_area": 2,\n'
        '  "inferred_vars": "",\n'
        '  "coder_id": "claude-opus-5",\n'
        '  "coding_note": "..."\n'
        "}"
    )

    client = _client()
    parts: list[str] = []
    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=_SYSTEM,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        for delta in stream.text_stream:
            parts.append(delta)
            if on_delta:
                on_delta(delta)

    raw = "".join(parts)
    row = _parse_json(raw)
    row = _sanitize(row)
    if case_id:
        row["case_id"] = case_id
    return row
