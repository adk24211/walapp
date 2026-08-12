"""제도 페이지 렌더러 — 레코드(사실) + 해설(문장) → Jekyll 마크다운.

구 generate_post.py 의 `_render_components()` 를 이어받되, 결정적인 차이가 하나 있다.

  구조: LLM 이 stats/compare/steps 를 통째로 만들었다 → 수치까지 생성했다
  현재: 수치·금액·기간·기관은 전부 `record` 에서 나온다. LLM 출력(`prose`)은
        설명 문장에만 쓰인다.

이 분리가 있어야 verify.py 의 사후 검증이 성립한다. (REDESIGN.md §6.3)
"""
from __future__ import annotations

import html
import re

import taxonomy
from schema import STATUS_ACTIVE, STATUS_CLOSED, ProgramRecord

# 구 generate_post.py 와 동일한 정책 — 한자·일본어 가나 제거
_FOREIGN_RE = re.compile(r"[㐀-䶿一-鿿぀-ゟ゠-ヺー-ヿ]")
_EMPTY_BRACKET_RE = re.compile(r"[(（\[「《]\s*[)）\]」》]")


def _strip_foreign(text) -> str:
    cleaned = _FOREIGN_RE.sub("", str(text or ""))
    cleaned = _EMPTY_BRACKET_RE.sub("", cleaned)
    cleaned = re.sub(r"\s+([,.)\]%])", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


def _esc(text) -> str:
    return html.escape(_strip_foreign(text), quote=False)


def _attr(text) -> str:
    return html.escape(str(text or ""), quote=True)


def _yaml(text) -> str:
    """front matter 한 줄 문자열로 안전하게."""
    return " ".join(str(text or "").split()).replace('"', "'")


# ─────────────────────────────────────────────────────────────
#  본문 컴포넌트
# ─────────────────────────────────────────────────────────────
def render_body(record: ProgramRecord, prose: dict) -> str:
    cat = record.category
    parts: list[str] = []

    def open_block(cls: str) -> str:
        return f'<div class="cn {cls}" data-cat="{cat}">'

    # ── 1) 한 줄 요약 ──
    summary = prose.get("summary") or record.benefit_raw
    parts += [
        open_block("cn-lead"),
        f'  <span class="cn-lead-icon"><i class="ti {taxonomy.CATEGORIES[cat]["icon"]}"></i></span>',
        f"  <p>{_esc(summary)}</p>",
        "</div>",
        "",
    ]

    # ── 2) 한눈에 보기 (전부 API 원본) ──
    # cn-spec: 라벨/값 2열 표. 기존 cn-table 은 다열 비교표용이라 가로 스크롤을 쓰는데,
    # 여기서는 값이 길므로 줄바꿈시켜야 한다.
    parts += ['<h2 class="cn-h">한눈에 보기</h2>', open_block("cn-table cn-spec"), "<table>"]
    parts += ["  <tbody>"]
    rows = [
        ("지원 대상", record.target_raw),
        ("지원 내용", record.benefit_raw),
        ("선정 기준", record.criteria_raw),
        ("신청 기간", _period_text(record)),
        ("소관 기관", record.org),
        ("지원 지역", record.region.label),
    ]
    for label, value in rows:
        if not str(value).strip():
            continue
        parts.append(f"    <tr><th>{_esc(label)}</th><td>{_esc(value)}</td></tr>")
    parts += ["  </tbody>", "</table>", "</div>", ""]

    # ── 3) 나도 받을 수 있나요 — 체크리스트 ──
    eligibility = [c for c in (prose.get("eligibility") or []) if str(c).strip()]
    if eligibility:
        parts.append('<h2 class="cn-h">나도 받을 수 있나요?</h2>')
        parts.append(f'<ul class="cn cn-check" data-cat="{cat}">')
        for item in eligibility:
            parts.append(f"  <li>{_esc(item)}</li>")
        parts += ["</ul>", ""]

    # ── 4) 신청 방법 ──
    steps = [s for s in (prose.get("steps") or []) if s.get("body")]
    if steps:
        parts.append('<h2 class="cn-h">어떻게 신청하나요?</h2>')
        parts.append(f'<div class="cn cn-steps" data-cat="{cat}">')
        for index, step in enumerate(steps, 1):
            title = re.sub(r"^\s*\d+\s*[.)]\s*", "", str(step.get("title", "")))
            parts += [
                '  <div class="cn-step">',
                f'    <span class="cn-step-no">{index}</span>',
                '    <div class="cn-step-body">',
                f"      <h4>{_esc(title)}</h4>",
                f'      <p>{_esc(step.get("body", ""))}</p>',
                "    </div>",
                "  </div>",
            ]
        parts += ["</div>", ""]

    # ── 5) 필요한 서류 (API 원본) ──
    if record.documents_raw:
        parts.append('<h2 class="cn-h">필요한 서류</h2>')
        parts.append(f'<ul class="cn cn-check" data-cat="{cat}">')
        for doc in record.documents_raw:
            parts.append(f"  <li>{_esc(doc)}</li>")
        parts += ["</ul>", ""]

    # ── 6) 신청 기간 타임라인 (API 원본) ──
    timeline = _timeline(record)
    if timeline:
        parts.append('<h2 class="cn-h">신청 일정</h2>')
        parts.append(f'<ul class="cn cn-timeline" data-cat="{cat}">')
        for when, what in timeline:
            parts.append(
                f'  <li><span class="cn-tl-when">{_esc(when)}</span>'
                f'<span class="cn-tl-what">{_esc(what)}</span></li>'
            )
        parts += ["</ul>", ""]

    # ── 7) FAQ ──
    faq = [f for f in (prose.get("faq") or []) if f.get("q") and f.get("a")]
    if faq:
        parts.append('<h2 class="cn-h">자주 묻는 질문</h2>')
        parts.append(f'<div class="cn cn-faq" data-cat="{cat}">')
        for item in faq:
            parts += [
                "  <details>",
                f'    <summary>{_esc(item["q"])}</summary>',
                f'    <div class="cn-faq-body">{_esc(item["a"])}</div>',
                "  </details>",
            ]
        parts += ["</div>", ""]

    # ── 8) 주의 안내 ──
    note = prose.get("note")
    if note:
        parts += [
            open_block("cn-note"),
            '  <i class="ti ti-alert-triangle"></i>',
            f"  <p>{_esc(note)}</p>",
            "</div>",
            "",
        ]

    # ── 9) 공식 창구 (LLM 이 만든 URL 은 절대 쓰지 않는다) ──
    links = [(url, label) for url, label in (
        (record.apply_url, "온라인으로 신청하기"),
        (record.official_url, "소관 기관에서 자세히 보기"),
    ) if url]
    if links:
        parts.append('<h2 class="cn-h">공식 창구</h2>')
        parts.append(f'<div class="cn cn-links" data-cat="{cat}">')
        for url, label in links:
            parts.append(
                f'  <a href="{_attr(url)}" target="_blank" rel="noopener nofollow">'
                f'<i class="ti ti-external-link"></i> {_esc(label)}'
                f' <span class="cn-link-ext">↗</span></a>'
            )
        parts += ["</div>", ""]

    return "\n".join(parts)


def _period_text(record: ProgramRecord) -> str:
    period = record.apply_period
    if period.always:
        return "상시 접수"
    if period.start and period.end:
        return f"{period.start} ~ {period.end}"
    if period.end:
        return f"{period.end}까지"
    if period.start:
        return f"{period.start}부터"
    return ""


def _timeline(record: ProgramRecord) -> list[tuple[str, str]]:
    period = record.apply_period
    if period.always:
        return []
    out: list[tuple[str, str]] = []
    if period.start:
        out.append((period.start, "신청 접수 시작"))
    if period.end:
        label = "신청 마감" if record.status != STATUS_CLOSED else "신청 마감 (종료됨)"
        out.append((period.end, label))
    return out


# ─────────────────────────────────────────────────────────────
#  전체 파일
# ─────────────────────────────────────────────────────────────
def to_markdown(record: ProgramRecord, prose: dict) -> str:
    front: list[str] = [
        "---",
        "layout: program",
        f'title: "{_yaml(record.name)}"',
        f'program_id: "{_yaml(record.id)}"',
        f'source: "{_yaml(record.source)}"',
        f"category: {record.category}",
    ]

    if record.audiences:
        front.append("audiences:")
        front += [f"  - {a}" for a in record.audiences]
    else:
        front.append("audiences: []")

    front += [
        f"region_scope: {record.region.scope}",
        f'region_label: "{_yaml(record.region.label)}"',
    ]
    if record.region.sido:
        front.append(f"region_sido: {record.region.sido}")
    if record.region.sigungu:
        front.append(f'region_sigungu: "{_yaml(record.region.sigungu)}"')

    front += [
        f'org: "{_yaml(record.org)}"',
        f'summary: "{_yaml(prose.get("summary") or record.benefit_raw)[:160]}"',
        f"status: {record.status}",
        f"apply_always: {'true' if record.apply_period.always else 'false'}",
    ]
    if record.apply_period.start:
        front.append(f'apply_start: "{record.apply_period.start}"')
    if record.apply_period.end:
        front.append(f'apply_end: "{record.apply_period.end}"')
    if record.apply_url:
        front.append(f'apply_url: "{_yaml(record.apply_url)}"')
    if record.official_url:
        front.append(f'official_url: "{_yaml(record.official_url)}"')

    front += [
        f'first_published: "{record.first_published}"',
        f'last_updated: "{record.last_updated}"',
        f'last_checked: "{record.last_checked}"',
        f"revision: {record.revision}",
    ]
    if record.is_mock:
        front.append("is_mock: true")

    # 카드 라벨용 — 대표 금액이 있으면 뽑아 둔다
    highlight = extract_highlight(record.benefit_raw)
    if highlight:
        front.append(f'highlight: "{_yaml(highlight)}"')

    front.append("---")
    return "\n".join(front) + "\n\n" + render_body(record, prose) + "\n"


_AMOUNT_RE = re.compile(
    r"(?:최대\s*)?\d[\d,]*\s*(?:억|천만|백만|만)?\s*원(?:\s*(?:까지|이내))?"
)


def extract_highlight(benefit: str) -> str:
    """지원 내용에서 대표 금액 표현을 뽑는다. 카드 배지에 쓴다."""
    if not benefit:
        return ""
    matches = _AMOUNT_RE.findall(benefit)
    if not matches:
        return ""
    # findall 이 그룹 없이 전체 매치를 주도록 finditer 로 다시 확인
    spans = [m.group(0).strip() for m in _AMOUNT_RE.finditer(benefit)]
    if not spans:
        return ""
    # '최대' 가 붙은 표현을 우선
    for span in spans:
        if "최대" in span:
            return span
    return spans[0]
