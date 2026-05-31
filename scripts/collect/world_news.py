"""
해외 핫뉴스 수집기 — 공신력 있는 해외 매체의 '오늘의 주요 뉴스'
- Google News (World, 주요뉴스 — 신뢰 매체 기사를 중요도순 집계)
- BBC News (World)
- Al Jazeera / CNN (World)
영문 기사이며, 포스트 생성 단계에서 한국어 기사체로 번역·요약된다.
"""
from __future__ import annotations

import logging
from .base import RawItem, parse_rss

log = logging.getLogger(__name__)

SOURCES = [
    {
        "url": "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en",
        "name": "Google News",
        "limit": 20,
    },
    {
        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "name": "BBC",
        "limit": 15,
    },
    {
        "url": "https://www.aljazeera.com/xml/rss/all.xml",
        "name": "Al Jazeera",
        "limit": 10,
    },
]


def collect() -> list[RawItem]:
    """해외 핫뉴스 수집 (중복 제거 후 상위 10건)"""
    log.info("=== 해외 핫뉴스 수집 시작 ===")
    all_items: list[RawItem] = []

    for src in SOURCES:
        try:
            all_items.extend(parse_rss(src["url"], src["name"], src["limit"]))
        except Exception as e:
            log.error("수집 실패 [%s]: %s", src["name"], e)

    # 제목 기준 중복 제거 (앞선 소스 우선)
    seen: set[str] = set()
    unique: list[RawItem] = []
    for item in all_items:
        key = item.title.strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(item)

    log.info("해외 핫뉴스 수집 완료: 전체 %d건 → 중복 제거 %d건", len(all_items), len(unique))
    return unique[:10]


if __name__ == "__main__":
    for r in collect():
        print(f"  • {r.title} [{r.source}]")
