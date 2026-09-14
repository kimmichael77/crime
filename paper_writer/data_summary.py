"""코딩시트 xlsx로부터 결과 섹션 서술에 쓸 기술통계를 자동 계산.

R/Stata에서 본격 회귀분석을 하기 전에, 논문 결과 섹션에서 반드시 서술해야
할 요약 통계 — 표본 크기, 형종 분포, 양형기준 이탈 비율, rel_position 분포,
가해자·피해자 특성 등 — 을 마크다운으로 정리해 초안 생성기의 컨텍스트로
넣는다.
"""

from __future__ import annotations

import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from . import xlsx_io
from .codebook import FIELDS_BY_NAME


MISSING_NUM = -99
MISSING_CAT = 9


def _is_missing_num(v) -> bool:
    return v is None or v == "" or v == MISSING_NUM


def _is_missing_cat(v) -> bool:
    return v is None or v == "" or v == MISSING_CAT


def _fmt_num(x: float, digits: int = 2) -> str:
    if isinstance(x, int) or (isinstance(x, float) and x.is_integer()):
        return str(int(x))
    return f"{x:.{digits}f}"


def _numeric_summary(name: str, values: list[float]) -> dict[str, Any]:
    if not values:
        return {"name": name, "n": 0}
    mean = statistics.mean(values)
    sd = statistics.stdev(values) if len(values) > 1 else 0.0
    return {
        "name": name,
        "n": len(values),
        "mean": mean,
        "sd": sd,
        "min": min(values),
        "max": max(values),
        "median": statistics.median(values),
    }


def _cat_frequency(name: str, values: list[int]) -> dict[str, Any]:
    counter = Counter(values)
    field = FIELDS_BY_NAME.get(name)
    choices = (field.choices if field else {}) or {}
    total = sum(counter.values())
    dist = []
    for code, cnt in sorted(counter.items()):
        label = choices.get(code, "")
        pct = (cnt / total * 100) if total else 0.0
        dist.append({"code": code, "label": label, "count": cnt, "pct": pct})
    return {"name": name, "n": total, "distribution": dist}


def summarize(xlsx_path: str | Path,
              deep_dive: bool = True) -> dict[str, Any]:
    """전체 코딩시트를 훑어 요약 통계를 계산."""
    wb = xlsx_io.Workbook(xlsx_path)
    header = wb.header
    ws = wb.ws

    rows: list[dict[str, Any]] = []
    for r in range(2, ws.max_row + 1):
        row: dict[str, Any] = {}
        for i, name in enumerate(header):
            if not name:
                continue
            row[name] = ws.cell(row=r, column=i + 1).value
        if row.get("case_id"):
            rows.append(row)

    def collect_num(field_name: str) -> list[float]:
        out: list[float] = []
        for row in rows:
            v = row.get(field_name)
            if _is_missing_num(v):
                continue
            try:
                out.append(float(v))
            except (TypeError, ValueError):
                continue
        return out

    def collect_cat(field_name: str) -> list[int]:
        out: list[int] = []
        for row in rows:
            v = row.get(field_name)
            if _is_missing_cat(v):
                continue
            try:
                out.append(int(round(float(v))))
            except (TypeError, ValueError):
                continue
        return out

    summary: dict[str, Any] = {
        "n_total": len(rows),
        "numeric": {},
        "categorical": {},
        "deviation": {},
    }

    for var in ["sentence_months", "offender_age", "num_victims",
                "num_codefendants", "appeal_duration",
                "aggravating_factors", "mitigating_factors",
                "guideline_rel_position", "area_rel_position"]:
        summary["numeric"][var] = _numeric_summary(var, collect_num(var))

    for var in ["case_type", "sentence_type", "sentencing_guideline_type",
                "guideline_area", "guideline_deviation", "deviation_direction",
                "forensic_evidence", "distribution_purpose_established",
                "fabrication_suspected_unconfirmed", "prior_record",
                "victim_relationship", "victim_minor", "act_type",
                "platform", "law_period", "instance",
                "relationship_power_dynamic"]:
        summary["categorical"][var] = _cat_frequency(var, collect_cat(var))

    if deep_dive:
        # 부진정 하향이탈 비율 등 논문 핵심 지표
        dd = summary["categorical"]["deviation_direction"]["distribution"]
        codes = {d["code"]: d for d in dd}
        pseudo_low = codes.get(3, {}).get("count", 0)
        in_range = codes.get(0, {}).get("count", 0)
        pseudo_high = codes.get(4, {}).get("count", 0)
        true_low = codes.get(1, {}).get("count", 0)
        true_high = codes.get(2, {}).get("count", 0)
        total = pseudo_low + in_range + pseudo_high + true_low + true_high
        summary["deviation"] = {
            "n_with_guideline": total,
            "true_low": true_low,
            "true_high": true_high,
            "pseudo_low": pseudo_low,
            "pseudo_high": pseudo_high,
            "in_range_middle": in_range,
            "pseudo_low_ratio": (pseudo_low / total) if total else None,
        }

    wb.wb.close()
    return summary


