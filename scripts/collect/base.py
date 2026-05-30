"""
공통 유틸리티 — HTTP 요청, RSS 파싱, 결과 데이터 구조 정의
"""
from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from typing import Optional

import feedparser
import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}

REQUEST_TIMEOUT = 10
RETRY_COUNT = 2
RETRY_DELAY = 2.0


@dataclass
class RawItem:
    """수집된 원시 데이터 한 건"""
    title: str
    url: str
    source: str
    published: str = ""
    summary: str = ""
    content: str = ""
    tags: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.source}] {self.title}"


def fetch(url: str, **kwargs) -> Optional[requests.Response]:
    """재시도 포함 HTTP GET"""
    for attempt in range(RETRY_COUNT + 1):
        try:
            resp = requests.get(
                url, headers=HEADERS, timeout=REQUEST_TIMEOUT, **kwargs
            )
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            if attempt < RETRY_COUNT:
                time.sleep(RETRY_DELAY)
            else:
                logging.getLogger(__name__).warning("fetch 실패 [%s]: %s", url, e)
    return None


def parse_rss(url: str, source_name: str, limit: int = 10) -> list[RawItem]:
    """RSS/Atom 피드 파싱"""
    log = logging.getLogger(__name__)
    log.info("RSS 수집: %s", url)

    feed = feedparser.parse(url)
    items: list[RawItem] = []

    for entry in feed.entries[:limit]:
        content = ""
        if hasattr(entry, "content"):
            content = BeautifulSoup(
                entry.content[0].value, "lxml"
            ).get_text(separator="\n", strip=True)
        elif hasattr(entry, "summary"):
            content = BeautifulSoup(
                entry.summary, "lxml"
            ).get_text(separator="\n", strip=True)

        tags = [t.term for t in getattr(entry, "tags", [])]

        items.append(
            RawItem(
                title=entry.get("title", "").strip(),
                url=entry.get("link", ""),
                source=source_name,
                published=entry.get("published", ""),
                summary=content[:300],
                content=content,
                tags=tags,
            )
        )

    log.info("  → %d건 수집", len(items))
    return items


def parse_html(url: str, source_name: str, item_selector: str,
               title_selector: str, link_selector: str,
               summary_selector: str = "", limit: int = 10) -> list[RawItem]:
    """HTML 페이지 스크래핑"""
    log = logging.getLogger(__name__)
    log.info("HTML 수집: %s", url)

    resp = fetch(url)
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    items: list[RawItem] = []

    for el in soup.select(item_selector)[:limit]:
        title_el = el.select_one(title_selector)
        link_el  = el.select_one(link_selector)
        summary_el = el.select_one(summary_selector) if summary_selector else None

        if not title_el:
            continue

        title = title_el.get_text(strip=True)
        href  = link_el.get("href", "") if link_el else ""
        if href and not href.startswith("http"):
            from urllib.parse import urljoin
            href = urljoin(url, href)

        summary = summary_el.get_text(strip=True) if summary_el else ""

        items.append(
            RawItem(
                title=title,
                url=href,
                source=source_name,
                summary=summary[:300],
            )
        )

    log.info("  → %d건 수집", len(items))
    return items
