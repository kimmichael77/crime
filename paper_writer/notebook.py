"""NotebookLM 스타일 대화형 QA — 라이브러리의 자료 안에서만 답한다.

Google NotebookLM의 핵심 원칙 두 가지를 지킨다:
  1. 사용자가 등록한 자료 안에서만 답변한다. 자료에 없는 내용은 만들어내지 않고
     "자료에서 확인되지 않는다"고 명시한다.
  2. 답변에 어느 자료를 근거로 삼았는지 [자료ID] 형태로 인용한다.

대화 상태는 프로젝트 폴더 안의 conversations/<name>.json 에 저장되어
다음 세션에서 이어서 질문할 수 있다.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import anthropic

from .library import Library, Source


MODEL = "claude-opus-5"
MAX_SOURCES_PER_TURN = 8
MAX_TOKENS = 8000


SYSTEM_PROMPT = """\
당신은 연구자가 축적한 자료 라이브러리 안에서만 답하는 학술 조수이다.
Google NotebookLM과 같은 방식으로 작동한다.

절대 규칙:

1. 자료 안에서만 답한다.
   - 답변의 모든 사실은 이 대화에 제공된 '자료 발췌'에서 근거를 찾을 수 있어야 한다.
   - 자료에 근거가 없는 사실 · 통계 · 인용 · 날짜 · 저자 · 판례 사건번호는 절대 만들어내지 않는다.
   - 자료로 답할 수 없는 질문에는 "제공된 자료에서 확인되지 않습니다"라고 명확히 답한다.
     이때 어떤 자료가 더 있으면 답할 수 있는지 짧게 제안해도 된다.

2. 답변에 인용을 단다.
   - 각 문장 · 문단이 어느 자료에 근거했는지 대괄호로 표시. 예: [조혜민-2025], [한민경-2024].
   - 판례 인용은 자료의 원문에 나온 사건번호를 그대로 사용. 예: "제주지방법원 2023고합220 판결 [판례-제주2023고합220]".
   - 두 자료가 모두 근거이면 [A, B]처럼 함께 표시.
   - 한 문단에서 여러 문장이 같은 자료에서 왔으면 문단 끝에 한 번만 표시해도 된다.

3. 대화 톤
   - 학술 서술체. 필요한 경우 목록·표를 사용해도 되지만, 답변의 골격은 근거 기반.
   - 사용자가 '한 문단으로', '표로 정리', '이론적 함의를 짧게' 같이 형식을 요구하면 그대로 따른다.
   - 논쟁적 해석이 자료에 나오면, 어느 자료가 어떤 주장을 하는지 대비해 보여준다.

4. 도움말
   - 사용자가 이전 답변을 인용해 후속 질문을 던지면 대화 히스토리를 참고해 이어간다.
   - 사용자가 특정 자료를 지정하지 않으면 관련도가 높은 자료 위주로 발췌를 사용한다.
