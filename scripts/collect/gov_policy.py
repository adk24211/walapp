"""
정부·청년 정책 수집기
- 복지로 RSS
- 정책브리핑 (청년 카테고리) RSS
- 고용노동부 보도자료 RSS
- 청년정책 포털 (온라인청년센터)
"""
from __future__ import annotations

import logging
from .base import RawItem, parse_rss, parse_html

log = logging.getLogger(__name__)

# 작동 확인된 소스만 유지. (대부분의 한국 정부 RSS는 폐기되었거나 해외 IP를 차단함)
# 정책브리핑(korea.kr)은 정상 작동하며, 청년 키워드 필터로 관련 항목을 추린다.
SOURCES = [
    {
        "type": "rss",
        "name": "정책브리핑",
        "url": "https://www.korea.kr/rss/policy.xml",
        "limit": 20,
    },
]

# 청년 정책 관련 키워드 필터
YOUTH_KEYWORDS = [
    "청년", "월세", "주거", "취업", "창업", "장학", "지원금",
    "내일채움", "청년도약", "고용", "직업훈련", "인턴",
    "소득세", "감면", "바우처",
]


def is_youth_related(item: RawItem) -> bool:
    text = (item.title + item.summary).lower()
    return any(kw in text for kw in YOUTH_KEYWORDS)


def collect() -> list[RawItem]:
    """정부·청년 정책 데이터 수집"""
    log.info("=== 정부·청년 정책 수집 시작 ===")
    all_items: list[RawItem] = []

    for src in SOURCES:
        try:
            if src["type"] == "rss":
                items = parse_rss(src["url"], src["name"], src.get("limit", 10))
            else:
                items = parse_html(**{k: v for k, v in src.items() if k != "type"})
            all_items.extend(items)
        except Exception as e:
            log.error("수집 실패 [%s]: %s", src["name"], e)

    # 청년 관련 항목만 필터링
    filtered = [item for item in all_items if is_youth_related(item)]
    log.info("수집 완료: 전체 %d건 → 청년 관련 %d건", len(all_items), len(filtered))

    # 중복 제거 (URL 기준)
    seen: set[str] = set()
    unique: list[RawItem] = []
    for item in filtered:
        if item.url not in seen:
            seen.add(item.url)
            unique.append(item)

    return unique[:8]  # 최대 8건


if __name__ == "__main__":
    results = collect()
    for r in results:
        print(f"  • {r.title} [{r.source}]")
