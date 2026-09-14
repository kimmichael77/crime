"""Auto-computed variables: rel_position, deviation_direction, law_period, etc.

Rules from the codebook and the researcher's coding notes:
- guideline_rel_position and area_rel_position are 0~1 ratio variables.
- deviation_direction depends on guideline_deviation and the rel_position
  relative to a threshold (default 0.15 for below, 0.85 for above).
- The multi_offense_* range must NOT be used for rel_position (Rule 2).
"""

from __future__ import annotations

from datetime import date
from typing import Optional


LOWER_THRESHOLD = 0.15
UPPER_THRESHOLD = 0.85

LAW_BOUNDARY_LOW = date(2020, 3, 24)   # 제14조의2 시행
LAW_BOUNDARY_HIGH = date(2024, 9, 26)  # 소지·시청 처벌 확대


def _num(x) -> Optional[float]:
    if x is None or x == "" or x == -99:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def rel_position(sentence_months, lo, hi) -> Optional[float]:
    s, mn, mx = _num(sentence_months), _num(lo), _num(hi)
    if s is None or mn is None or mx is None:
        return None
    if mx <= mn:
        return None
    return (s - mn) / (mx - mn)


def guideline_deviation(sentence_months, gmin, gmax) -> Optional[int]:
    """진정이탈 (형식적 이탈) 여부. Returns 0/1/9."""
    s, mn, mx = _num(sentence_months), _num(gmin), _num(gmax)
    if s is None or mn is None or mx is None:
        return 9
    return 0 if mn <= s <= mx else 1


def deviation_direction(sentence_months, gmin, gmax,
                        lower=LOWER_THRESHOLD, upper=UPPER_THRESHOLD) -> Optional[int]:
    """
    0=범위내 중간, 1=진정하향, 2=진정상향,
    3=부진정하향(범위내지만 rel<=lower),
    4=부진정상향(범위내지만 rel>=upper),
    9=판단불가.
    """
    s, mn, mx = _num(sentence_months), _num(gmin), _num(gmax)
    if s is None or mn is None or mx is None or mx <= mn:
        return 9
    if s < mn:
        return 1
    if s > mx:
        return 2
    rel = (s - mn) / (mx - mn)
    if rel <= lower:
        return 3
    if rel >= upper:
        return 4
    return 0


def law_period(judgment_date: Optional[date]) -> Optional[int]:
    """1=2020.3 이전, 2=2020.3~2024.9, 3=2024.9 이후."""
    if judgment_date is None:
        return None
    if judgment_date < LAW_BOUNDARY_LOW:
        return 1
    if judgment_date < LAW_BOUNDARY_HIGH:
        return 2
    return 3


def appeal_duration_days(prior: Optional[date], end: Optional[date]) -> Optional[int]:
    if prior is None or end is None:
        return None
    delta = (end - prior).days
    return delta if delta >= 0 else None


def compute_all(row: dict) -> dict:
    """Take a partially-coded row and fill in every computed field.
    The caller may run this before writing to xlsx so the sheet always
    stays consistent with what the codebook derives from raw values."""
    out = dict(row)

    sm = out.get("sentence_months")
    gmin = out.get("guideline_min_months")
    gmax = out.get("guideline_max_months")
    amin = out.get("area_min_months")
    amax = out.get("area_max_months")

    grp = rel_position(sm, gmin, gmax)
    arp = rel_position(sm, amin, amax)
    out["guideline_rel_position"] = round(grp, 4) if grp is not None else None
    out["area_rel_position"] = round(arp, 4) if arp is not None else None
    out["guideline_deviation"] = guideline_deviation(sm, gmin, gmax)
    out["deviation_direction"] = deviation_direction(sm, gmin, gmax)

    end = out.get("end_date")
    if isinstance(end, str) and end:
        try:
            end_d = date.fromisoformat(end)
        except ValueError:
            end_d = None
    else:
        end_d = end if isinstance(end, date) else None

    prior = out.get("prior_judgment_date")
    if isinstance(prior, str) and prior:
        try:
            prior_d = date.fromisoformat(prior)
        except ValueError:
            prior_d = None
    else:
        prior_d = prior if isinstance(prior, date) else None

    out["law_period"] = law_period(end_d)
    out["appeal_duration"] = appeal_duration_days(prior_d, end_d)
    return out
