"""
Gemini API를 사용해 수집된 데이터를 Jekyll 포스트로 변환
"""
from __future__ import annotations

import logging
import re
import textwrap
from datetime import datetime
from typing import Literal

from groq import Groq

from collect.base import RawItem

log = logging.getLogger(__name__)

Category = Literal["policy", "dev-jobs", "tech-news"]

CATEGORY_META = {
    "policy": {
        "jekyll_cat": "policy",
        "label": "정부·청년 정책",
        "summary_label": "summary-box policy",
    },
    "dev-jobs": {
        "jekyll_cat": "dev-jobs",
        "label": "개발자 채용",
        "summary_label": "summary-box jobs",
    },
    "tech-news": {
        "jekyll_cat": "tech-news",
        "label": "IT·테크",
        "summary_label": "summary-box tech",
    },
}


def _build_prompt(
    category: Category,
    items: list[RawItem],
    extra: dict | None = None,
) -> str:
    """카테고리별 프롬프트 생성"""
    today = datetime.now().strftime("%Y년 %m월 %d일")

    item_text = "\n\n".join(
        f"[{i+1}] 출처: {item.source}\n제목: {item.title}\nURL: {item.url}\n요약: {item.summary}"
        for i, item in enumerate(items)
    )

    base = textwrap.dedent(f"""
        오늘 날짜: {today}
        카테고리: {CATEGORY_META[category]["label"]}

        아래 수집된 데이터를 바탕으로 Jekyll 블로그 포스트를 작성해주세요.

        === 수집된 데이터 ===
        {item_text}
    """).strip()

    if category == "policy":
        instruction = textwrap.dedent("""
            === 작성 지침 ===
            - 대상 독자: 20~35세 청년, 정책 용어에 익숙하지 않은 일반인
            - 문체: 친근하고 쉬운 구어체 (예: "~해요", "~거든요", "~이에요")
            - 가장 중요한 정책 1~2개를 선정해서 깊이 있게 다루세요
            - 신청 방법, 조건, 금액 등 실용적인 정보를 구체적으로 포함하세요
            - 독자가 바로 행동할 수 있도록 구체적인 다음 단계를 제시하세요
        """).strip()

    elif category == "dev-jobs":
        stack_info = ""
        if extra and extra.get("stack_counts"):
            top5 = list(extra["stack_counts"].items())[:5]
            stack_info = "기술 스택 언급 빈도: " + ", ".join(
                f"{k}({v})" for k, v in top5
            )
        instruction = textwrap.dedent(f"""
            === 작성 지침 ===
            - 대상 독자: 취업 준비 중이거나 이직을 고려하는 개발자
            - 문체: 친근하되 정보 밀도가 높은 구어체
            - 이번 주 채용 시장의 전체적인 흐름을 먼저 분석하세요
            - 기술 스택 트렌드를 수치와 함께 구체적으로 언급하세요
            - 눈에 띄는 공고 3~5개를 구체적으로 소개하세요
            - 구직자에게 실용적인 팁 1가지를 마지막에 추가하세요
            {stack_info}
        """).strip()

    else:  # tech-news
        instruction = textwrap.dedent("""
            === 작성 지침 ===
            - 대상 독자: IT에 관심 있는 개발자, 테크 종사자
            - 문체: 정보 중심, 간결하고 명확한 구어체
            - 수집된 뉴스 중 개발자에게 가장 임팩트 있는 3~5개를 선별하세요
            - 각 뉴스마다 "왜 중요한지"를 한 문장으로 짚어주세요
            - 영어 뉴스는 한국어로 자연스럽게 요약하세요
            - 글로벌 트렌드와 국내 개발 생태계에 미치는 영향을 연결해서 설명하세요
        """).strip()

    output_format = textwrap.dedent("""
        === 출력 형식 ===
        반드시 아래 JSON 형식으로만 응답하세요. JSON 외 다른 텍스트는 절대 포함하지 마세요.

        {
          "title": "포스트 제목 (40자 이내, 핵심 내용 담기)",
          "summary": "카드에 표시될 한 줄 요약 (80자 이내)",
          "headline": "오늘의 메인 헤드라인 (index.html h1용, 개행 포함 가능, 최초 포스트만)",
          "callout": "강조할 핵심 정보 한 줄 (선택사항, 정책류에 유용)",
          "callout_label": "callout 앞 라벨 (예: 신청 기간, 핵심)",
          "tags": ["태그1", "태그2", "태그3"],
          "content": "마크다운 본문 전체 (summary-box 포함)"
        }

        content 작성 규칙:
        - 첫 줄은 반드시 <div class="summary-box [CATEGORY_CLASS]"> 블록으로 시작
        - [CATEGORY_CLASS] 자리에는 policy / jobs / tech 중 하나를 넣으세요
        - 이후 ## 소제목으로 섹션을 나누세요
        - 본문 길이: 600~900자 (한국어 기준)
        - 마크다운 표, 굵은 글씨, blockquote 자유롭게 사용
        - URL 링크는 포함하지 마세요 (보안 이슈)
    """).strip()

    return f"{base}\n\n{instruction}\n\n{output_format}"


def generate(
    category: Category,
    items: list[RawItem],
    client: Groq,
    extra: dict | None = None,
) -> dict:
    """Groq API 호출 → 포스트 데이터 반환"""
    import json

    prompt = _build_prompt(category, items, extra)
    log.info("Groq API 호출: %s (%d건)", category, len(items))

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000,
    )
    raw = response.choices[0].message.content.strip()

    # JSON 펜스 제거
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        log.error("JSON 파싱 실패: %s\n원문: %s", e, raw[:200])
        raise

    log.info("생성 완료: %s", data.get("title", "제목 없음"))
    return data


def to_jekyll_markdown(
    data: dict,
    category: Category,
    post_date: datetime,
) -> str:
    """생성된 데이터를 Jekyll front matter + 마크다운으로 변환"""
    meta = CATEGORY_META[category]
    date_str = post_date.strftime("%Y-%m-%d %H:%M:%S +0900")
    tags_yaml = "\n".join(f"  - {t}" for t in data.get("tags", []))

    front_matter_parts = [
        "---",
        "layout: post",
        f'title: "{data["title"]}"',
        f"date: {date_str}",
        f"categories: [{meta['jekyll_cat']}]",
        f"tags:\n{tags_yaml}",
        f'summary: "{data.get("summary", "")}"',
    ]

    if data.get("callout"):
        front_matter_parts.append(f'callout: "{data["callout"]}"')
        front_matter_parts.append(
            f'callout_label: "{data.get("callout_label", "핵심")}"'
        )

    if data.get("headline"):
        front_matter_parts.append(f'headline: "{data["headline"]}"')

    front_matter_parts.append("---")
    front_matter = "\n".join(front_matter_parts)

    return f"{front_matter}\n\n{data['content']}\n"


def make_filename(category: Category, post_date: datetime, title: str) -> str:
    """Jekyll 파일명 생성"""
    date_prefix = post_date.strftime("%Y-%m-%d")

    slug_map = {
        "policy":    "policy",
        "dev-jobs":  "dev-jobs",
        "tech-news": "tech-news",
    }
    slug = slug_map[category]

    # 제목에서 영문/숫자 추출해서 슬러그에 추가
    title_slug = re.sub(r"[^a-zA-Z0-9가-힣\s]", "", title)
    title_slug = re.sub(r"\s+", "-", title_slug.strip())[:30]

    return f"{date_prefix}-{slug}.md"
