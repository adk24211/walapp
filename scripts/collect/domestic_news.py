"""
국내 핫뉴스 수집기 — 공신력 있는 국내 매체/포털의 '오늘의 주요 뉴스'
- Google News (한국, 주요뉴스 — 신뢰 매체 기사를 중요도순 집계)
- 연합뉴스 (국가기간뉴스통신사)
- 한겨레 / 경향신문 (종합 일간지)
"""
from __future__ import annotations

import logging
from .base import RawItem, parse_rss

log = logging.getLogger(__name__)

SOURCES = [
    {
        "url": "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko",
        "name": "구글뉴스",
        "limit": 20,
    },
    {
        "url": "https://www.yna.co.kr/rss/news.xml",
        "name": "연합뉴스",
        "limit": 15,
    },
    {
        "url": "https://www.hani.co.kr/rss/",
        "name": "한겨레",
        "limit": 10,
    },
]


def collect() -> list[RawItem]:
    """국내 핫뉴스 수집 (중복 제거 후 상위 10건)"""
    log.info("=== 국내 핫뉴스 수집 시작 ===")
    all_items: list[RawItem] = []

    for src in SOURCES:
        try:
            all_items.extend(parse_rss(src["url"], src["name"], src["limit"]))
        except Exception as e:
            log.error("수집 실패 [%s]: %s", src["name"], e)

    # 제목 기준 중복 제거 (앞선 소스 우선 = 구글뉴스 주요뉴스 우선)
    seen: set[str] = set()
    unique: list[RawItem] = []
    for item in all_items:
        key = item.title.strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(item)

    log.info("국내 핫뉴스 수집 완료: 전체 %d건 → 중복 제거 %d건", len(all_items), len(unique))
    return unique[:10]


if __name__ == "__main__":
    for r in collect():
        print(f"  • {r.title} [{r.source}]")
