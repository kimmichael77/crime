"""CLI — 논문 작성 파이프라인을 커맨드라인에서 사용.

빠른 사용 예:

  # 새 프로젝트 만들기
  python -m paper_writer.paper_cli init ./my_thesis --title "박사학위논문"

  # 연구계획서 자료 라이브러리 씨드
  python -m paper_writer.paper_cli library seed ./my_thesis

  # 자료 하나 등록 (PDF나 텍스트)
  python -m paper_writer.paper_cli library add ./my_thesis \\
      --id 판례-제주2023고합220 --kind 판례 \\
      --title "제주지방법원 2023고합220 판결" \\
      --file /path/to/judgment.pdf

  # 자료 목록
  python -m paper_writer.paper_cli library list ./my_thesis

  # 섹션 목록 (기본 26개 + 초록 + 참고문헌)
  python -m paper_writer.paper_cli sections ./my_thesis

  # 특정 섹션 초안 생성
  python -m paper_writer.paper_cli draft ./my_thesis 04_이론_사실인정불확실성

  # 결과 섹션 (코딩시트 필요)
  python -m paper_writer.paper_cli draft ./my_thesis 16_결과_기술통계 \\
      --xlsx ./data/coding_sheet.xlsx

  # 기존 초안 다듬기
  python -m paper_writer.paper_cli revise ./my_thesis 04_이론_사실인정불확실성 \\
      "제주2023고합220 판결의 양형이유 부분을 좀 더 상세히 인용해 주세요"

  # 코딩시트 기술통계만 마크다운으로 출력
  python -m paper_writer.paper_cli stats ./data/coding_sheet.xlsx

  # 지금까지 확정된 섹션을 이어붙여 draft_paper.md 생성
  python -m paper_writer.paper_cli compile ./my_thesis
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import writing_project as wp
from . import drafter, data_summary, notebook
from .library import Library, Source, seed_from_proposal, KIND_CHOICES


def _print_stream(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def cmd_init(args) -> int:
    proj = wp.load_or_create(args.dir, title=args.title)
    Library(args.dir).close()  # library.db 초기화
    print(f"프로젝트 생성/열림: {proj.dir}")
    print(f"제목: {proj.title}")
    print(f"섹션 {len(proj.sections)}개, 파일: {proj.json_path}")
    return 0


def cmd_sections(args) -> int:
    proj = wp.load_or_create(args.dir)
    for s in proj.sections:
        mark = {"미착수": " ", "초안": "·", "수정중": "~", "확정": "✓"}.get(s.status, " ")
        print(f"  [{mark}] {s.key:35}  {s.title}  (~{s.estimated_pages}쪽)")
    return 0


def cmd_library_seed(args) -> int:
    lib = Library(args.dir)
    seed_from_proposal(lib)
    print(f"연구계획서 참고문헌 시드 완료: {len(lib.all())}건")
    lib.close()
    return 0


def cmd_library_add(args) -> int:
    lib = Library(args.dir)
    source = Source(
        id=args.id, title=args.title, authors=args.authors,
        year=args.year, kind=args.kind, tags=args.tags,
        citation=args.citation, reference=args.reference,
        summary=args.summary or "",
    )
    lib.add(source, source_file=args.file, extract_text=True)
    print(f"등록 완료: {args.id}  ({args.title})")
    if args.file:
        print(f"  원본 파일 사본: sources/{args.id}{Path(args.file).suffix}")
    lib.close()
    return 0


def cmd_library_list(args) -> int:
    lib = Library(args.dir)
    for s in lib.all():
        year = f"({s.year})" if s.year else "     "
        tags = f" [{s.tags}]" if s.tags else ""
        print(f"  {s.id:30}  {s.kind:8}  {year}  {s.authors[:20]:20}  {s.title[:40]}{tags}")
    print(f"\n총 {len(lib.all())}건")
    lib.close()
    return 0


def cmd_library_delete(args) -> int:
    lib = Library(args.dir)
    ok = lib.delete(args.id)
    print("삭제됨." if ok else "해당 id를 찾을 수 없습니다.")
    lib.close()
    return 0 if ok else 1


def cmd_stats(args) -> int:
    summary = data_summary.summarize(args.xlsx)
    md = data_summary.to_markdown(summary)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"결과를 {args.out} 에 저장했습니다.")
    else:
        print(md)
    return 0


def cmd_draft(args) -> int:
    proj = wp.load_or_create(args.dir)
    lib = Library(args.dir)

    data_md = ""
    if args.xlsx:
        summary = data_summary.summarize(args.xlsx)
        data_md = data_summary.to_markdown(summary)

    print(f"[draft] 섹션 {args.section} 초안 생성 중...\n")
    try:
        text = drafter.draft_section(
            proj, lib, args.section,
            data_summary_md=data_md,
            extra_instructions=args.extra or "",
            on_delta=_print_stream if args.stream else None,
        )
    finally:
        lib.close()
    print(f"\n\n[draft] 저장 완료: {wp.section_file(proj, wp.section_by_key(proj, args.section))}")
    if not args.stream:
        print("\n---\n" + text)
    return 0


def cmd_revise(args) -> int:
    proj = wp.load_or_create(args.dir)
    lib = Library(args.dir)

    data_md = ""
    if args.xlsx:
        summary = data_summary.summarize(args.xlsx)
        data_md = data_summary.to_markdown(summary)

    print(f"[revise] 섹션 {args.section} 다듬는 중...\n")
    try:
        text = drafter.revise_section(
            proj, lib, args.section,
            revision_instruction=args.instruction,
            data_summary_md=data_md,
            on_delta=_print_stream if args.stream else None,
        )
    finally:
        lib.close()
    print(f"\n\n[revise] 새 버전 저장 완료.")
    if not args.stream:
        print("\n---\n" + text)
    return 0


def cmd_ask(args) -> int:
    lib = Library(args.dir)
    try:
        answer, used = notebook.ask(
            args.dir, lib, args.question,
            conversation_name=args.chat,
            pinned_source_ids=args.pin or None,
            kind=args.kind, tag=args.tag,
            on_delta=_print_stream if args.stream else None,
        )
    finally:
        lib.close()
    if not args.stream:
        print(answer)
    print(f"\n\n[사용한 자료] {', '.join(used) if used else '(없음)'}")
    return 0


def cmd_briefing(args) -> int:
    lib = Library(args.dir)
    try:
        text = notebook.briefing(
            args.dir, lib, args.topic,
            on_delta=_print_stream if args.stream else None,
        )
    finally:
        lib.close()
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"\n\n[briefing] 저장: {args.out}")
    elif not args.stream:
        print(text)
    return 0


def cmd_compile(args) -> int:
    proj = wp.load_or_create(args.dir)
    lib = Library(args.dir)
    out = wp.compile_full_draft(proj)
    refs = lib.bibliography()
    ref_out = wp.compile_references(proj, refs)
    lib.close()
    print(f"draft_paper.md 생성: {out}")
    print(f"references.md 생성: {ref_out} ({len(refs)}개 항목)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="paper", description="박사논문 글쓰기 파이프라인")
    sub = p.add_subparsers(dest="cmd", required=True)

    ip = sub.add_parser("init", help="새 프로젝트 초기화")
    ip.add_argument("dir")
    ip.add_argument("--title", default="박사학위논문")
    ip.set_defaults(func=cmd_init)

    sp = sub.add_parser("sections", help="섹션 목록")
    sp.add_argument("dir")
    sp.set_defaults(func=cmd_sections)

    lp = sub.add_parser("library", help="자료 라이브러리")
    lsub = lp.add_subparsers(dest="lcmd", required=True)

    lseed = lsub.add_parser("seed", help="연구계획서 참고문헌 시드")
    lseed.add_argument("dir")
    lseed.set_defaults(func=cmd_library_seed)

    ladd = lsub.add_parser("add", help="자료 등록")
    ladd.add_argument("dir")
    ladd.add_argument("--id", required=True, help="예: 조혜민-2025")
    ladd.add_argument("--title", required=True)
    ladd.add_argument("--authors", default="")
    ladd.add_argument("--year", type=int, default=None)
    ladd.add_argument("--kind", choices=KIND_CHOICES, default="선행연구")
    ladd.add_argument("--tags", default="")
    ladd.add_argument("--citation", default="")
    ladd.add_argument("--reference", default="")
    ladd.add_argument("--summary", default="")
    ladd.add_argument("--file", default=None, help="원본 PDF/DOCX/TXT 경로")
    ladd.set_defaults(func=cmd_library_add)

    llist = lsub.add_parser("list", help="자료 목록")
    llist.add_argument("dir")
    llist.set_defaults(func=cmd_library_list)

    ldel = lsub.add_parser("delete", help="자료 삭제")
    ldel.add_argument("dir")
    ldel.add_argument("id")
    ldel.set_defaults(func=cmd_library_delete)

    st = sub.add_parser("stats", help="코딩시트 기술통계 → 마크다운")
    st.add_argument("xlsx")
    st.add_argument("--out", default=None, help="파일로 저장 (미지정 시 표준출력)")
    st.set_defaults(func=cmd_stats)

    dr = sub.add_parser("draft", help="섹션 초안 생성")
    dr.add_argument("dir")
    dr.add_argument("section", help="예: 04_이론_사실인정불확실성")
    dr.add_argument("--xlsx", default=None, help="결과 섹션이면 코딩시트 지정")
    dr.add_argument("--extra", default=None, help="추가 지시사항")
    dr.add_argument("--stream", action="store_true", help="스트리밍 출력")
    dr.set_defaults(func=cmd_draft)

    rv = sub.add_parser("revise", help="기존 초안 다듬기")
    rv.add_argument("dir")
    rv.add_argument("section")
    rv.add_argument("instruction", help="수정 지시사항")
    rv.add_argument("--xlsx", default=None)
    rv.add_argument("--stream", action="store_true")
    rv.set_defaults(func=cmd_revise)

    cp = sub.add_parser("compile", help="전체 섹션 이어붙여 draft_paper.md 생성")
    cp.add_argument("dir")
    cp.set_defaults(func=cmd_compile)

    ap = sub.add_parser("ask", help="라이브러리 안의 자료로 QA (NotebookLM 스타일)")
    ap.add_argument("dir")
    ap.add_argument("question", help="자연어 질문")
    ap.add_argument("--chat", default="default", help="대화 이름 (연속 대화 유지)")
    ap.add_argument("--pin", action="append", default=[],
                    help="반드시 참조할 자료 ID (여러 번 사용 가능)")
    ap.add_argument("--kind", default="", help="자료 유형으로 필터")
    ap.add_argument("--tag", default="", help="태그로 필터")
    ap.add_argument("--stream", action="store_true")
    ap.set_defaults(func=cmd_ask)

    bp = sub.add_parser("briefing", help="주제 브리핑 문서 자동 작성 (NotebookLM 스타일)")
    bp.add_argument("dir")
    bp.add_argument("topic")
    bp.add_argument("--out", default=None, help="파일로 저장")
    bp.add_argument("--stream", action="store_true")
    bp.set_defaults(func=cmd_briefing)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
