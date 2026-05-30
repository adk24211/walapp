"""
IT·테크 뉴스 수집기
- GeekNews RSS (한국 HN 계열)
- Bloter RSS
- ZDNet Korea RSS
- Hacker News Top Stories API
- TechCrunch RSS (영문, 요약용)
"""
from __future__ import annotations

import logging
import json
from .base import RawItem, parse_rss, fetch

log = logging.getLogger(__name__)

RSS_SOURCES = [
    {
        "url":   "https://feeds.feedburner.com/geeknews-feed",
        "name":  "GeekNews",
        "limit": 10,
    },
    {
        "url":   "https://news.hada.io/rss/news",
        "name":  "GeekNews(하다)",
        "limit": 10,
    },
    {
        "url":   "https://yozm.wishket.com/magazine/feed/",
        "name":  "요즘IT",
        "limit": 8,
    },
    {
        "url":   "https://www.bloter.net/feed",
        "name":  "Bloter",
        "limit": 8,
    },
    {
        "url":   "https://zdnet.co.kr/rss/latest",
        "name":  "ZDNet Korea",
        "limit": 8,
    },
    {
        "url":   "https://www.itworld.co.kr/rss/all.xml",
        "name":  "ITWorld Korea",
        "limit": 6,
    },
    {
        "url":   "https://byline.network/feed/",
        "name":  "바이라인네트워크",
        "limit": 6,
    },
    {
        "url":   "https://techcrunch.com/feed/",
        "name":  "TechCrunch",
        "limit": 6,
    },
    {
        "url":   "https://feeds.arstechnica.com/arstechnica/technology-lab",
        "name":  "Ars Technica",
        "limit": 5,
    },
    {
        "url":   "https://www.theverge.com/rss/index.xml",
        "name":  "The Verge",
        "limit": 5,
    },
    {
        "url":   "https://www.engadget.com/rss.xml",
        "name":  "Engadget",
        "limit": 5,
    },
]

# 관련도 높은 키워드
TECH_KEYWORDS = [
    "AI", "LLM", "GPT", "Claude", "Gemini", "인공지능",
    "오픈소스", "GitHub", "개발자", "스타트업", "빅테크",
    "애플", "구글", "마이크로소프트", "메타", "아마존",
    "클라우드", "AWS", "보안", "사이버", "반도체", "엔비디아",
]

# 제외 키워드 (광고성, 무관 콘텐츠)
EXCLUDE_KEYWORDS = [
    "경품", "이벤트 당첨", "광고", "PR", "협찬",
]


def collect_hackernews_top() -> list[RawItem]:
    """Hacker News Top Stories API"""
    log.info("Hacker News Top 수집 중...")
    try:
        resp = fetch("https://hacker-news.firebaseio.com/v0/topstories.json")
        if not resp:
            return []

        story_ids = json.loads(resp.text)[:15]
        items: list[RawItem] = []

        for sid in story_ids:
            story_resp = fetch(
                f"https://hacker-news.firebaseio.com/v0/item/{sid}.json"
            )
            if not story_resp:
                continue

            story = json.loads(story_resp.text)
            if story.get("type") != "story":
                continue

            title = story.get("title", "")
            url   = story.get("url", f"https://news.ycombinator.com/item?id={sid}")
            score = story.get("score", 0)
            comments = story.get("descendants", 0)

            items.append(
                RawItem(
                    title=title,
                    url=url,
                    source="Hacker News",
                    summary=f"Points: {score} | Comments: {comments}",
                    extra={"score": score, "comments": comments},
                )
            )

        log.info("  → HN %d건", len(items))
        return items

    except Exception as e:
        log.warning("HN 수집 실패: %s", e)
        return []


def is_relevant(item: RawItem) -> bool:
    """관련도 필터"""
    text = (item.title + item.summary).lower()
    if any(ex.lower() in text for ex in EXCLUDE_KEYWORDS):
        return False
    return True


def score_item(item: RawItem) -> int:
    """관련도 점수 계산 (높을수록 우선)"""
    text = (item.title + item.summary).lower()
    score = 0
    for kw in TECH_KEYWORDS:
        if kw.lower() in text:
            score += 2
    # HN은 점수 반영
    if item.source == "Hacker News":
        score += min(item.extra.get("score", 0) // 50, 10)
    # 한국어 소스 가산
    if item.source in (
        "GeekNews", "GeekNews(하다)", "요즘IT", "Bloter",
        "ZDNet Korea", "ITWorld Korea", "바이라인네트워크",
    ):
        score += 3
    return score


def collect() -> list[RawItem]:
    """IT·테크 뉴스 수집"""
    log.info("=== IT·테크 뉴스 수집 시작 ===")
    all_items: list[RawItem] = []

    for src in RSS_SOURCES:
        try:
            items = parse_rss(src["url"], src["name"], src["limit"])
            all_items.extend(items)
        except Exception as e:
            log.error("RSS 수집 실패 [%s]: %s", src["name"], e)

    # HN Top 추가
    all_items.extend(collect_hackernews_top())

    # 필터 + 스코어 정렬
    filtered = [i for i in all_items if is_relevant(i)]
    filtered.sort(key=score_item, reverse=True)

    # URL 기준 중복 제거
    seen: set[str] = set()
    unique: list[RawItem] = []
    for item in filtered:
        if item.url not in seen:
            seen.add(item.url)
            unique.append(item)

    log.info("수집 완료: 전체 %d건 → 필터 후 %d건", len(all_items), len(unique))
    return unique[:12]


if __name__ == "__main__":
    results = collect()
    for r in results:
        print(f"  • {r.title} [{r.source}]")
