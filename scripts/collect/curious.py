"""
흥미로운 발견 수집기 — 신기·미스터리·재미·신기술 등 '읽는 재미'가 있는 소재
- ScienceAlert / LiveScience / IFLScience (과학·자연·우주의 흥미로운 발견)
- Smithsonian Magazine (역사·문화·미스터리)
- MIT Technology Review (신기술)
영문 소재이며, 포스트 생성 단계에서 한국어로 번역·재구성된다.
"""
from __future__ import annotations

import logging
from .base import RawItem, parse_rss, dedupe_by_title

log = logging.getLogger(__name__)

SOURCES = [
    {
        "url": "https://www.sciencealert.com/feed",
        "name": "ScienceAlert",
        "limit": 10,
    },
    {
        "url": "https://www.livescience.com/feeds/all",
        "name": "LiveScience",
        "limit": 10,
    },
    {
        "url": "https://www.sciencedaily.com/rss/all.xml",
        "name": "ScienceDaily",
        "limit": 10,
    },
    {
        "url": "https://www.smithsonianmag.com/rss/latest_articles/",
        "name": "Smithsonian",
        "limit": 8,
    },
    {
        "url": "https://www.technologyreview.com/feed/",
        "name": "MIT Tech Review",
        "limit": 8,
    },
]


def collect() -> list[RawItem]:
    """흥미로운 발견 소재 수집 (중복 제거 후 상위 12건)"""
    log.info("=== 흥미로운 발견 수집 시작 ===")
    all_items: list[RawItem] = []

    for src in SOURCES:
        try:
            all_items.extend(parse_rss(src["url"], src["name"], src["limit"]))
        except Exception as e:
            log.error("수집 실패 [%s]: %s", src["name"], e)

    # 정규화 제목 기준 중복 제거
    unique = dedupe_by_title(all_items)

    log.info("흥미로운 발견 수집 완료: 전체 %d건 → 중복 제거 %d건", len(all_items), len(unique))
    return unique[:12]


if __name__ == "__main__":
    for r in collect():
        print(f"  • {r.title} [{r.source}]")