def to_markdown(summary: dict[str, Any]) -> str:
    """Claude 컨텍스트용 마크다운으로 변환."""
    parts: list[str] = []
    n = summary["n_total"]
    parts.append(f"## 표본 개요")
    parts.append(f"- 전체 사건 수: **{n}건**")
    parts.append("")

    parts.append("## 형종·형량 분포")
    st = summary["categorical"].get("sentence_type", {}).get("distribution", [])
    for d in st:
        parts.append(f"- 형종 {d['code']} ({d['label']}): {d['count']}건 ({d['pct']:.1f}%)")
    sm = summary["numeric"].get("sentence_months", {})
    if sm.get("n"):
        parts.append(
            f"- 선고형량(월, 벌금·기타 제외 n={sm['n']}): "
            f"평균 {_fmt_num(sm['mean'])} · 표준편차 {_fmt_num(sm['sd'])} · "
            f"중앙값 {_fmt_num(sm['median'])} · 범위 {_fmt_num(sm['min'])}~{_fmt_num(sm['max'])}"
        )
    parts.append("")

    parts.append("## 양형기준 이탈")
    dev = summary.get("deviation", {})
    if dev.get("n_with_guideline"):
        parts.append(
            f"- 양형기준 기재 사건 n={dev['n_with_guideline']}"
        )
        parts.append(
            f"- 진정하향이탈 {dev['true_low']}건, 진정상향이탈 {dev['true_high']}건"
        )
        parts.append(
            f"- **부진정 하향이탈**(rel≤0.15) {dev['pseudo_low']}건 "
            f"({(dev['pseudo_low_ratio'] or 0) * 100:.1f}%), "
            f"부진정 상향이탈 {dev['pseudo_high']}건"
        )
        parts.append(f"- 범위내 중간 {dev['in_range_middle']}건")
        grp = summary["numeric"].get("guideline_rel_position", {})
        if grp.get("n"):
            parts.append(
                f"- guideline_rel_position 분포(n={grp['n']}): "
                f"평균 {grp['mean']:.3f} · 중앙값 {grp['median']:.3f} · "
                f"범위 {grp['min']:.3f}~{grp['max']:.3f}"
            )
    else:
        parts.append("- 양형기준 기재 사건이 없어 이탈 분석 불가.")
    parts.append("")

    parts.append("## 사실인정의 불확실성 관련 변수")
    for var in ["forensic_evidence", "distribution_purpose_established",
                "fabrication_suspected_unconfirmed"]:
        d = summary["categorical"].get(var, {})
        if not d.get("n"):
            continue
        parts.append(f"### {var} (n={d['n']})")
        for row in d["distribution"]:
            parts.append(f"- {row['code']} ({row['label']}): "
                         f"{row['count']}건 ({row['pct']:.1f}%)")
    parts.append("")

    parts.append("## 가해자·피해자 특성")
    for var in ["prior_record", "victim_relationship", "victim_minor",
                "relationship_power_dynamic"]:
        d = summary["categorical"].get(var, {})
        if not d.get("n"):
            continue
        parts.append(f"- {var} (n={d['n']}): " +
                     ", ".join(f"{row['code']}({row['label']})={row['count']}"
                               for row in d["distribution"]))
    age = summary["numeric"].get("offender_age", {})
    if age.get("n"):
        parts.append(
            f"- offender_age (n={age['n']}): 평균 {age['mean']:.1f}세, "
            f"범위 {age['min']:.0f}~{age['max']:.0f}"
        )
    parts.append("")

    parts.append("## 사건특성")
    for var in ["case_type", "act_type", "platform", "law_period", "instance"]:
        d = summary["categorical"].get(var, {})
        if not d.get("n"):
            continue
        parts.append(f"- {var} (n={d['n']}): " +
                     ", ".join(f"{row['code']}({row['label']})={row['count']}"
                               for row in d["distribution"]))
    parts.append("")

    return "\n".join(parts)
