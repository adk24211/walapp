"""
공공·1차 출처 수집기 — 대한민국 정책브리핑(korea.kr) policy.xml 단일 피드.

저작권 안전성:
- korea.kr 자료는 공공누리(제1유형: 출처표시)로, 출처만 밝히면 자유 이용이 가능합니다.
- 언론사 기사가 아닌 정부 1차 발표 자료이므로 저작권/구글 정책(scaled content) 리스크가 낮습니다.

분류:
- 하나의 정책 피드를 키워드로 국내정책 / 청년정책 / 통계·생활정보 3개 카테고리로 나눕니다.
- 분류 우선순위: 청년 → 통계·생활 → (나머지) 국내정책
"""
from __future__ import annotations

import logging
from functools import lru_cache

from .base import RawItem, parse_rss

log = logging.getLogger(__name__)

POLICY_FEED = "https://www.korea.kr/rss/policy.xml"
FEED_LIMIT = 40  # 분류 후 카테고리별로 추리기 위해 넉넉히 수집

# 청년 정책 키워드 (가장 먼저 분류)
YOUTH_KEYWORDS = [
    "청년", "대학생", "취업준비", "구직", "내일채움", "청년도약", "청년미래",
    "장학", "등록금", "월세 지원", "청년주택", "신혼", "사회초년생", "인턴",
]

# 통계·생활정보 키워드 (청년에 안 걸린 항목 중에서)
DATA_KEYWORDS = [
    "통계", "물가", "소비자물가", "고용동향", "지표", "지수", "인구", "출생",
    "가구", "소득", "금리", "환율", "수출", "수입", "성장률", "조사 결과",
    "발표", "현황", "전망", "동향", "요금", "공공요금", "전기요금", "건강보험",
    "연금", "복지", "바우처", "안전", "재난", "기상", "폭염", "한파",
]


def _match(item: RawItem, keywords: list[str]) -> bool:
    text = f"{item.title} {item.summary}"
    return any(kw in text for kw in keywords)


@lru_cache(maxsize=1)
def _fetch_all() -> tuple[RawItem, ...]:
    """policy.xml 을 한 번만 가져와 캐시한다(동일 프로세스 내 재사용)."""
    try:
        items = parse_rss(POLICY_FEED, "대한민국 정책브리핑", FEED_LIMIT)
        log.info("정책브리핑 수집: %d건", len(items))
        return tuple(items)
    except Exception as e:
        log.error("정책브리핑 수집 실패: %s", e)
        return tuple()


def _dedupe(items: list[RawItem], limit: int) -> list[RawItem]:
    seen: set[str] = set()
    out: list[RawItem] = []
    for it in items:
        if it.url in seen:
            continue
        seen.add(it.url)
        out.append(it)
    return out[:limit]


def collect_policy(limit: int = 10) -> list[RawItem]:
    """국내 정책 — 청년/통계로 분류되지 않은 일반 국내 정책."""
    items = [
        it for it in _fetch_all()
        if not _match(it, YOUTH_KEYWORDS) and not _match(it, DATA_KEYWORDS)
    ]
    return _dedupe(items, limit)


def collect_youth(limit: int = 10) -> list[RawItem]:
    """청년 정책 — 청년 키워드가 포함된 항목."""
    items = [it for it in _fetch_all() if _match(it, YOUTH_KEYWORDS)]
    return _dedupe(items, limit)


def collect_data(limit: int = 10) -> list[RawItem]:
    """통계·생활정보 — 청년이 아니면서 통계/생활 키워드가 포함된 항목."""
    items = [
        it for it in _fetch_all()
        if not _match(it, YOUTH_KEYWORDS) and _match(it, DATA_KEYWORDS)
    ]
    return _dedupe(items, limit)


if __name__ == "__main__":
    for name, fn in (("국내정책", collect_policy), ("청년정책", collect_youth), ("통계·생활", collect_data)):
        rows = fn()
        print(f"\n=== {name}: {len(rows)}건 ===")
        for r in rows:
            print("  •", r.title[:45])
