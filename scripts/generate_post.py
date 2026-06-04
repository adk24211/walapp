"""
Groq API로 수집 데이터를 구조화 JSON으로 받아 → 카드뉴스 HTML 컴포넌트 포스트로 렌더링.

설계 원칙:
- LLM은 '구조화된 JSON 필드'만 생성한다(lead/stats/compare/steps/checklist/note/source).
- HTML 컴포넌트(.cn-*)는 파이썬이 결정론적으로 렌더링한다.
  → 매 포스트가 동일한 디자인으로 안정적으로 나오고, 마크다운/HTML 깨짐이 없다.
- 문체는 '존대말투'(~합니다/~하세요). 출처는 공공·1차(공공누리) 기준으로 표기.
"""
from __future__ import annotations

import html
import json
import logging
import re
import textwrap
from datetime import datetime
from typing import Literal

from groq import Groq

from collect.base import RawItem

log = logging.getLogger(__name__)

Category = Literal["policy", "youth", "data", "curious"]

CATEGORY_META = {
    "policy": {
        "jekyll_cat": "policy",
        "label": "국내 정책",
        "lead_icon": "ti-building-bank",
        "audience": "정부 정책·제도의 핵심과 영향을 빠르게 파악하고 싶은 일반 독자",
        "focus": (
            "정부·지자체가 발표한 국내 정책·제도를 다룹니다. "
            "도입 배경, 핵심 내용, 대상과 영향, 시행 일정을 사실·수치 중심으로 정리하세요."
        ),
    },
    "youth": {
        "jekyll_cat": "youth",
        "label": "청년 정책",
        "lead_icon": "ti-user-star",
        "audience": "지원금·정책 혜택을 찾는 19~34세 청년",
        "focus": (
            "청년 대상 지원금·일자리·주거·자산형성 정책을 다룹니다. "
            "'내가 받을 수 있는지, 얼마를, 어떻게 신청하는지'를 끝까지 해결하는 실전 가이드로 작성하세요. "
            "자격 요건은 checklist로, 유형 비교는 compare 표로 정리하면 좋습니다."
        ),
    },
    "data": {
        "jekyll_cat": "data",
        "label": "통계·생활정보",
        "lead_icon": "ti-chart-bar",
        "audience": "물가·고용·복지 등 생활에 직결되는 공공 통계와 생활정보를 알고 싶은 독자",
        "focus": (
            "공공기관이 발표한 통계·지표·생활밀착 정보를 다룹니다. "
            "핵심 수치를 stats로 강조하고, 수치가 의미하는 바와 생활에 미치는 영향을 해설하세요."
        ),
    },
    "curious": {
        "jekyll_cat": "curious",
        "label": "흥미로운 발견",
        "lead_icon": "ti-bulb",
        "audience": "과학적 발견·신기술·흥미로운 사실에 호기심을 느끼는 일반 독자",
        "focus": (
            "과학·우주·자연·역사·신기술 등 '읽는 재미'가 있는 이야기를 다룹니다. "
            "호기심을 자극하는 도입과 배경지식을 곁들여 steps(소재별 카드)로 풀어 쓰세요. "
            "stats/compare/checklist는 어울릴 때만 선택적으로 사용하세요."
        ),
    },
}


