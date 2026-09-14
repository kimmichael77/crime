"""Read from and append to the researcher's existing 코딩시트 workbook.

The column order is defined by the workbook itself, not by our codebook order,
so we always look up columns by name from the header row. If a codebook field
does not exist in the sheet, it is skipped (with a warning). This lets the
tool coexist with the researcher's own edits.
"""

from __future__ import annotations

import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Optional

import openpyxl

from .codebook import FIELDS_BY_NAME


SHEET_NAME = "코딩시트"


def _to_cell_value(name: str, value: Any) -> Any:
    if value is None or value == "":
        return None
    field = FIELDS_BY_NAME.get(name)
    kind = field.kind if field else "text"
    if kind == "date":
        if isinstance(value, (date, datetime)):
            return value if isinstance(value, date) else value.date()
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None
    if kind in {"int"}:
        try:
            return int(round(float(value)))
        except (TypeError, ValueError):
            return None
    if kind in {"float"}:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return str(value)


def _from_cell_value(name: str, value: Any) -> Any:
    if value is None:
        return None
    field = FIELDS_BY_NAME.get(name)
    kind = field.kind if field else "text"
    if kind == "date":
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return str(value)[:10] if value else None
    if kind == "int":
        try:
            return int(round(float(value)))
        except (TypeError, ValueError):
            return value
    if kind == "float":
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    return value


class Workbook:
    """Thin wrapper around openpyxl for the 코딩시트 sheet."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"코딩시트 파일을 찾을 수 없습니다: {self.path}")
        self.wb = openpyxl.load_workbook(self.path)
        if SHEET_NAME not in self.wb.sheetnames:
            raise ValueError(
                f"'{SHEET_NAME}' 시트가 없습니다. 사용 가능한 시트: {self.wb.sheetnames}"
            )
        self.ws = self.wb[SHEET_NAME]
        self.header: list[str] = [
            (str(c.value).strip() if c.value is not None else "")
            for c in self.ws[1]
        ]
        self.col_index = {name: i + 1 for i, name in enumerate(self.header) if name}

    def next_case_id(self, prefix: str = "DF-2026-") -> str:
        """Return the next unused case_id matching '{prefix}NNN' pattern."""
        col = self.col_index.get("case_id")
        if not col:
            return f"{prefix}001"
        used: set[str] = set()
        for row in self.ws.iter_rows(min_row=2, min_col=col, max_col=col,
                                     values_only=True):
            v = row[0]
            if isinstance(v, str) and v.startswith(prefix):
                used.add(v)
        n = 1
        while True:
            candidate = f"{prefix}{n:03d}"
            if candidate not in used:
                return candidate
            n += 1

    def find_row(self, case_id: str) -> Optional[int]:
        col = self.col_index.get("case_id")
        if not col:
            return None
        for idx, row in enumerate(
            self.ws.iter_rows(min_row=2, min_col=col, max_col=col, values_only=True),
            start=2,
        ):
            if row[0] == case_id:
                return idx
        return None

    def read_row(self, case_id: str) -> Optional[dict]:
        r = self.find_row(case_id)
        if r is None:
            return None
        out: dict[str, Any] = {}
        for name, col in self.col_index.items():
            out[name] = _from_cell_value(name, self.ws.cell(row=r, column=col).value)
        return out

    def upsert(self, row: dict, backup: bool = True) -> int:
        """Insert or update a row keyed by case_id. Returns the sheet row index."""
        case_id = row.get("case_id")
        if not case_id:
            raise ValueError("row에 case_id가 없습니다.")

        target = self.find_row(case_id)
        if target is None:
            target = self.ws.max_row + 1

        for name, value in row.items():
            col = self.col_index.get(name)
            if not col:
                continue  # column not present in this sheet — skip silently
            cell = self.ws.cell(row=target, column=col)
            cell.value = _to_cell_value(name, value)
        return target

    def save(self, backup: bool = True) -> Path:
        if backup and self.path.exists():
            bak = self.path.with_suffix(self.path.suffix + ".bak")
            shutil.copy2(self.path, bak)
        self.wb.save(self.path)
        return self.path

    def all_case_ids(self) -> list[str]:
        col = self.col_index.get("case_id")
        if not col:
            return []
        ids: list[str] = []
        for row in self.ws.iter_rows(min_row=2, min_col=col, max_col=col, values_only=True):
            v = row[0]
            if isinstance(v, str) and v.strip():
                ids.append(v.strip())
        return ids


def create_blank(path: str | Path, source: Optional[str | Path] = None) -> Path:
    """Create a new coding workbook. If `source` is given, copy it as the template."""
    dst = Path(path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if source and Path(source).exists():
        shutil.copy2(source, dst)
        return dst
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = SHEET_NAME
    from .codebook import FIELDS
    ws.append([f.name for f in FIELDS])
    wb.save(dst)
    return dst
