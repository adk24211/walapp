"""
공통 유틸리티 — HTTP 요청, RSS 파싱, 결과 데이터 구조 정의
"""
from __future__ import annotations

import re
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


def normalize_title(title: str) -> str:
    """중복 판별용 제목 정규화 키 생성.

    - Google News 형식 '제목 - 매체명'에서 끝의 매체명 제거
    - 공백·문장부호 제거 후 소문자화 → 표기가 조금 달라도 같은 기사 검출
    """
    import re as _re
    t = (title or "").strip()
    if " - " in t:
        t = t.rsplit(" - ", 1)[0]
    return _re.sub(r"[\s\W_]+", "", t).lower()


def dedupe_by_title(items: list["RawItem"]) -> list["RawItem"]:
    """정규화된 제목 기준 중복 제거 (앞선 항목 우선)."""
    seen: set[str] = set()
    unique: list[RawItem] = []
    for item in items:
        key = normalize_title(item.title)
        if key and key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


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


# 기사 본문이 들어있을 가능성이 높은 컨테이너 후보 (korea.kr 등 정부 사이트 우선)
_ARTICLE_SELECTORS = [
    "#article_body", ".article_body", ".view_cont", ".view_con", ".cont_body",
    "#contentArea", ".article-cont", ".article_cont", ".news_cont", ".board_view",
    "article",
]
_NOISE_RE = re.compile(
    r"(저작권|무단\s*전재|재배포\s*금지|공공누리|배너|관련기사|이전글|다음글|"
    r"목록|프린트|페이스북|트위터|카카오|이메일|구독|뉴스레터)"
)


def fetch_article_text(url: str, max_chars: int = 1800) -> str:
    """기사 URL에서 본문 텍스트를 추출한다.

    RSS 요약(teaser)만으로는 LLM이 받을 정보가 빈약하므로, 실제 기사 페이지에서
    본문 단락을 받아와 생성 품질(정보량)을 높인다. 추출 실패 시 빈 문자열 반환.
    """
    if not url or not url.startswith("http"):
        return ""
    resp = fetch(url)
    if resp is None:
        return ""

    soup = BeautifulSoup(resp.text, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()

    node = None
    for sel in _ARTICLE_SELECTORS:
        cand = soup.select_one(sel)
        if cand and len(cand.get_text(strip=True)) > 250:
            node = cand
            break

    if node is not None:
        paras = [p.get_text(" ", strip=True) for p in node.find_all(["p", "li"])]
        if not paras:
            paras = [node.get_text("\n", strip=True)]
    else:
        # 폴백: 페이지 전체에서 의미 있는 길이의 <p> 단락만 수집
        paras = [
            p.get_text(" ", strip=True)
            for p in soup.find_all("p")
            if len(p.get_text(strip=True)) > 30
        ]

    # 노이즈 단락 제거 + 중복 정리
    clean: list[str] = []
    seen: set[str] = set()
    for p in paras:
        p = re.sub(r"\s{2,}", " ", p).strip()
        if len(p) < 15 or _NOISE_RE.search(p):
            continue
        if p in seen:
            continue
        seen.add(p)
        clean.append(p)

    text = "\n".join(clean).strip()
    return text[:max_chars]


def parse_rss(url: str, source_name: str, limit: int = 10) -> list[RawItem]:
    """RSS/Atom 피드 파싱

    feedparser.parse(url)를 직접 쓰면 feedparser 기본 봇 User-Agent로 요청하게 돼
    한국 정부·기업 사이트가 차단하는 경우가 많다. 따라서 브라우저 헤더를 가진
    fetch()로 먼저 본문을 받아온 뒤 그 내용을 파싱한다.
    """
    log = logging.getLogger(__name__)
    log.info("RSS 수집: %s", url)

    resp = fetch(url)
    if resp is None:
        log.info("  → 0건 수집 (응답 없음)")
        return []

    feed = feedparser.parse(resp.content)
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