# ─────────────────────────────────────────────────────────────
#  프롬프트
# ─────────────────────────────────────────────────────────────
def _build_prompt(
    category: Category,
    items: list[RawItem],
    extra: dict | None = None,
) -> str:
    today = datetime.now().strftime("%Y년 %m월 %d일")
    meta = CATEGORY_META[category]

    item_text = "\n\n".join(
        f"[{i+1}] 출처: {item.source}\n제목: {item.title}\nURL: {item.url}\n요약: {item.summary}"
        for i, item in enumerate(items)
    )

    base = textwrap.dedent(f"""
        오늘 날짜: {today}
        카테고리: {meta["label"]}
        대상 독자: {meta["audience"]}

        아래 수집된 공공 발표 자료를 바탕으로, 카드뉴스형 정보 콘텐츠를 작성합니다.
        {meta["focus"]}

        === 수집된 데이터 ===
        {item_text}
    """).strip()

    rules = textwrap.dedent(r"""
        === 작성 원칙 ===
        ★ 문체(가장 중요) — 반드시 '존대말투'
        - 본문의 모든 문장은 '~합니다 / ~입니다 / ~됩니다 / ~하세요' 같은 존댓말로 끝맺습니다.
        - 평서형 기사체('~다/~했다')나 구어체('~해요/~거든요/~죠')는 쓰지 않습니다.
        - 다만 title·summary·headline·callout 은 명사(체언)로 끝내거나 '~합니다'로 끝냅니다.

        ★ 독창성·저작권
        - 수집 원문의 문장·표현을 절대 그대로 베끼지 않습니다. 사실·수치만 취해 완전히 자신의 언어로 다시 씁니다.
        - 개별 항목을 나열·복제하지 말고, 여러 정보를 엮어 '종합·해설'한 독창적 글로 재구성합니다.
        - 맥락·배경지식·의미를 더해 원문에 없는 부가가치를 만듭니다.

        ★ 정확성
        - 한글과 영문(+숫자)만 사용합니다. 한자·일본어 가나는 절대 쓰지 않습니다.
        - 수집 자료에 없는 수치를 지어내지 않습니다. 불확실하면 단정하지 않습니다.
        - 정치적으로 민감한 사안은 한쪽에 치우치지 않고 균형 있게 서술합니다.

        === 출력 형식(JSON만, 그 외 텍스트 금지) ===
        {
          "title": "포스트 제목 (40자 이내, 명사 또는 '~합니다'로 끝맺음)",
          "summary": "카드 한 줄 요약 (80자 이내)",
          "headline": "홈 대문 헤드라인 (45자 이내, 마침표 없이 명사형, 한 문장)",
          "callout": "강조할 핵심 한 줄 (선택)",
          "callout_label": "callout 라벨 (예: 핵심, 신청 기간)",
          "tags": ["태그1", "태그2", "태그3"],
          "lead": "핵심을 요약하는 1~2문장 (존댓말, 80~140자). 카드 상단 요약 배너에 들어갑니다.",
          "stats": [
            {"num": "19~34세", "label": "가입 연령"},
            {"num": "최대 12%", "label": "정부 기여금"}
          ],
          "compare": {
            "headers": ["구분", "일반형", "우대형"],
            "rows": [["정부 기여금", "월 6%", "월 12%"], ["소득 요건", "6,000만 원 이하", "3,600만 원 이하"]]
          },
          "steps": [
            {"title": "소제목", "body": "4~6문장의 충실한 설명 (존댓말). 배경·의미·영향을 풀어 씁니다."}
          ],
          "checklist": ["자격·확인 항목을 한 줄씩", "해당 여부를 스스로 판단하게"],
          "timeline": [{"when": "2026년 6월", "what": "출시 및 신청 개시"}],
          "faq": [{"q": "자주 묻는 질문", "a": "존댓말 답변 2~3문장"}],
          "quote": "이 글의 핵심을 한 문장으로 압축한 인용구 (존댓말)",
          "note": "독자가 꼭 확인해야 할 주의·안내 1~2문장 (존댓말)",
          "source": {"name": "대한민국 정책브리핑(korea.kr)", "license": "공공누리 제1유형"}
        }

        === 각 필드 작성 가이드 ===
        - lead: 필수. 글 전체의 핵심을 한눈에 전달합니다.
        - stats: 2~4개. 가장 중요한 수치/키워드를 짧게(num) + 라벨(label)로. 수치가 마땅치 않으면 빈 배열 [].
        - compare: 유형·구분 비교가 자연스러울 때만. 없으면 생략하거나 null. headers 첫 칸은 '구분'.
        - steps: 필수, 3~5개. 이 글의 본문에 해당합니다. 각 body는 최소 4문장 이상으로 충실히, 존댓말로.
        - checklist: 신청 자격·확인 항목 등 행동 유도가 필요할 때만. 없으면 [] 또는 생략.
        - timeline: 일정·절차가 있을 때만(when=시점, what=내용). 없으면 [] 또는 생략.
        - faq: 독자가 궁금해할 질문 2~4개(q=질문, a=존댓말 답변). 없으면 [] 또는 생략.
        - quote: 글의 핵심을 압축한 한 문장. 없으면 생략 가능.
        - note: 변경 가능성·공식 확인처 안내 등. 없으면 생략 가능.
        - source: 수집 데이터의 대표 출처 기관명을 name 에 적습니다. license 는 공공자료면 "공공누리 제1유형".
        - URL은 어떤 필드에도 넣지 않습니다(보안). 출처 링크는 시스템이 별도로 부착합니다.
        - 모든 값에서 한자·일본어 가나 금지.
    """).strip()

    return f"{base}\n\n{rules}"


