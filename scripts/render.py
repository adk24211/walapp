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
from schema import (
    STATUS_ACTIVE,
    STATUS_CLOSED,
    STATUS_LABELS,
    STATUS_UPCOMING,
    ProgramRecord,
)

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


def _esc_lines(text) -> str:
    """짧은 다중값을 <br> 로 이어 붙인다 (예: '기타 온라인신청\\n방문신청')."""
    lines = [_esc(line) for line in str(text or "").split("\n") if line.strip()]
    return "<br>".join(lines)


# 원문 불릿 마커 — 이 글자로 시작하는 줄은 목록 항목으로 본다.
_BULLET_RE = re.compile(r"^\s*[○●◦□■▪·•\-*]\s*")


def _render_lines(text) -> str:
    """장문 원문을 줄 구조를 살려 HTML 로.

    보조금24 원문은 '○ 큰 항목' 아래 '- 세부' 를 두는 형태가 많다. 마커를 그대로
    출력하면 지저분하므로 목록으로 바꾸되, **문구 자체는 손대지 않는다.**
    이 값들은 사실 원본이라 LLM 도 이 렌더러도 내용을 고쳐 쓰지 않는다.
    """
    out: list[str] = []
    in_list = False
    for raw_line in str(text or "").split("\n"):
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if _BULLET_RE.match(line):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"  <li>{_esc(_BULLET_RE.sub('', line))}</li>")
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<p>{_esc(line)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


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

    # ── 1) 한 줄 요약은 렌더하지 않는다 ──
    # 같은 문장이 이미 페이지 상단 히어로(`program-summary`)에 있다. 본문 첫 블록에
    # 한 번 더 찍으면 글자까지 똑같은 문단이 두 번 나온다.
    # front matter 의 `summary` 로만 넘기고(히어로·카드·검색이 그걸 쓴다) 여기선 생략.

    # ── 2) 한눈에 보기 — 짧은 메타만 표로 ──
    # 실제 보조금24 데이터의 지원대상·지원내용·선정기준은 '○'/'-' 불릿을 가진 장문이다
    # (근로장려금 선정기준은 2천 자가 넘는다). 표 한 칸에 넣으면 읽을 수 없으므로
    # 메타 정보만 표로 두고, 장문은 아래에서 줄 구조를 살려 따로 렌더한다.
    parts += ['<h2 class="cn-h">한눈에 보기</h2>', open_block("cn-table cn-spec"), "<table>"]
    parts += ["  <tbody>"]
    meta_rows = [
        ("진행 상태", _status_text(record)),
        ("신청 기간", _period_text(record)),
        ("소관 기관", record.org),
        ("지원 지역", record.region.label),
        ("접수 기관", record.receiver_raw),
        ("문의처", record.contact_raw),
        ("근거 법령", record.law_raw),
    ]
    for label, value in meta_rows:
        if not str(value).strip():
            continue
        parts.append(f"    <tr><th>{_esc(label)}</th><td>{_esc_lines(value)}</td></tr>")
    parts += ["  </tbody>", "</table>", "</div>", ""]

    # ── 2-b) 사실 원본 장문 (LLM 미개입) ──
    # 원문은 그대로 싣되, 아래 체크리스트·단계가 같은 내용을 쉬운 말로 다시 쓴다.
    # 둘을 다 펼쳐 두면 페이지가 두 배가 되므로 재서술이 있는 것만 접는다.
    #
    # ⚠️ '지원 내용'은 접지 않는다. 금액이 적힌 곳이 이 원문뿐이라 접으면 페이지에서
    #    금액이 사라진다. 지원금 사이트에서 그건 있을 수 없다. (한눈에 보기 표에는
    #    기간·기관만 있고 금액 칸이 없다.)
    for heading, value, fold in (
        ("지원 대상", record.target_raw, True),
        ("지원 내용", record.benefit_raw, False),
        ("선정 기준", record.criteria_raw, True),
    ):
        if not str(value).strip():
            continue
        # 제목은 <details> 밖에 둔다. 접힌 상태에서도 목차가 이 위치로 이동할 수 있어야 한다.
        parts.append(f'<h2 class="cn-h">{_esc(heading)}</h2>')
        if fold:
            parts.append(f'<details class="cn cn-fold" data-cat="{cat}">')
            parts.append(f'  <summary>{_esc(heading)} 원문 펼치기'
                         f'<span class="cn-fold-hint">공공데이터 원문</span></summary>')
            parts.append('  <div class="cn-fold-body">')
            parts.append(_render_lines(value))
            parts += ["  </div>", "</details>", ""]
        else:
            parts.append(open_block("cn-raw"))
            parts.append(_render_lines(value))
            parts += ["</div>", ""]

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

    # ── 5) 준비 서류·서식 (API 원본) ──
    # 보조금24는 '구비서류', 복지로는 서식·안내 자료가 섞여 온다. 후자를 '필요한 서류'로
    # 단정하면 제출 대상이 아닌 안내문까지 서류로 읽힌다. 둘을 포괄하는 제목을 쓴다.
    if record.documents_raw:
        parts.append('<h2 class="cn-h">준비 서류·서식</h2>')
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


def _status_text(record: ProgramRecord) -> str:
    """'시행중' / '예정 (2026-09-01 접수 시작)' / '종료 (2026-03-31 마감)'.

    괄호 안의 날짜는 원천 신청기한 원문에서 파싱한 값이다. 원문에 날짜가 없으면
    라벨만 남는다 — 없는 기간을 지어내지 않는다.
    """
    label = STATUS_LABELS.get(record.status, record.status)
    period = record.apply_period
    if record.status == STATUS_UPCOMING and period.start:
        return f"{label} ({period.start} 접수 시작)"
    if record.status == STATUS_CLOSED and period.end:
        return f"{label} ({period.end} 마감)"
    if record.status == STATUS_ACTIVE and period.always:
        return f"{label} (상시 접수)"
    return label


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
        label = ("신청 접수 시작 (예정)" if record.status == STATUS_UPCOMING
                 else "신청 접수 시작")
        out.append((period.start, label))
    if period.end:
        label = "신청 마감 (종료됨)" if record.status == STATUS_CLOSED else "신청 마감"
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
    if record.primary_audience:
        front.append(f"primary_audience: {record.primary_audience}")
    # 조회수는 원천 인기도다. 홈 히어로·정렬에 쓰므로 front matter 로 내보낸다.
    if record.view_count:
        front.append(f"view_count: {record.view_count}")

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
        f'status_label: "{STATUS_LABELS.get(record.status, record.status)}"',
        f"apply_always: {'true' if record.apply_period.always else 'false'}",
    ]

    # 종료된 제도는 색인에서 뺀다. 마감된 금액·요건이 검색 결과에 남으면
    # 지금 신청 가능한 제도로 오인된다 (YMYL). 페이지 자체는 그대로 둔다 —
    # 이미 유입된 사람에게는 '끝난 제도' 라는 정보가 필요하다. (사용자 확정 사항)
    if record.status == STATUS_CLOSED:
        front.append("noindex: true")
        front.append("sitemap: false")   # jekyll-sitemap 이 읽는 키
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