"""


@dataclass
class Turn:
    role: str          # "user" | "assistant"
    content: str
    sources_used: list[str] = field(default_factory=list)
    timestamp: str = ""


@dataclass
class Conversation:
    name: str
    turns: list[Turn] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


def _client() -> anthropic.Anthropic:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY 환경변수가 설정되어 있지 않습니다.")
    return anthropic.Anthropic()


def conv_dir(project_dir: str | Path) -> Path:
    p = Path(project_dir) / "conversations"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _sanitize_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_가-힣.-]+", "_", name) or "chat"


def load_conversation(project_dir: str | Path, name: str) -> Conversation:
    fp = conv_dir(project_dir) / f"{_sanitize_name(name)}.json"
    if fp.exists():
        data = json.loads(fp.read_text(encoding="utf-8"))
        return Conversation(
            name=data["name"],
            turns=[Turn(**t) for t in data.get("turns", [])],
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )
    now = datetime.now().isoformat(timespec="seconds")
    return Conversation(name=name, created_at=now, updated_at=now)


def save_conversation(project_dir: str | Path, conv: Conversation) -> Path:
    conv.updated_at = datetime.now().isoformat(timespec="seconds")
    fp = conv_dir(project_dir) / f"{_sanitize_name(conv.name)}.json"
    fp.write_text(
        json.dumps({
            "name": conv.name,
            "created_at": conv.created_at,
            "updated_at": conv.updated_at,
            "turns": [asdict(t) for t in conv.turns],
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return fp


def _select_sources(lib: Library, question: str,
                    pinned_ids: Optional[list[str]] = None,
                    kind: str = "", tag: str = "") -> list[Source]:
    """Pick sources relevant to the question. Pinned ids always in."""
    sources: list[Source] = []
    seen: set[str] = set()

    for pid in (pinned_ids or []):
        s = lib.get(pid)
        if s and s.id not in seen:
            sources.append(s)
            seen.add(s.id)

    remaining = max(0, MAX_SOURCES_PER_TURN - len(sources))
    if remaining > 0:
        found = lib.search(query=question, kind=kind, tag=tag, limit=remaining * 2)
        for s in found:
            if s.id not in seen:
                sources.append(s)
                seen.add(s.id)
            if len(sources) >= MAX_SOURCES_PER_TURN:
                break
    return sources


def _turns_to_messages(conv: Conversation) -> list[dict]:
    """Anthropic messages 배열로 변환 (system은 별도로 넘김)."""
    out: list[dict] = []
    for t in conv.turns:
        out.append({"role": t.role, "content": t.content})
    return out


def ask(project_dir: str | Path,
        lib: Library,
        question: str,
        conversation_name: str = "default",
        pinned_source_ids: Optional[list[str]] = None,
        kind: str = "",
        tag: str = "",
        on_delta: Optional[Callable[[str], None]] = None) -> tuple[str, list[str]]:
    """한 번의 QA. 대화 상태를 자동 저장하고 (답변, 사용한 자료 ID 목록)을 반환."""
    conv = load_conversation(project_dir, conversation_name)

    sources = _select_sources(lib, question, pinned_source_ids, kind=kind, tag=tag)
    bundle = lib.context_bundle(sources) if sources else "_(관련 자료 없음 — 라이브러리에 자료를 등록하세요.)_"

    prefix = (
        "## 자료 발췌 (아래 자료 안에서만 답할 것)\n\n"
        + bundle
        + "\n\n---\n\n"
        + "## 사용자 질문\n\n"
        + question
    )

    # 히스토리는 유지하되, 현재 턴의 사용자 프롬프트는 자료+질문으로 확장.
    messages: list[dict] = _turns_to_messages(conv)
    messages.append({"role": "user", "content": prefix})

    client = _client()
    parts: list[str] = []
    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        thinking={"type": "adaptive"},
        messages=messages,
    ) as stream:
        for delta in stream.text_stream:
            parts.append(delta)
            if on_delta:
                on_delta(delta)
    answer = "".join(parts).strip()

    # 히스토리에는 원본 질문만 저장 (자료 발췌는 매 턴 재조립)
    now = datetime.now().isoformat(timespec="seconds")
    conv.turns.append(Turn(role="user", content=question, timestamp=now))
    used_ids = [s.id for s in sources]
    conv.turns.append(Turn(role="assistant", content=answer,
                           sources_used=used_ids, timestamp=now))
    save_conversation(project_dir, conv)
    return answer, used_ids


def briefing(project_dir: str | Path, lib: Library,
             topic: str,
             on_delta: Optional[Callable[[str], None]] = None) -> str:
    """NotebookLM의 'briefing doc'처럼, 주어진 주제에 대해 라이브러리 전체를
    바탕으로 2~4쪽 분량의 종합 정리를 작성한다."""
    sources = lib.search(query=topic, limit=12)
    bundle = lib.context_bundle(sources, max_content_chars=3000) if sources else "_(자료 없음)_"

    user_prompt = (
        "다음 자료를 근거로 '"
        + topic
        + "' 주제에 대한 종합 브리핑을 마크다운으로 작성하시오. "
        "1) 핵심 논점, 2) 각 자료의 주장 · 방법 · 발견, 3) 자료 간 일치·상충, "
        "4) 연구 공백을 순서대로 다루고, 각 문단 끝에 [자료ID] 인용을 붙이시오. "
        "자료에 없는 내용은 만들어내지 마시오.\n\n"
        + "## 자료 발췌\n\n"
        + bundle
    )

    client = _client()
    parts: list[str] = []
    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        for delta in stream.text_stream:
            parts.append(delta)
            if on_delta:
                on_delta(delta)
    return "".join(parts).strip()