# ─────────────────────────────────────────────────────────────
#  정리 유틸
# ─────────────────────────────────────────────────────────────
def _escape_control_chars(raw: str) -> str:
    """JSON 문자열 값 내부의 이스케이프되지 않은 제어문자를 이스케이프."""
    out, in_string, escaped = [], False, False
    for ch in raw:
        if escaped:
            out.append(ch); escaped = False; continue
        if ch == "\\":
            out.append(ch); escaped = True; continue
        if ch == '"':
            in_string = not in_string; out.append(ch); continue
        if in_string and ch == "\n":
            out.append("\\n")
        elif in_string and ch == "\r":
            out.append("\\r")
        elif in_string and ch == "\t":
            out.append("\\t")
        else:
            out.append(ch)
    return "".join(out)


# 카테고리별 공식 포털 링크(고정값 — LLM이 생성한 URL은 사용하지 않음, 보안)
OFFICIAL_LINKS = {
    "policy": [
        ("정부24 — 정책·민원 통합 포털", "https://www.gov.kr"),
        ("대한민국 정책브리핑 — 정책 원문", "https://www.korea.kr"),
    ],
    "youth": [
        ("온통청년 — 청년정책 통합 플랫폼", "https://www.youthcenter.go.kr"),
        ("복지로 — 복지 자격 모의계산", "https://www.bokjiro.go.kr"),
        ("정부24 — 정책·민원 통합 포털", "https://www.gov.kr"),
    ],
    "data": [
        ("국가통계포털 KOSIS — 통계 원자료", "https://kosis.kr"),
        ("e-나라지표 — 국가 주요 지표", "https://www.index.go.kr"),
    ],
}


# CJK 한자 + 일본어 가나(가타카나 가운뎃점 U+30FB 제외)
_FOREIGN_RE = re.compile(r"[㐀-䶿一-鿿぀-ゟ゠-ヺー-ヿ]")


def _strip_foreign(text: str) -> str:
    cleaned = _FOREIGN_RE.sub("", str(text))
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


def _esc(text: str) -> str:
    """HTML 본문 삽입용 이스케이프 + 외국문자 제거."""
    return html.escape(_strip_foreign(text), quote=False)


# ─────────────────────────────────────────────────────────────
#  Groq 호출
# ─────────────────────────────────────────────────────────────
def generate(
    category: Category,
    items: list[RawItem],
    client: Groq,
    extra: dict | None = None,
) -> dict:
    prompt = _build_prompt(category, items, extra)
    log.info("Groq API 호출: %s (%d건)", category, len(items))

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
            log.warning("%s 한도 초과 → 폴백 모델(%s)", primary_model, fallback_model)
            response = _call(fallback_model)
        else:
            raise

    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = json.loads(_escape_control_chars(raw))

    # 텍스트 필드 외국문자 제거
    for key in ("title", "summary", "headline", "callout", "callout_label", "lead", "note"):
        if data.get(key):
            data[key] = _strip_foreign(str(data[key]))
    if isinstance(data.get("tags"), list):
        data["tags"] = [t for t in (_strip_foreign(str(t)) for t in data["tags"]) if t]

    log.info("생성 완료: %s", data.get("title", "제목 없음"))
    return data


