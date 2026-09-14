"""Research library — 논문 작성을 위한 자료(선행연구, 판례, 법조문, 보고서) 등록·검색.

400페이지 분량의 박사논문을 채우려면 근거 자료가 방대해야 한다. 이 모듈은
연구자가 수집한 자료를 프로젝트 폴더 안에 체계적으로 축적하고, 각 섹션을
작성할 때 관련 자료를 자동으로 검색해 초안 생성기의 컨텍스트로 제공한다.

메타데이터 스키마:
  id           연구자 부여 (예: "조혜민-2025", "제주2023고합220")
  title        전체 제목
  authors      "조혜민" (여러 명은 쉼표)
  year         2025
  kind         "선행연구" | "판례" | "법조문" | "통계보고서" | "이론서" | "기타"
  tags         쉼표 구분 ("딥페이크,양형기준,판결문분석")
  citation     본문 인용용 짧은 형태 (예: "조혜민(2025)")
  reference    참고문헌 목록용 완전한 서지정보
  file_path    프로젝트 폴더 안의 원문 파일 경로 (선택)
  content      추출된 텍스트 (검색용, 파일이 있으면 자동 추출)
  summary      연구자가 직접 요약 (연구자용 노트)
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from . import pdf_reader


KIND_CHOICES = ["선행연구", "판례", "법조문", "통계보고서", "이론서", "기타"]


@dataclass
class Source:
    id: str
    title: str = ""
    authors: str = ""
    year: Optional[int] = None
    kind: str = "선행연구"
    tags: str = ""
    citation: str = ""
    reference: str = ""
    file_path: str = ""
    content: str = ""
    summary: str = ""
    created_at: str = ""

    def tag_list(self) -> list[str]:
        return [t.strip() for t in self.tags.split(",") if t.strip()]


class Library:
    """SQLite-backed library kept inside a project folder.

    파일 저장 구조:
      <project>/
        library.db              — 메타데이터 인덱스
        sources/                — 원본 파일 사본
          <id>.pdf 등
    """

    def __init__(self, project_dir: str | Path) -> None:
        self.dir = Path(project_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "sources").mkdir(exist_ok=True)
        self.db_path = self.dir / "library.db"
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS sources (
                id TEXT PRIMARY KEY,
                title TEXT DEFAULT '',
                authors TEXT DEFAULT '',
                year INTEGER,
                kind TEXT DEFAULT '선행연구',
                tags TEXT DEFAULT '',
                citation TEXT DEFAULT '',
                reference TEXT DEFAULT '',
                file_path TEXT DEFAULT '',
                content TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                created_at TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_kind ON sources(kind);
            CREATE INDEX IF NOT EXISTS idx_year ON sources(year);
        """)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def add(self, source: Source, source_file: Optional[str | Path] = None,
            extract_text: bool = True) -> Source:
        """Register a source. If `source_file` is a path, copy it to sources/
        and (optionally) extract text for searching."""
        if source_file:
            src = Path(source_file)
            if not src.exists():
                raise FileNotFoundError(f"원본 파일이 없습니다: {src}")
            dst = self.dir / "sources" / f"{source.id}{src.suffix.lower()}"
            shutil.copy2(src, dst)
            source.file_path = str(dst.relative_to(self.dir))
            if extract_text and not source.content:
                try:
                    source.content = pdf_reader.read(str(dst))
                except Exception as e:
                    source.content = f"[텍스트 추출 실패: {e}]"
        source.created_at = datetime.now().isoformat(timespec="seconds")
        self.conn.execute(
            "INSERT OR REPLACE INTO sources "
            "(id,title,authors,year,kind,tags,citation,reference,file_path,content,summary,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (source.id, source.title, source.authors, source.year,
             source.kind, source.tags, source.citation, source.reference,
             source.file_path, source.content, source.summary, source.created_at),
        )
        self.conn.commit()
        return source

    def get(self, source_id: str) -> Optional[Source]:
        row = self.conn.execute(
            "SELECT * FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        return _row_to_source(row) if row else None

    def all(self) -> list[Source]:
        rows = self.conn.execute(
            "SELECT * FROM sources ORDER BY year DESC, authors ASC"
        ).fetchall()
        return [_row_to_source(r) for r in rows]

    def delete(self, source_id: str) -> bool:
        s = self.get(source_id)
        if not s:
            return False
        if s.file_path:
            fp = self.dir / s.file_path
            if fp.exists():
                fp.unlink()
        self.conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        self.conn.commit()
        return True

    def search(self, query: str = "", kind: str = "", tag: str = "",
               limit: int = 20) -> list[Source]:
        """Simple full-text-ish search across title/authors/tags/content."""
        sql = "SELECT * FROM sources WHERE 1=1"
        params: list = []
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        if tag:
            sql += " AND tags LIKE ?"
            params.append(f"%{tag}%")
        if query:
            keywords = [k for k in re.split(r"\s+", query.strip()) if k]
            for kw in keywords:
                sql += (" AND (title LIKE ? OR authors LIKE ? OR tags LIKE ? "
                        "OR summary LIKE ? OR content LIKE ? OR reference LIKE ?)")
                like = f"%{kw}%"
                params.extend([like] * 6)
        sql += " ORDER BY year DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [_row_to_source(r) for r in rows]

    def bibliography(self) -> list[str]:
        """참고문헌 목록으로 쓸 수 있는 reference 문자열들."""
        rows = self.conn.execute(
            "SELECT reference FROM sources "
            "WHERE reference != '' "
            "ORDER BY authors ASC, year DESC"
        ).fetchall()
        return [r["reference"] for r in rows]

    def context_bundle(self, sources: Iterable[Source],
                       max_content_chars: int = 4000) -> str:
        """Assemble a compact markdown bundle to hand to Claude as context.
        Truncates each source's content so we don't blow the context window on
        one huge PDF; the summary field, when present, comes first."""
        parts: list[str] = []
        for s in sources:
            head = f"### [{s.id}] {s.title}"
            if s.authors or s.year:
                head += f"  — {s.authors}"
                if s.year:
                    head += f" ({s.year})"
            parts.append(head)
            parts.append(f"- 종류: {s.kind}  |  태그: {s.tags}")
            if s.citation:
                parts.append(f"- 본문 인용: {s.citation}")
            if s.reference:
                parts.append(f"- 참고문헌: {s.reference}")
            if s.summary:
                parts.append(f"\n**요약**:\n{s.summary.strip()}")
            if s.content:
                snippet = s.content.strip().replace("\n\n\n", "\n\n")
                if len(snippet) > max_content_chars:
                    snippet = snippet[:max_content_chars] + "\n... [발췌 절단됨]"
                parts.append(f"\n**원문 발췌**:\n{snippet}")
            parts.append("")
        return "\n".join(parts).strip()


def _row_to_source(row: sqlite3.Row) -> Source:
    return Source(
        id=row["id"], title=row["title"], authors=row["authors"],
        year=row["year"], kind=row["kind"], tags=row["tags"],
        citation=row["citation"], reference=row["reference"],
        file_path=row["file_path"], content=row["content"],
        summary=row["summary"], created_at=row["created_at"],
    )


def seed_from_proposal(lib: Library) -> None:
    """연구계획서 참고문헌 목록을 라이브러리에 등록 (제목·저자·연도만 채움).
    각 자료의 원문은 연구자가 별도로 등록하면서 채워나간다."""
    entries = [
        ("배상균-2025", "딥페이크 성범죄 대응 규제에 관한 검토",
         "배상균", 2025, "선행연구", "딥페이크,입법",
         "배상균(2025)",
         "배상균 (2025). 딥페이크 성범죄 대응 규제에 관한 검토. 외법논집, 49(2), 123-143."),
        ("조혜민-2025", "판결문 내용 분석을 통해 본 '딥페이크 성범죄' 실태",
         "조혜민", 2025, "선행연구", "딥페이크,판결문분석,젠더",
         "조혜민(2025)",
         "조혜민 (2025). [기획논문] 판결문 내용 분석을 통해 본 '딥페이크 성범죄' 실태. 여성연구, 124(1), 5-28."),
        ("한민경-2024", "미디어 플랫폼 속 성적 인격권 침해 - 허위영상물 편집·반포를 중심으로",
         "한민경", 2024, "선행연구", "딥페이크,허위영상물,반포목적",
         "한민경(2024)",
         "한민경 (2024). 미디어 플랫폼 속 성적 인격권 침해 - 허위영상물 편집·반포를 중심으로 -. 미디어와 인격권, 10(3), 53-86."),
        ("김중곤-2024", "약물을 이용한 성폭력범죄의 실태",
         "김중곤", 2024, "선행연구", "DFSA,판결문분석,통제균형이론",
         "김중곤(2024)",
         "김중곤 (2024). 약물을 이용한 성폭력범죄의 실태 - 주도형 DFSA에 대한 판결문 내용분석 -. 경찰학연구, 24(1), 53-87."),
        ("김한균-2014", "양형기준 존중과 양형기준을 벗어난 판결",
         "김한균", 2014, "이론서", "양형기준,이탈,진정이탈,부진정이탈",
         "김한균(2014)",
         "김한균 (2014). 양형기준 존중과 양형기준을 벗어난 판결. 형사정책, 26(3), 163-188."),
        ("Steffensmeier-1998", "The interaction of race, gender, and age in criminal sentencing",
         "Steffensmeier, D., Ulmer, J., & Kramer, J.", 1998, "이론서",
         "초점관심이론,양형결정",
         "Steffensmeier et al.(1998)",
         "Steffensmeier, D., Ulmer, J., & Kramer, J. (1998). The interaction of race, gender, and age in criminal sentencing. Criminology, 36(4), 763-798."),
        ("Albonetti-1991", "An integration of theories to explain judicial discretion",
         "Albonetti, C. A.", 1991, "이론서",
         "불확실성회피,양형결정",
         "Albonetti(1991)",
         "Albonetti, C. A. (1991). An integration of theories to explain judicial discretion. Social Problems, 38(2), 247-266."),
        ("Tittle-1995", "Control balance: Toward a general theory of deviance",
         "Tittle, C. R.", 1995, "이론서", "통제균형이론",
         "Tittle(1995)",
         "Tittle, C. R. (1995). Control balance: Toward a general theory of deviance. Boulder, CO: Westview."),
        ("양형위원회-2023", "디지털성범죄 양형기준",
         "대법원 양형위원회", 2023, "법조문", "양형기준,디지털성범죄",
         "대법원 양형위원회(2023)",
         "대법원 양형위원회. 디지털성범죄 양형기준(2023.4.24. 수정, 2023.7.1. 시행). https://sc.scourt.go.kr/sc/krsc/criterion/criterion_56/digital_sexual_01.jsp"),
        ("법원조직법-제81조의7", "양형기준의 효력 등",
         "국회", None, "법조문", "양형기준,법원조직법",
         "법원조직법 제81조의7",
         "법원조직법 제81조의7(양형기준의 효력 등)."),
    ]
    for row in entries:
        (sid, title, authors, year, kind, tags, citation, reference) = row
        lib.add(Source(id=sid, title=title, authors=authors, year=year,
                       kind=kind, tags=tags, citation=citation,
                       reference=reference))
