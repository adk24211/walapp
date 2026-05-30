"""
개발자 채용 & 기술 스택 동향 수집기
- 원티드 개발 직군 RSS
- 점핏 RSS
- GitHub Trending (Python 스크래핑)
- Hacker News Who's Hiring (월별)
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from .base import RawItem, parse_rss, parse_html, fetch
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# 원티드 개발 카테고리 RSS
WANTED_RSS_URLS = [
    ("https://www.wanted.co.kr/jobsfeed/rss?job_category_id=518", "원티드-백엔드"),
    ("https://www.wanted.co.kr/jobsfeed/rss?job_category_id=672", "원티드-프론트엔드"),
    ("https://www.wanted.co.kr/jobsfeed/rss?job_category_id=655", "원티드-AI/ML"),
    ("https://www.wanted.co.kr/jobsfeed/rss?job_category_id=669", "원티드-데이터"),
]

# 기타 채용 플랫폼 RSS
JOB_RSS_URLS = [
    ("https://www.saramin.co.kr/zf_user/rss", "사람인"),
    ("https://rss.jobkorea.co.kr/rss/it", "잡코리아-IT"),
    ("https://career.programmers.co.kr/job/rss", "프로그래머스"),
]

# 주목할 기술 스택 키워드
HOT_STACKS = {
    "AI/ML": ["LLM", "RAG", "파인튜닝", "PyTorch", "LangChain", "Hugging Face", "AI 엔지니어"],
    "시스템": ["Rust", "Go", "golang", "C++"],
    "백엔드": ["Spring", "Django", "FastAPI", "Node.js", "NestJS", "Kotlin"],
    "프론트": ["React", "Next.js", "TypeScript", "Vue", "Svelte"],
    "인프라": ["Kubernetes", "k8s", "Docker", "AWS", "GCP", "Terraform"],
    "데이터": ["Spark", "Kafka", "Airflow", "dbt", "Flink"],
}


def collect_wanted() -> list[RawItem]:
    """원티드 채용 공고 수집"""
    items: list[RawItem] = []
    for url, name in WANTED_RSS_URLS:
        try:
            result = parse_rss(url, name, limit=6)
            items.extend(result)
        except Exception as e:
            log.warning("원티드 수집 실패 [%s]: %s", name, e)
    return items


def collect_jumpit() -> list[RawItem]:
    """점핏 채용 공고 수집"""
    try:
        return parse_rss(
            "https://www.jumpit.co.kr/rss",
            "점핏",
            limit=10,
        )
    except Exception as e:
        log.warning("점핏 수집 실패: %s", e)
        return []


def collect_other_boards() -> list[RawItem]:
    """사람인·잡코리아·프로그래머스 등 기타 채용 플랫폼 수집"""
    items: list[RawItem] = []
    for url, name in JOB_RSS_URLS:
        try:
            items.extend(parse_rss(url, name, limit=6))
        except Exception as e:
            log.warning("채용 수집 실패 [%s]: %s", name, e)
    return items


def collect_github_trending() -> list[RawItem]:
    """GitHub Trending 스크래핑"""
    log.info("GitHub Trending 수집 중...")
    resp = fetch("https://github.com/trending?since=weekly&spoken_language_code=")
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    items: list[RawItem] = []

    for repo_el in soup.select("article.Box-row")[:10]:
        name_el  = repo_el.select_one("h2 a")
        desc_el  = repo_el.select_one("p")
        lang_el  = repo_el.select_one("[itemprop='programmingLanguage']")
        stars_el = repo_el.select_one(".f6 .octicon-star")

        if not name_el:
            continue

        name    = name_el.get_text(strip=True).replace("\n", "").replace(" ", "")
        desc    = desc_el.get_text(strip=True) if desc_el else ""
        lang    = lang_el.get_text(strip=True) if lang_el else ""
        stars_text = ""
        if stars_el and stars_el.parent:
            stars_text = stars_el.parent.get_text(strip=True)

        items.append(
            RawItem(
                title=name,
                url=f"https://github.com/{name}",
                source="GitHub Trending",
                summary=desc[:200],
                tags=[lang] if lang else [],
                extra={"stars": stars_text},
            )
        )

    log.info("  → GitHub Trending %d건", len(items))
    return items


def extract_stack_tags(items: list[RawItem]) -> dict[str, int]:
    """수집된 채용 공고에서 기술 스택 빈도 추출"""
    counts: dict[str, int] = {}
    all_text = " ".join(f"{i.title} {i.summary}" for i in items)

    for category, keywords in HOT_STACKS.items():
        for kw in keywords:
            count = len(re.findall(re.escape(kw), all_text, re.IGNORECASE))
            if count > 0:
                counts[kw] = counts.get(kw, 0) + count

    return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))


def collect() -> tuple[list[RawItem], dict[str, int]]:
    """
    개발자 채용 데이터 수집
    Returns:
        (채용 공고 목록, 기술 스택 빈도)
    """
    log.info("=== 개발자 채용 수집 시작 ===")

    job_items: list[RawItem] = []
    job_items.extend(collect_wanted())
    job_items.extend(collect_jumpit())
    job_items.extend(collect_other_boards())

    trend_items = collect_github_trending()

    # 기술 스택 빈도 분석
    stack_counts = extract_stack_tags(job_items)
    log.info("기술 스택 TOP5: %s", list(stack_counts.items())[:5])

    # 중복 제거
    seen: set[str] = set()
    unique_jobs: list[RawItem] = []
    for item in job_items:
        key = item.title + item.source
        if key not in seen:
            seen.add(key)
            unique_jobs.append(item)

    log.info("채용 공고: %d건, GitHub Trending: %d건", len(unique_jobs), len(trend_items))

    # 채용 + 트렌딩을 합쳐서 반환 (generate_post에서 구분해서 사용)
    all_items = unique_jobs[:12] + trend_items[:8]
    return all_items, stack_counts


if __name__ == "__main__":
    items, stacks = collect()
    print("\n채용 공고:")
    for i in items[:5]:
        print(f"  • {i.title} [{i.source}]")
    print("\n기술 스택 TOP10:")
    for k, v in list(stacks.items())[:10]:
        print(f"  {k}: {v}건")
