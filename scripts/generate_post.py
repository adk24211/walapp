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

Category = Literal["domestic", "world", "policy", "curious"]

CATEGORY_META = {
    "domestic": {
        "jekyll_cat": "domestic",
        "label": "국내 핫뉴스",
        "summary_label": "summary-box domestic",
    },
    "world": {
        "jekyll_cat": "world",
        "label": "해외 핫뉴스",
        "summary_label": "summary-box world",
    },
    "policy": {
        "jekyll_cat": "policy",
        "label": "정부·청년 정책",
        "summary_label": "summary-box policy",
    },
    "curious": {
        "jekyll_cat": "curious",
        "label": "흥미로운 발견",
        "summary_label": "summary-box curious",
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

    if category == "domestic":
        instruction = textwrap.dedent("""
            === 작성 지침 ===
            - 대상 독자: 오늘의 주요 뉴스를 빠르게 파악하려는 일반 독자
            - 주제: 오늘 국내에서 가장 화제가 된 주요 뉴스 정리
            - 문체: 신문 기사체. 평서형 종결어미('~다', '~했다', '~라고 밝혔다')를 사용하고, 객관적이고 중립적인 보도 어조를 유지하세요. 구어체·말투는 절대 쓰지 마세요
            - 첫 문단은 오늘 국내 뉴스의 전체 흐름을 요약하는 리드 문장으로 시작하세요
            - 수집된 뉴스 중 가장 중요한 5~7개를 선별하고, 각 뉴스마다 ## 소제목을 두세요
            - 각 뉴스는 핵심 사실(무엇이·언제·누가) → 배경·맥락 → 의미·파급 효과 순으로 최소 3문장 이상 충실히 작성하세요
            - 정치적으로 민감한 사안은 특정 입장에 치우치지 말고 사실 위주로 균형 있게 서술하세요
            - 마지막에 오늘 뉴스를 관통하는 큰 흐름을 한 문단으로 정리하세요
        """).strip()

    elif category == "world":
        instruction = textwrap.dedent("""
            === 작성 지침 ===
            - 대상 독자: 오늘의 해외 주요 뉴스를 빠르게 파악하려는 일반 독자
            - 주제: 오늘 해외에서 가장 화제가 된 주요 뉴스 정리
            - 문체: 신문 기사체. 평서형 종결어미('~다', '~라고 밝혔다', '~으로 전해졌다')를 사용하고, 객관적이고 중립적인 보도 어조를 유지하세요. 구어체·말투는 절대 쓰지 마세요
            - 영어 원문 뉴스를 한국어 기사체로 정확하게 번역·요약하세요. 오역에 주의하세요
            - 첫 문단은 오늘 해외 뉴스의 전체 흐름을 요약하는 리드 문장으로 시작하세요
            - 수집된 뉴스 중 가장 중요한 5~7개를 선별하고, 각 뉴스마다 ## 소제목을 두세요
            - 각 뉴스는 핵심 사실 → 배경·맥락 → 국제적 의미·파급 효과 순으로 최소 3문장 이상 작성하세요
            - 국내 독자가 생소할 수 있는 인물·지명·기관은 간단히 부연 설명을 덧붙이세요
            - 마지막에 오늘 국제 뉴스를 관통하는 큰 흐름을 한 문단으로 정리하세요
        """).strip()

    elif category == "curious":
        instruction = textwrap.dedent("""
            === 작성 지침 ===
            - 대상 독자: 신기하고 재미있는 이야기, 새로운 발견과 신기술에 흥미를 느끼는 일반 독자
            - 주제: 과학적 발견, 우주, 자연, 역사 속 미스터리, 흥미로운 사실, 신기술 등 '읽는 재미'가 있는 이야기
            - 문체: 신문 기사체(평서형 '~다' 종결)를 유지하되, 호기심을 자극하는 흥미로운 서술로 작성하세요. 구어체·말투는 쓰지 마세요
            - 첫 문단은 독자의 호기심을 강하게 끄는 도입부로 시작하세요 (놀라운 사실, 의외의 발견 등)
            - 수집된 소재 중 가장 흥미로운 4~6개를 선별하고, 각 소재마다 ## 소제목을 두세요
            - 각 소재는 '무엇이 발견·발표됐는가' → '왜 놀랍거나 흥미로운가' → '배경 지식과 맥락' → '의미와 시사점' 순으로 충실히 풀어 쓰세요
            - 독자가 몰랐을 배경지식이나 관련 사실을 곁들여 '아하' 하는 깨달음을 주세요
            - 영어 원문 소재는 한국어로 정확하게 옮기되, 전문 용어는 쉽게 풀어 설명하세요
            - 마지막에 이번 이야기들을 관통하는 흥미로운 통찰이나 여운을 남기는 문장으로 마무리하세요
        """).strip()

    else:  # policy
        instruction = textwrap.dedent("""
            === 작성 지침 ===
            - 대상 독자: 정책 정보를 찾는 20~35세 청년 및 일반 독자
            - 문체: 신문 기사체. 평서형 종결어미('~다', '~했다', '~로 나타났다')를 사용하고, 객관적이고 단정적인 보도 어조를 유지하세요. "~해요", "~거든요" 같은 구어체·말투는 절대 쓰지 마세요
            - 첫 문단은 핵심 사실을 요약하는 리드(lead) 문장으로 시작하세요 (누가·무엇을·언제·얼마)
            - 가장 중요한 정책 1~2개를 선정해 깊이 있게 다루세요. 각 정책마다 ## 소제목을 두고 최소 3~4문장 이상으로 충실히 설명하세요
            - 다음 요소를 빠짐없이 구체적으로 담으세요: 정책 도입 배경과 목적, 지원 대상과 자격 요건, 지원 금액·규모(구체적 수치), 신청 기간과 방법, 기대 효과
            - 독자가 자신이 해당되는지 판단할 수 있도록 자격 요건(나이·소득·거주지 등)을 구체적으로 풀어 쓰세요
            - 표(마크다운 table)를 활용해 지원 내용/대상/금액을 정리하면 좋습니다
            - 단순 사실 나열을 넘어, 이 정책이 청년에게 어떤 의미가 있는지 맥락을 함께 제시하세요
        """).strip()

    output_format = textwrap.dedent("""
        === 출력 형식 ===
        반드시 아래 JSON 형식으로만 응답하세요. JSON 외 다른 텍스트는 절대 포함하지 마세요.

        {
          "title": "포스트 제목 (40자 이내, 명사로 끝나는 신문 헤드라인 형식)",
          "summary": "카드에 표시될 한 줄 요약 (80자 이내, 명사 또는 '~다'로 종결)",
          "headline": "오늘의 메인 헤드라인 (index.html h1용, 개행 포함 가능, 최초 포스트만)",
          "callout": "강조할 핵심 정보 한 줄 (선택사항, 정책류에 유용)",
          "callout_label": "callout 앞 라벨 (예: 신청 기간, 핵심)",
          "tags": ["태그1", "태그2", "태그3"],
          "content": "마크다운 본문 전체 (summary-box 포함)"
        }

        ★ 문장 종결 규칙 (가장 중요, 반드시 준수) ★
        - 본문(content)의 모든 문장은 평서형 종결어미 '~다'/'~한다'/'~했다'/'~로 나타났다' 등으로 끝내세요
        - title, summary, headline, callout 은 명사(체언)로 끝내거나 '~다'로 끝내세요. (예: "청년 월세 지원 확대" O, "월세를 지원해요" X)
        - '~요', '~해요', '~네요', '~거든요', '~이에요', '~죠', '~세요' 같은 구어체 종결은 제목·요약·본문 어디에도 절대 쓰지 마세요
        - 존댓말 권유체("~하세요", "~보세요")도 쓰지 마세요. 객관적 서술로만 작성하세요

        ★ 독자 몰입 규칙 (조회수·체류시간을 높이는 핵심) ★
        - 단순 사실 요약에 그치지 말고, 독자가 끝까지 읽고 싶게 만드는 깊이 있는 글을 쓰세요
        - 리드 문단은 호기심을 자극하는 강력한 도입부로 시작하세요 (놀라운 수치, 의외의 사실, 핵심 쟁점 등). 단, 과장이나 낚시성 표현은 금지
        - 각 항목마다 '무슨 일인가' → '왜 그런가(배경·맥락)' → '그래서 무엇이 달라지나(의미·영향)' → '앞으로 어떻게 되나(전망)' 흐름으로 풍부하게 서술하세요
        - 독자가 "몰랐던 사실"이나 "숨은 맥락", "관련 배경지식"을 곁들여 정보의 밀도를 높이세요
        - 가능하면 구체적 수치, 사례, 비교, 인용 등 근거를 들어 설득력과 흥미를 동시에 확보하세요
        - 딱딱한 나열 대신, 사안들을 연결해 하나의 이야기처럼 자연스럽게 이어 쓰세요 (단, 문체는 평서형 기사체 유지)
        - 마지막 섹션에서는 전체를 관통하는 통찰이나 독자가 곱씹을 만한 시사점을 제시하세요

        content 작성 규칙:
        - 한글과 영문(+숫자)만 사용하세요. 한자(漢字)와 일본어 가나(カタカナ·ひらがな)는 절대 쓰지 마세요 (예: '詳細' → '상세', 'サイバー' → '사이버')
        - 모든 줄은 들여쓰기 없이 행의 맨 앞에서 시작하세요. 공백으로 들여쓰지 마세요
        - 첫 줄은 반드시 <div class="summary-box [CATEGORY_CLASS]">핵심을 요약하는 1~2문장</div> 형태의 한 줄짜리 요약 박스로 작성하세요. 본문 전체를 이 박스 안에 넣지 마세요
        - [CATEGORY_CLASS] 자리에는 domestic / world / policy / curious 중 하나를 넣으세요
        - summary-box 다음부터는 반드시 마크다운 ## 소제목으로 섹션을 나누세요. <h2>·<p> 같은 HTML 태그를 쓰지 말고 순수 마크다운으로 작성하세요
        - 각 ## 섹션 본문은 최소 4~6문장 이상으로 충실히 작성하세요. 한두 문장으로 끝내지 마세요
        - 본문 길이: 1800~2800자 (한국어 기준). 정보성 글이므로 풍부하게 채우되, 의미 없는 반복이나 군더더기는 피하세요
        - 최소 4개 이상의 ## 소제목 섹션으로 구성하세요
        - 마크다운 표, 굵은 글씨, blockquote, 글머리 기호(목록)를 적극 활용해 정보를 구조적으로 정리하세요
        - URL 링크는 포함하지 마세요 (보안 이슈)
    """).strip()

    return f"{base}\n\n{instruction}\n\n{output_format}"


def _escape_control_chars(raw: str) -> str:
    """JSON 문자열 값 내부의 이스케이프되지 않은 제어문자를 이스케이프 처리.

    LLM이 content 등의 값 안에 실제 줄바꿈/탭을 그대로 넣으면 json.loads가
    'Invalid control character' 에러를 내므로, 따옴표 안쪽에 있을 때만 변환한다.
    """
    out = []
    in_string = False
    escaped = False
    for ch in raw:
        if escaped:
            out.append(ch)
            escaped = False
            continue
        if ch == "\\":
            out.append(ch)
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            out.append(ch)
            continue
        if in_string:
            if ch == "\n":
                out.append("\\n")
            elif ch == "\r":
                out.append("\\r")
            elif ch == "\t":
                out.append("\\t")
            else:
                out.append(ch)
        else:
            out.append(ch)
    return "".join(out)


# 한국어 텍스트에 끼어드는 외국 문자 제거용.
# CJK 한자(통합 + 확장 A), 일본어 히라가나/가타카나(음장기호 ー 포함).
# 가타카나 가운뎃점 U+30FB는 한국어 가운뎃점과 혼동되므로 범위에서 제외한다.
_FOREIGN_RE = re.compile(
    r"[㐀-䶿一-鿿぀-ゟ゠-ヺー-ヿ]"
)


def _strip_foreign(text: str) -> str:
    """한국어 문맥에 무작위로 끼어드는 한자·일본어 가나를 제거한다.

    예) '詳細' → '', 'サイバー攻撃' → ''. 영문/숫자/한글은 보존한다.
    제거 후 생기는 이중 공백은 한 칸으로 정리한다.
    """
    cleaned = _FOREIGN_RE.sub("", text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


def _clean_content(content: str) -> str:
    """LLM이 생성한 마크다운 본문 정리.

    - 각 줄의 선행 공백을 제거한다. 모델이 본문 전체를 들여쓰면 kramdown이
      4칸 이상 들여쓰기를 코드 블록으로 오인해 div/제목이 깨지기 때문이다.
    - 한자·일본어 가나를 제거한다.
    """
    lines = [line.lstrip() for line in content.splitlines()]
    cleaned = "\n".join(lines).strip()
    cleaned = _FOREIGN_RE.sub("", cleaned)
    return cleaned


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

    # 기본 모델로 호출하되, 일일 토큰 한도(429) 도달 시 별도 한도를 가진
    # 경량 모델로 폴백해 포스트 생성을 보장한다.
    primary_model = "llama-3.3-70b-versatile"
    fallback_model = "llama-3.1-8b-instant"

    def _call(model: str):
        return client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4096,
            response_format={"type": "json_object"},
        )

    try:
        response = _call(primary_model)
    except Exception as e:
        if "rate_limit" in str(e) or "429" in str(e):
            log.warning("%s 한도 초과 → 폴백 모델(%s)로 재시도", primary_model, fallback_model)
            response = _call(fallback_model)
        else:
            raise

    raw = response.choices[0].message.content.strip()

    # JSON 펜스 제거
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # 문자열 값 안에 이스케이프되지 않은 제어문자(줄바꿈 등)가 섞인 경우 보정
        data = json.loads(_escape_control_chars(raw))

    # content 후처리: 줄별 들여쓰기 제거(kramdown 코드블록 오인 방지) + 외국 문자 제거
    if data.get("content"):
        data["content"] = _clean_content(data["content"])

    # 나머지 텍스트 필드 외국 문자(한자·일본어 가나) 제거
    for key in ("title", "summary", "headline", "callout", "callout_label"):
        if data.get(key):
            data[key] = _strip_foreign(str(data[key]))
    if isinstance(data.get("tags"), list):
        data["tags"] = [t for t in (_strip_foreign(str(t)) for t in data["tags"]) if t]

    log.info("생성 완료: %s", data.get("title", "제목 없음"))
    return data


def _yaml_safe(text: str) -> str:
    """큰따옴표로 감싸는 YAML 스칼라용으로 안전하게 정리.

    줄바꿈을 공백으로 바꾸고 내부 큰따옴표를 작은따옴표로 치환해
    front matter 파싱이 깨지지 않게 한다.
    """
    return " ".join(str(text).split()).replace('"', "'")


def to_jekyll_markdown(
    data: dict,
    category: Category,
    post_date: datetime,
) -> str:
    """생성된 데이터를 Jekyll front matter + 마크다운으로 변환"""
    meta = CATEGORY_META[category]
    date_str = post_date.strftime("%Y-%m-%d %H:%M:%S +0900")
    tags_yaml = "\n".join(f"  - {_yaml_safe(t)}" for t in data.get("tags", []))

    front_matter_parts = [
        "---",
        "layout: post",
        f'title: "{_yaml_safe(data["title"])}"',
        f"date: {date_str}",
        f"categories: [{meta['jekyll_cat']}]",
        f"tags:\n{tags_yaml}",
        f'summary: "{_yaml_safe(data.get("summary", ""))}"',
    ]

    if data.get("callout"):
        front_matter_parts.append(f'callout: "{_yaml_safe(data["callout"])}"')
        front_matter_parts.append(
            f'callout_label: "{_yaml_safe(data.get("callout_label", "핵심"))}"'
        )

    if data.get("headline"):
        front_matter_parts.append(f'headline: "{_yaml_safe(data["headline"])}"')

    front_matter_parts.append("---")
    front_matter = "\n".join(front_matter_parts)

    return f"{front_matter}\n\n{data['content']}\n"


def make_filename(category: Category, post_date: datetime, title: str) -> str:
    """Jekyll 파일명 생성"""
    date_prefix = post_date.strftime("%Y-%m-%d")

    slug_map = {
        "domestic": "domestic",
        "world":    "world",
        "policy":   "policy",
        "curious":  "curious",
    }
    slug = slug_map[category]

    # 제목에서 영문/숫자 추출해서 슬러그에 추가
    title_slug = re.sub(r"[^a-zA-Z0-9가-힣\s]", "", title)
    title_slug = re.sub(r"\s+", "-", title_slug.strip())[:30]

    return f"{date_prefix}-{slug}.md"