# ─────────────────────────────────────────────────────────────
#  HTML 컴포넌트 렌더링 (결정론적)
# ─────────────────────────────────────────────────────────────
def _render_components(data: dict, category: Category, source_url: str = "") -> str:
    meta = CATEGORY_META[category]
    cat = meta["jekyll_cat"]
    parts: list[str] = [f'<div class="cn" data-cat="{cat}">', ""]

    # 1) lead
    lead = data.get("lead") or data.get("summary") or ""
    if lead:
        parts += [
            f'<div class="cn cn-lead" data-cat="{cat}">',
            f'  <span class="cn-lead-icon"><i class="ti {meta["lead_icon"]}"></i></span>',
            f'  <p>{_esc(lead)}</p>',
            "</div>",
            "",
        ]

    # 2) stats
    stats = [s for s in (data.get("stats") or []) if s.get("num")]
    if stats:
        parts.append(f'<div class="cn cn-stats" data-cat="{cat}">')
        for s in stats[:4]:
            parts.append(
                '  <div class="cn-stat">'
                f'<span class="cn-stat-num">{_esc(s.get("num",""))}</span>'
                f'<span class="cn-stat-label">{_esc(s.get("label",""))}</span></div>'
            )
        parts += ["</div>", ""]

    # 3) compare 표
    cmp = data.get("compare")
    if cmp and cmp.get("headers") and cmp.get("rows"):
        parts += [f'<h2 class="cn-h">한눈에 보기</h2>', f'<div class="cn cn-table" data-cat="{cat}">', "<table>"]
        heads = "".join(f"<th>{_esc(h)}</th>" for h in cmp["headers"])
        parts += ["  <thead>", f"    <tr>{heads}</tr>", "  </thead>", "  <tbody>"]
        for row in cmp["rows"]:
            if not row:
                continue
            cells = f"<th>{_esc(str(row[0]))}</th>" + "".join(
                f"<td>{_esc(str(c))}</td>" for c in row[1:]
            )
            parts.append(f"    <tr>{cells}</tr>")
        parts += ["  </tbody>", "</table>", "</div>", ""]

    # 4) steps (본문)
    steps = [s for s in (data.get("steps") or []) if s.get("body")]
    if steps:
        parts.append(f'<h2 class="cn-h">핵심 정리</h2>')
        parts.append(f'<div class="cn cn-steps" data-cat="{cat}">')
        for n, s in enumerate(steps, 1):
            parts += [
                '  <div class="cn-step">',
                f'    <span class="cn-step-no">{n}</span>',
                '    <div class="cn-step-body">',
                f'      <h4>{_esc(s.get("title",""))}</h4>',
                f'      <p>{_esc(s.get("body",""))}</p>',
                "    </div>",
                "  </div>",
            ]
        parts += ["</div>", ""]

    # 5) checklist
    checklist = [c for c in (data.get("checklist") or []) if str(c).strip()]
    if checklist:
        parts.append(f'<h2 class="cn-h">확인 체크리스트</h2>')
        parts.append(f'<ul class="cn cn-check" data-cat="{cat}">')
        for c in checklist:
            parts.append(f"  <li>{_esc(str(c))}</li>")
        parts += ["</ul>", ""]

    # 5-b) timeline
    timeline = [t for t in (data.get("timeline") or []) if t.get("what")]
    if timeline:
        parts.append('<h2 class="cn-h">일정·절차</h2>')
        parts.append(f'<ul class="cn cn-timeline" data-cat="{cat}">')
        for t in timeline:
            parts.append(
                f'  <li><span class="cn-tl-when">{_esc(t.get("when",""))}</span>'
                f'<span class="cn-tl-what">{_esc(t.get("what",""))}</span></li>'
            )
        parts += ["</ul>", ""]

    # 5-c) FAQ
    faq = [f for f in (data.get("faq") or []) if f.get("q") and f.get("a")]
    if faq:
        parts.append('<h2 class="cn-h">자주 묻는 질문</h2>')
        parts.append(f'<div class="cn cn-faq" data-cat="{cat}">')
        for f in faq:
            parts += [
                "  <details>",
                f'    <summary>{_esc(f.get("q",""))}</summary>',
                f'    <div class="cn-faq-body">{_esc(f.get("a",""))}</div>',
                "  </details>",
            ]
        parts += ["</div>", ""]

    # 5-d) quote
    quote = data.get("quote")
    if quote:
        parts += [
            f'<div class="cn cn-quote" data-cat="{cat}">',
            f"  {_esc(quote)}",
            "</div>",
            "",
        ]

    # 6) note
    note = data.get("note")
    if note:
        parts += [
            f'<div class="cn cn-note" data-cat="{cat}">',
            '  <i class="ti ti-alert-triangle"></i>',
            f'  <p>{_esc(note)}</p>',
            "</div>",
            "",
        ]

    # 6-b) 공식 포털 링크 (카테고리별 고정값)
    links = OFFICIAL_LINKS.get(cat, [])
    if links:
        parts.append('<h2 class="cn-h">함께 보면 좋은 곳</h2>')
        parts.append(f'<div class="cn cn-links" data-cat="{cat}">')
        for label, url in links:
            parts.append(
                f'  <a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener">'
                f'<i class="ti ti-external-link"></i> {_esc(label)}'
                f' <span class="cn-link-ext">↗</span></a>'
            )
        parts += ["</div>", ""]

    # 7) source (공공누리 출처표시)
    src = data.get("source") or {}
    src_name = _esc(src.get("name", "공공 발표 자료"))
    src_license = _esc(src.get("license", "공공누리 제1유형"))
    if source_url:
        name_html = f'<a href="{html.escape(source_url, quote=True)}" target="_blank" rel="noopener">{src_name}</a>'
    else:
        name_html = src_name
    parts += [
        f'<div class="cn cn-source" data-cat="{cat}">',
        '  <span class="cn-source-tag">출처표시</span>',
        f'  <p>{name_html} · {src_license}. 위 내용은 공공 발표 자료의 사실·수치를 토대로 본 사이트가 직접 재구성·해설한 것입니다.</p>',
        "</div>",
        "",
        "</div>",
    ]
    return "\n".join(parts)


