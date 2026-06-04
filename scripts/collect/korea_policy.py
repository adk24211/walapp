"""
공공·1차 출처 수집기 — 정책/청년/통계 카테고리.

각 카테고리는 '공신력 있는' 소스를 3개 이상 사용한다.
  1) 대한민국 정책브리핑(korea.kr) 공식 RSS — 공공누리(제1유형) 1차 자료
  2~3) Google News RSS 검색을 정부·공공 도메인(site:)으로 스코프한 피드
       → 안정적으로 동작하며, 본문은 원본(공공) 도메인에서 받아 재구성한다.

저작권 안전성: 정부·공공기관 발표 자료의 사실·수치를 취해 직접 재구성·해설한다.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from urllib.parse import quote_plus

from .base import RawItem, parse_rss, fetch_article_text, dedupe_by_title

log = logging.getLogger(__name__)

ENRICH_TOP = 6   # 본문까지 받아올 카테고리별 상위 기사 수
PER_FEED = 12    # 피드당 최대 수집 수


def _gn(query: str) -> str:
    """정부·공공 도메인으로 스코프한 Google News RSS 검색 URL."""
    return (
        "https://news.google.com/rss/search?q="
        + quote_plus(query)
        + "&hl=ko&gl=KR&ceid=KR:ko"
    )


KOREA_POLICY_FEED = "https://www.korea.kr/rss/policy.xml"

# (표시명, URL, 분류필터)
#  - 분류필터 'policy'/'youth'/'data' 는 공용 korea.kr 피드를 키워드로 카테고리에 맞게 거른다.
#  - None 은 이미 주제가 좁혀진 피드(Google News 스코프 검색)라 필터를 적용하지 않는다.
POLICY_FEEDS = [
    ("대한민국 정책브리핑", KOREA_POLICY_FEED, "policy"),
    ("정부 정책뉴스", _gn("정책 OR 제도 when:7d (site:korea.kr OR site:mois.go.kr OR site:moef.go.kr)"), None),
    ("부처 보도자료", _gn("정책 보도자료 when:7d (site:moel.go.kr OR site:mohw.go.kr OR site:moe.go.kr)"), None),
]

YOUTH_FEEDS = [
    ("대한민국 정책브리핑", KOREA_POLICY_FEED, "youth"),
    ("청년정책 통합", _gn("청년 정책 OR 청년 지원금 when:14d (site:korea.kr OR site:youthcenter.go.kr)"), None),
    ("청년 일자리·주거", _gn("청년 일자리 OR 청년 주거 when:14d (site:moel.go.kr OR site:molit.go.kr)"), None),
]

DATA_FEEDS = [
    ("대한민국 정책브리핑", KOREA_POLICY_FEED, "data"),
    ("통계·물가·고용", _gn("통계청 OR 소비자물가 OR 고용동향 when:14d (site:korea.kr OR site:kostat.go.kr)"), None),
    ("경제지표", _gn("금리 OR 수출 OR 경제지표 when:14d (site:bok.or.kr OR site:moef.go.kr)"), None),
]

# 키워드 필터 (공용 korea.kr 피드 분류용)
YOUTH_KEYWORDS = [
    "청년", "대학생", "취업준비", "구직", "내일채움", "청년도약", "청년미래",
    "장학", "등록금", "월세 지원", "청년주택", "신혼", "사회초년생", "인턴",
]
DATA_KEYWORDS = [
    "통계", "물가", "소비자물가", "고용동향", "지표", "지수", "인구", "출생",
    "가구", "소득", "금리", "환율", "수출", "수입", "성장률", "조사 결과",
    "발표", "현황", "전망", "동향", "요금", "공공요금", "전기요금", "건강보험",
    "연금", "복지", "바우처", "안전", "재난", "기상", "폭염", "한파",
]


def _match(item: RawItem, keywords: list[str]) -> bool:
    text = f"{item.title} {item.summary}"
    return any(kw in text for kw in keywords)


def _apply_filter(items: list[RawItem], kind: str | None) -> list[RawItem]:
    if kind == "policy":
        return [i for i in items if not _match(i, YOUTH_KEYWORDS) and not _match(i, DATA_KEYWORDS)]
    if kind == "youth":
        return [i for i in items if _match(i, YOUTH_KEYWORDS)]
    if kind == "data":
        return [i for i in items if not _match(i, YOUTH_KEYWORDS) and _match(i, DATA_KEYWORDS)]
    return items


@lru_cache(maxsize=16)
def _cached_feed(url: str, name: str) -> tuple[RawItem, ...]:
    """피드를 한 번만 받아 캐시(동일 실행 내 공용 피드 재사용)."""
    try:
        return tuple(parse_rss(url, name, PER_FEED))
    except Exception as e:
        log.error("피드 수집 실패 [%s]: %s", name, e)
        return tuple()


@lru_cache(maxsize=256)
def _article_body(url: str) -> str:
    return fetch_article_text(url)


def _enrich(items: list[RawItem]) -> list[RawItem]:
    """상위 기사 본문을 받아와 정보 밀도를 높인다."""
    for it in items[:ENRICH_TOP]:
        body = _article_body(it.url)
        if body and len(body) > len(it.content):
            it.content = body
            if len(it.summary) < 120:
                it.summary = body[:300]
    return items


def _collect(feeds: list[tuple], limit: int = 8) -> list[RawItem]:
    collected: list[RawItem] = []
    for name, url, kind in feeds:
        items = list(_cached_feed(url, name))
        items = _apply_filter(items, kind)
        collected.extend(items)

    # 제목 기준 중복 제거 → URL 기준 중복 제거
    collected = dedupe_by_title(collected)
    seen: set[str] = set()
    unique: list[RawItem] = []
    for it in collected:
        if it.url and it.url not in seen:
            seen.add(it.url)
            unique.append(it)

    return _enrich(unique[:limit])


def collect_policy(limit: int = 8) -> list[RawItem]:
    """국내 정책."""
    return _collect(POLICY_FEEDS, limit)


def collect_youth(limit: int = 8) -> list[RawItem]:
    """청년 정책."""
    return _collect(YOUTH_FEEDS, limit)


def collect_data(limit: int = 8) -> list[RawItem]:
    """통계·생활정보."""
    return _collect(DATA_FEEDS, limit)


if __name__ == "__main__":
    for label, fn in (("국내정책", collect_policy), ("청년정책", collect_youth), ("통계·생활", collect_data)):
        rows = fn()
        print(f"\n=== {label}: {len(rows)}건 ===")
        for r in rows:
            print("  •", r.title[:45], f"[{r.source}]")
