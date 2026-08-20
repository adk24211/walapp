"""② 큐 산출 — 발행 후보에 우선순위를 매긴다.

RSS 최신순 선택을 버리고 이 큐로 대체하는 것이 컨셉 전환의 핵심이다.
"오늘 올라온 것" 이 아니라 "사람들이 가장 많이 찾는 것" 순으로 발행한다.

인기 순서의 근거는 추정이 아니라 **원천이 주는 실제 조회수**다.
  · 보조금24        `조회수`
  · 중앙부처복지서비스 `inqNum`
두 값은 스케일이 달라 직접 비교하면 안 된다. 소스별 백분위로 정규화한 뒤 섞는다.

모듈명이 `queue` 가 아닌 이유: scripts/ 가 sys.path 에 들어가므로 표준 라이브러리
`queue` 를 가려 버린다(urllib3 등이 이를 import 한다). 이름을 비켜 둔다.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date

import taxonomy
from schema import STATUS_ACTIVE, STATUS_UPCOMING, ProgramRecord

log = logging.getLogger(__name__)

# 가중치 — 합 100. 조회수가 가장 크다: "사람들이 가장 많이 찾는 정책 순서" 가
# 발행 순서의 1순위 기준이라는 것이 확정 사항이다.
W_POPULAR = 45     # 원천 조회수 (소스별 백분위)
W_REGION = 20      # 전국일수록 검색 수요가 크다
W_AUDIENCE = 15    # 대상이 넓을수록
W_DEADLINE = 12    # 마감이 가까울수록 지금 알려야 한다
W_FRESH = 8        # 최근 신설

# 대상별 검색 수요 추정치 (0~1). 조회수가 없는 소스를 위한 보조 신호다.
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

# 조회수를 주지 않는 소스(목 데이터 등)의 기본 백분위. 0 을 주면 그 소스 전체가
# 큐 바닥에 깔려 다른 신호가 무의미해지므로 중립값을 쓴다.
NEUTRAL_PERCENTILE = 0.5


def popularity(records: list[ProgramRecord]) -> dict[str, float]:
    """레코드별 인기 백분위 0~1. **소스 안에서만** 순위를 매긴다.

    보조금24 조회수는 수십만 단위, 복지로 inqNum 은 수천 단위다. 원값을 그대로
    비교하면 보조금24가 큐를 통째로 차지한다.

    순위는 '서로 다른 조회수 값' 기준이다. 조회수 분포는 상위 몇 건이 극단적으로
    높은 꼬리 분포라, 건수 기준으로 나누면 중하위권이 모두 0 근처로 뭉갠다.
    """
    by_source: dict[str, list[ProgramRecord]] = defaultdict(list)
    for record in records:
        by_source[record.source].append(record)

    out: dict[str, float] = {}
    for source, group in by_source.items():
        values = sorted({r.view_count for r in group if r.view_count > 0})
        if not values:
            log.info("조회수 없음 [%s] — 중립값 %.1f 로 둡니다.", source, NEUTRAL_PERCENTILE)
            for record in group:
                out[record.id] = NEUTRAL_PERCENTILE
            continue
        span = max(len(values) - 1, 1)
        rank = {value: index / span for index, value in enumerate(values)}
        for record in group:
            out[record.id] = rank.get(record.view_count, 0.0)
    return out


def score(record: ProgramRecord, today: date, percentile: float) -> tuple[float, str]:
    """우선순위 점수와 그 근거."""
    reasons: list[str] = []

    # ① 인기도 — 원천 조회수 백분위
    if percentile >= 0.9:
        reasons.append("top_viewed")

    # ② 지역 범위
    scope = record.region.scope
    region_factor = {taxonomy.REGION_NATIONAL: 1.0, "sido": 0.6}.get(scope, 0.3)
    if scope == taxonomy.REGION_NATIONAL:
        reasons.append("national")

    # ③ 대상 범위
    if record.audiences:
        audience_factor = max(_AUDIENCE_WEIGHT.get(a, 0.4) for a in record.audiences)
        top = max(record.audiences, key=lambda a: _AUDIENCE_WEIGHT.get(a, 0.4))
        reasons.append(f"audience:{top}")
    else:
        audience_factor = 0.4

    # ④ 마감 예정도
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

    # ⑤ 신설 여부 — 접수 시작이 최근 30일 이내
    fresh_factor = 0.0
    if record.apply_period.start:
        try:
            started = (today - date.fromisoformat(record.apply_period.start)).days
            if 0 <= started <= 30:
                fresh_factor = 1.0
                reasons.append("new")
        except ValueError:
            pass

    total = (
        W_POPULAR * percentile
        + W_REGION * region_factor
        + W_AUDIENCE * audience_factor
        + W_DEADLINE * deadline_factor
        + W_FRESH * fresh_factor
    )
    return round(total, 1), "+".join(reasons) or "baseline"


def build(records: list[ProgramRecord], today: date) -> dict:
    """발행 후보를 점수순으로 정렬한 큐 payload."""
    percentiles = popularity(records)
    scored = []
    for record in records:
        percentile = percentiles.get(record.id, NEUTRAL_PERCENTILE)
        value, reason = score(record, today, percentile)
        scored.append({
            "id": record.id,
            "name": record.name,
            "category": record.category,
            # 테마별 1건 선정에 쓰는 축. 대표 테마가 비면 어떤 테마에도 배정되지 않는다.
            "audience": record.primary_audience,
            "status": record.status,
            "views": record.view_count,
            "percentile": round(percentile, 3),
            "score": value,
            "reason": reason,
        })
    scored.sort(key=lambda item: (-item["score"], item["id"]))

    log.info("큐 산출: %d건 (최고 %.1f점)", len(scored), scored[0]["score"] if scored else 0)
    return {"generated_at": today.isoformat(), "pending": scored}


# ─────────────────────────────────────────────────────────────
#  선정
# ─────────────────────────────────────────────────────────────
def take_by_theme(
    queue_payload: dict,
    records: dict[str, ProgramRecord],
    themes: tuple[str, ...],
    per_theme: int = 1,
) -> list[ProgramRecord]:
    """오늘 조에 속한 테마별로 상위 `per_theme` 건씩 꺼낸다 (시행중만).

    한 제도는 대표 테마 한 곳에서만 뽑힌다. 청년·구직자 양쪽에 걸친 제도가
    두 번 발행되는 일을 여기서 막는다. (taxonomy.pick_primary_audience)

    테마에 후보가 없으면 그 자리는 그냥 빈다. 다른 테마 것으로 채우지 않는다 —
    '테마마다 하루 1건' 이라는 약속이 무너지고, 인기 테마만 계속 쌓인다.
    """
    picked: list[ProgramRecord] = []
    counts: dict[str, int] = {theme: 0 for theme in themes}

    for item in queue_payload.get("pending", []):
        if item.get("status") != STATUS_ACTIVE:
            continue
        theme = item.get("audience")
        if theme not in counts or counts[theme] >= per_theme:
            continue
        record = records.get(item["id"])
        if record is None:
            continue
        counts[theme] += 1
        picked.append(record)
        if all(count >= per_theme for count in counts.values()):
            break

    empty = [t for t, c in counts.items() if c == 0]
    if empty:
        labels = ", ".join(taxonomy.AUDIENCES.get(t, {}).get("label", t) for t in empty)
        log.info("후보가 없어 건너뛴 테마: %s", labels)
    return picked


def take_upcoming(
    queue_payload: dict,
    records: dict[str, ProgramRecord],
    limit: int = 1,
) -> list[ProgramRecord]:
    """시행 예정 제도 상위 `limit` 건.

    없으면 빈 리스트다. 억지로 채우지 않는다 — 예정 발행은 '있으면 하루 1건'
    이지 매일 반드시 한 건이 아니다. (사용자 확정 사항)
    """
    picked: list[ProgramRecord] = []
    for item in queue_payload.get("pending", []):
        if item.get("status") != STATUS_UPCOMING:
            continue
        record = records.get(item["id"])
        if record is None:
            continue
        picked.append(record)
        if len(picked) >= limit:
            break
    return picked


def take(queue_payload: dict, records: dict[str, ProgramRecord], limit: int) -> list[ProgramRecord]:
    """큐 상단에서 limit 건을 꺼낸다. 레코드가 없는 항목은 건너뛴다.

    테마 배분을 무시하는 단순 상위 선택이다. 초기 백필처럼 테마 균형보다
    총량이 중요할 때 쓴다 (PUBLISH_MODE=top).
    """
    picked: list[ProgramRecord] = []
    for item in queue_payload.get("pending", []):
        record = records.get(item["id"])
        if record is None:
            continue
        picked.append(record)
        if len(picked) >= limit:
            break
    return picked