def _yaml_safe(text: str) -> str:
    return " ".join(str(text).split()).replace('"', "'")


def to_jekyll_markdown(
    data: dict,
    category: Category,
    post_date: datetime,
    source_url: str = "",
) -> str:
    meta = CATEGORY_META[category]
    date_str = post_date.strftime("%Y-%m-%d %H:%M:%S +0900")
    tags_yaml = "\n".join(f"  - {_yaml_safe(t)}" for t in data.get("tags", []))

    fm = [
        "---",
        "layout: post",
        f'title: "{_yaml_safe(data["title"])}"',
        f"date: {date_str}",
        f"categories: [{meta['jekyll_cat']}]",
        f"tags:\n{tags_yaml}",
        f'summary: "{_yaml_safe(data.get("summary", ""))}"',
    ]
    if data.get("callout"):
        fm.append(f'callout: "{_yaml_safe(data["callout"])}"')
        fm.append(f'callout_label: "{_yaml_safe(data.get("callout_label", "핵심"))}"')
    if data.get("headline"):
        fm.append(f'headline: "{_yaml_safe(data["headline"])}"')
    src = data.get("source") or {}
    if src.get("name"):
        fm.append(f'source: "{_yaml_safe(src["name"])}"')
    if source_url:
        fm.append(f'source_url: "{_yaml_safe(source_url)}"')
    fm.append("---")

    body = _render_components(data, category, source_url)
    return f"{chr(10).join(fm)}\n\n{body}\n"


def make_filename(category: Category, post_date: datetime, title: str) -> str:
    date_prefix = post_date.strftime("%Y-%m-%d")
    slug = CATEGORY_META[category]["jekyll_cat"]
    return f"{date_prefix}-{slug}.md"
