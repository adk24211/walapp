"""② 큐 산출 — 발행 후보에 우선순위를 매긴다.

RSS 최신순 선택을 버리고 이 큐로 대체하는 것이 컨셉 전환의 핵심이다.
"오늘 올라온 것" 이 아니라 "독자에게 가장 값어치 있는 것" 순으로 발행한다.

모듈명이 `queue` 가 아닌 이유: scripts/ 가 sys.path 에 들어가므로 표준 라이브러리
`queue` 를 가려 버린다(urllib3 등이 이를 import 한다). 이름을 비켜 둔다.
"""
from __future__ import annotations

import logging
from datetime import date

import taxonomy
from schema import ProgramRecord

log = logging.getLogger(__name__)

# 가중치 (REDESIGN.md §4.3)
W_REGION = 30      # 전국일수록 검색 수요가 크다
W_AUDIENCE = 25    # 대상이 넓을수록
W_DEADLINE = 20    # 마감이 가까울수록 지금 알려야 한다
W_FRESH = 15       # 최근 신설
W_NAMING = 10      # 고유명사형 제도명은 지명 검색이 붙는다

# 대상별 검색 수요 추정치 (0~1)
_AUDIENCE_WEIGHT = {
    "youth": 1.0,
    "parent": 0.9,
    "lowincome": 0.8,
    "jobseeker": 0.8,
    "newlywed": 0.7,
    "senior": 0.7,
    "business": 0.6,
    "disabled": 0.5,
}


def score(record: ProgramRecord, today: date) -> tuple[float, str]:
    """우선순위 점수와 그 근거."""
    reasons: list[str] = []

    # ① 지역 범위
    scope = record.region.scope
    region_factor = {taxonomy.REGION_NATIONAL: 1.0, "sido": 0.6}.get(scope, 0.3)
    if scope == taxonomy.REGION_NATIONAL:
        reasons.append("national")

    # ② 대상 범위
    if record.audiences:
        audience_factor = max(_AUDIENCE_WEIGHT.get(a, 0.4) for a in record.audiences)
        top = max(record.audiences, key=lambda a: _AUDIENCE_WEIGHT.get(a, 0.4))
        reasons.append(f"audience:{top}")
    else:
        audience_factor = 0.4

    # ③ 마감 임박도
    days_left = record.apply_period.days_left(today)
    if days_left is None:
        deadline_factor = 0.5           # 상시 접수 — 급하지 않지만 꾸준히 검색된다
    elif days_left < 0:
        deadline_factor = 0.0           # 이미 마감
    elif days_left <= 30:
        deadline_factor = 1.0
        reasons.append("deadline_soon")
    elif days_left <= 90:
        deadline_factor = 0.7
    else:
        deadline_factor = 0.4

    # ④ 신설 여부 — 접수 시작이 최근 30일 이내
    fresh_factor = 0.0
    if record.apply_period.start:
        try:
            started = (today - date.fromisoformat(record.apply_period.start)).days
            if 0 <= started <= 30:
                fresh_factor = 1.0
                reasons.append("new")
        except ValueError:
            pass

    # ⑤ 제도명 형태 — 짧고 고유명사형일수록 지명 검색이 잘 붙는다
    name_len = len(record.name)
    naming_factor = 1.0 if name_len <= 12 else (0.7 if name_len <= 20 else 0.4)

    total = (
        W_REGION * region_factor
        + W_AUDIENCE * audience_factor
        + W_DEADLINE * deadline_factor
        + W_FRESH * fresh_factor
        + W_NAMING * naming_factor
    )
    return round(total, 1), "+".join(reasons) or "baseline"


def build(records: list[ProgramRecord], today: date) -> dict:
    """발행 후보를 점수순으로 정렬한 큐 payload."""
    scored = []
    for record in records:
        value, reason = score(record, today)
        scored.append({
            "id": record.id,
            "name": record.name,
            "category": record.category,
            "score": value,
            "reason": reason,
        })
    scored.sort(key=lambda item: (-item["score"], item["id"]))

    log.info("큐 산출: %d건 (최고 %.1f점)", len(scored), scored[0]["score"] if scored else 0)
    return {"generated_at": today.isoformat(), "pending": scored}


def take(queue_payload: dict, records: dict[str, ProgramRecord], limit: int) -> list[ProgramRecord]:
    """큐 상단에서 limit 건을 꺼낸다. 레코드가 없는 항목은 건너뛴다."""
    picked: list[ProgramRecord] = []
    for item in queue_payload.get("pending", []):
        record = records.get(item["id"])
        if record is None:
            continue
        picked.append(record)
        if len(picked) >= limit:
            break
    return picked
