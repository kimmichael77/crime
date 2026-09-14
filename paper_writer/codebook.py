"""Codebook v1.1 (2026-09-11) — machine-readable definition of every variable.

This mirrors the '코딩북' sheet in the researcher's coding workbook so the
extractor, analyzer, and GUI all share one source of truth. The order of
`FIELDS` matches the column order of the '코딩시트' sheet, which lets the
xlsx writer append values without reshuffling.

Sentinel values used throughout the study:
  -99  numeric variable is missing / not applicable (e.g. fines have no month value)
    9  categorical variable is 확인불가 / 판단불가 / 미기재
  None date variable is missing (empty cell in xlsx)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


MISSING_NUM = -99
MISSING_CAT = 9


@dataclass(frozen=True)
class Field:
    name: str
    kind: str            # "int" | "float" | "cat" | "date" | "text"
    category: str        # 코딩북의 '구분'
    definition: str
    coding_rule: str
    status: str          # "확정" | "가설(파일럿검증)"
    choices: dict | None = None   # for kind="cat", {code: label}
    missing_value: object | None = None  # -99, 9, or None
    computed: bool = False        # True if computed by analyzer.py


FIELDS: list[Field] = [
    Field("case_id", "text", "식별",
          "사건 고유 식별번호",
          "연구자 부여 (예: DF-2024-001)", "확정"),
    Field("case_type", "cat", "식별/비교군",
          "사건 유형(핵심 비교변수)",
          "0=몰카(카메라등이용촬영, 제14조), 1=딥페이크(허위영상물, 제14조의2)",
          "확정",
          choices={0: "몰카(제14조)", 1: "딥페이크(제14조의2)"},
          missing_value=MISSING_CAT),
    Field("start_date", "date", "시간",
          "관찰 시작일",
          "공소제기일 기준, 불명 시 1심 최초 공판일. 판결문에 없으면 공란", "확정"),
    Field("end_date", "date", "시간",
          "관찰 종료일",
          "확정판결일 또는 자료수집 마감일(중도절단 시)", "확정"),
    Field("duration", "int", "시간",
          "처리기간(일) — 설계변경으로 결측",
          "판결문에 공소제기일이 거의 기재되지 않아 '기소~확정' 계산 불가. "
          "항소심 사건에 한해 appeal_duration으로 대체함", "확정",
          missing_value=MISSING_NUM),
    Field("event", "cat", "사건지시자",
          "확정판결 발생 여부",
          "1=확정, 0=중도절단(미확정)", "확정",
          choices={0: "중도절단", 1: "확정"},
          missing_value=MISSING_CAT),
    Field("sentence_months", "int", "종속변수(주)",
          "선고 형량(월 단위 환산)",
          "징역 1년2개월=14, 징역 2년6월=30. 집행유예도 징역형 기간을 기재(유예기간 아님). "
          "벌금형은 결측(-99) 후 sentence_type으로 구분", "확정",
          missing_value=MISSING_NUM),
    Field("sentence_type", "cat", "종속변수(주)",
          "선고 형종",
          "1=실형, 2=집행유예, 3=벌금형, 4=기타(무죄·선고유예·면소·공소기각)", "확정",
          choices={1: "실형", 2: "집행유예", 3: "벌금형", 4: "기타"},
          missing_value=MISSING_CAT),
    Field("prior_judgment_date", "date", "종속변수(보조)",
          "원심(1심) 선고일 — 항소심 사건만 해당",
          "항소심 판결문의 '원심판결' 항목에 기재된 선고일. 1심 사건은 공란", "확정"),
    Field("appeal_duration", "int", "종속변수(보조)",
          "상소심 소요기간(일)",
          "end_date - prior_judgment_date. 항소심 사건만 계산 가능", "확정",
          missing_value=MISSING_NUM, computed=True),
    Field("sentencing_guideline_type", "cat", "사건특성",
          "대법원 양형기준상 유형 (디지털성범죄 > 03. 허위영상물 등의 반포 등)",
          "1=제1유형(편집 등), 2=제2유형(반포 등), 3=제3유형(영리 목적 반포 등), 9=판결문 미기재",
          "확정",
          choices={1: "제1유형", 2: "제2유형", 3: "제3유형", 9: "미기재"},
          missing_value=MISSING_CAT),
    Field("guideline_min_months", "int", "양형기준",
          "대법원 양형기준 권고형 범위의 하한(월)",
          "판결문 '양형기준에 따른 권고형의 범위'의 하한. "
          "규칙2: 허위영상물 유형만 코딩. 다수범죄 처리기준은 multi_offense_*로 별도 기록",
          "확정", missing_value=MISSING_NUM),
    Field("guideline_max_months", "int", "양형기준",
          "대법원 양형기준 권고형 범위의 상한(월)",
          "동상", "확정", missing_value=MISSING_NUM),
    Field("guideline_area", "cat", "양형기준",
          "권고영역",
          "1=감경영역, 2=기본영역, 3=가중영역, 9=판결문 미기재", "확정",
          choices={1: "감경영역", 2: "기본영역", 3: "가중영역", 9: "미기재"},
          missing_value=MISSING_CAT),
    Field("multi_offense_min_months", "int", "양형기준(참고)",
          "다수범죄 처리기준 권고형 하한(월)",
          "'다수범죄 처리기준에 따른 권고형의 범위' 기록. rel_position 계산에는 사용 안 함(규칙 2)",
          "확정", missing_value=MISSING_NUM),
    Field("multi_offense_max_months", "int", "양형기준(참고)",
          "다수범죄 처리기준 권고형 상한(월)",
          "상한 미제시(예: '5년 이상') 시 -99", "확정", missing_value=MISSING_NUM),
    Field("area_min_months", "int", "양형기준",
          "적용된 형량영역(감경/기본/가중)의 하한(월)",
          "'[권고영역 및 권고형의 범위] 기본영역, 징역 6월~1년 6월'처럼 영역과 범위가 함께 기재된 경우 그 영역의 하한",
          "확정", missing_value=MISSING_NUM),
    Field("area_max_months", "int", "양형기준",
          "적용된 형량영역의 상한(월)",
          "동상", "확정", missing_value=MISSING_NUM),
    Field("aggravating_factors", "int", "양형기준",
          "특별양형인자 가중요소 개수",
          "'[특별양형인자] 가중요소:'의 개수. 없으면 0. 규칙2 준수", "확정",
          missing_value=MISSING_NUM),
    Field("mitigating_factors", "int", "양형기준",
          "특별양형인자 감경요소 개수",
          "'[특별양형인자] 감경요소:'의 개수. 없으면 0. 규칙2 준수", "확정",
          missing_value=MISSING_NUM),
    Field("guideline_deviation", "cat", "종속변수(핵심2)",
          "양형기준 권고범위 이탈 여부(진정이탈)",
          "sentence_months가 guideline_min~max 밖이면 1, 내면 0, 미기재 9",
          "확정",
          choices={0: "범위내", 1: "진정이탈", 9: "미기재"},
          missing_value=MISSING_CAT, computed=True),
    Field("deviation_direction", "cat", "종속변수(핵심2)",
          "이탈 유형 (김한균, 2014)",
          "0=범위내 중간, 1=진정하향, 2=진정상향, 3=부진정하향(rel_position≤0.15), "
          "4=부진정상향(≥0.85), 9=판단불가/미기재",
          "확정",
          choices={0: "범위내 중간", 1: "진정하향", 2: "진정상향",
                   3: "부진정하향", 4: "부진정상향", 9: "판단불가"},
          missing_value=MISSING_CAT, computed=True),
    Field("guideline_rel_position", "float", "종속변수(핵심2)",
          "권고형량범위 전체 기준 상대위치 (0=하한, 1=상한)",
          "(sentence_months - guideline_min) / (guideline_max - guideline_min)",
          "확정", computed=True),
    Field("area_rel_position", "float", "종속변수(핵심2)",
          "적용 영역 기준 상대위치 (0=영역하한, 1=영역상한)",
          "(sentence_months - area_min) / (area_max - area_min)",
          "확정", computed=True),
    Field("forensic_evidence", "cat", "사건특성",
          "디지털포렌식 감정 실시 여부",
          "0=없음, 1=실시", "확정",
          choices={0: "없음", 1: "실시"}, missing_value=MISSING_CAT),
    Field("distribution_purpose_established", "cat", "사건특성",
          "'반포 등을 할 목적으로' 요건 인정 여부 (한민경 2024)",
          "0=불인정/쟁점없음, 1=법원이 반포목적 인정. 무죄 사유가 이 요건 불충족인 경우 반드시 0",
          "가설(파일럿검증)",
          choices={0: "불인정/쟁점없음", 1: "인정"}, missing_value=MISSING_CAT),
    Field("fabrication_suspected_unconfirmed", "cat", "사건특성",
          "합성·편집이 의심되나 유죄로 확정되지 않은 사건 여부",
          "0=쟁점없음/정상확정, 1=판결문에 '합성 의심되나 증거불충분' 등 기재",
          "가설(파일럿검증)",
          choices={0: "쟁점없음", 1: "의심-미확정"}, missing_value=MISSING_CAT),
    Field("offender_age", "int", "가해자",
          "가해자 연령",
          "실수(만 나이). 미기재 시 -99", "확정", missing_value=MISSING_NUM),
    Field("offender_gender", "cat", "가해자",
          "가해자 성별",
          "0=남성, 1=여성. 미기재 시 -99(inferred_vars 활용)", "확정",
          choices={0: "남성", 1: "여성"}, missing_value=MISSING_CAT),
    Field("prior_record", "cat", "가해자",
          "전과 여부",
          "0=없음, 1=동종전과, 2=이종전과", "확정",
          choices={0: "없음", 1: "동종전과", 2: "이종전과"},
          missing_value=MISSING_CAT),
    Field("num_codefendants", "int", "가해자",
          "공동피고인 수",
          "단독범=0, 정수", "확정", missing_value=MISSING_NUM),
    Field("num_victims", "int", "피해자",
          "피해자 수",
          "정수 (다수 불특정 시 별도 처리)", "확정", missing_value=MISSING_NUM),
    Field("victim_relationship", "cat", "피해자",
          "가해자-피해자 관계",
          "1=지인,2=학교동급생,3=유명인,4=불특정,9=확인불가", "확정",
          choices={1: "지인", 2: "학교동급생", 3: "유명인",
                   4: "불특정", 9: "확인불가"},
          missing_value=MISSING_CAT),
    Field("victim_minor", "cat", "피해자",
          "미성년 피해자 포함 여부",
          "0=성인만, 1=미성년 포함", "확정",
          choices={0: "성인만", 1: "미성년 포함"}, missing_value=MISSING_CAT),
    Field("unidentified_victims_exist", "cat", "피해자",
          "미특정 다수 피해자 존재 여부",
          "0=없음(고소인만), 1=있음", "가설(파일럿검증)",
          choices={0: "없음", 1: "있음"}, missing_value=MISSING_CAT),
    Field("relationship_power_dynamic", "cat", "피해자",
          "가해자-피해자 관계의 위계적 성격 (Tittle 1995)",
          "0=대등, 1=가해자 우월적 지위, 9=불명확", "가설(파일럿검증)",
          choices={0: "대등", 1: "가해자 우월", 9: "불명확"},
          missing_value=MISSING_CAT),
    Field("act_type", "cat", "사건특성",
          "행위 유형",
          "1=제작만, 2=제작+유포, 3=유포만(재유포), 4=소지·시청만, "
          "5=영리목적 반포(제14조의2 제3항)", "확정",
          choices={1: "제작만", 2: "제작+유포", 3: "유포만(재유포)",
                   4: "소지·시청만", 5: "영리목적 반포"},
          missing_value=MISSING_CAT),
    Field("platform", "cat", "사건특성",
          "유통 플랫폼",
          "1=텔레그램,2=디스코드,3=기타SNS,4=온라인커뮤니티,"
          "5=해외성인사이트,9=확인불가", "확정",
          choices={1: "텔레그램", 2: "디스코드", 3: "기타SNS",
                   4: "온라인커뮤니티", 5: "해외성인사이트", 9: "확인불가"},
          missing_value=MISSING_CAT),
    Field("deletion_compliance", "cat", "사건특성",
          "삭제 이행 여부",
          "0=언급없음,1=자발적삭제,2=불이행", "확정",
          choices={0: "언급없음", 1: "자발적삭제", 2: "불이행"},
          missing_value=MISSING_CAT),
    Field("digital_guardianship", "cat", "사건특성",
          "피해자의 디지털 보호요인 존재 여부",
          "0=부재(SNS 전체공개, 인지못함), 1=존재(비공개계정임에도 유출 등). "
          "판결문에 언급 없으면 -99", "가설(파일럿검증)",
          choices={0: "부재", 1: "존재"}, missing_value=MISSING_NUM),
    Field("law_period", "cat", "법적맥락",
          "법 개정 시점 구분",
          "1=2020.3 이전, 2=2020.3~2024.9, 3=2024.9 이후", "확정",
          choices={1: "2020.3 이전", 2: "2020.3~2024.9", 3: "2024.9 이후"},
          missing_value=MISSING_CAT, computed=True),
    Field("court_region", "text", "법원",
          "관할법원 지역",
          "수도권/광역시/기타 (텍스트)", "확정"),
    Field("instance", "cat", "법원",
          "심급",
          "1=1심, 2=항소심, 3=상고심", "확정",
          choices={1: "1심", 2: "항소심", 3: "상고심"},
          missing_value=MISSING_CAT),
    Field("inferred_vars", "text", "관리",
          "추론 코딩된 변수명 목록 (규칙 1)",
          "간접 정황으로 추론 코딩한 변수명을 쉼표 구분. 없으면 공란", "확정"),
    Field("coder_id", "text", "관리",
          "코딩 담당자",
          "신뢰도 검증용 식별자", "확정"),
    Field("coding_note", "text", "관리",
          "코딩 비고",
          "결측/모호 사례 사유 및 규칙 적용 근거 기재", "확정"),
]


FIELDS_BY_NAME: dict[str, Field] = {f.name: f for f in FIELDS}


def is_hypothetical(name: str) -> bool:
    f = FIELDS_BY_NAME.get(name)
    return bool(f and f.status.startswith("가설"))


def coded_fields() -> list[Field]:
    """Fields that a coder or the extractor actually assigns
    (excludes computed and management-only fields)."""
    excluded = {"case_id", "coder_id", "inferred_vars", "coding_note"}
    return [f for f in FIELDS if not f.computed and f.name not in excluded]
