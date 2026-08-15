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

from schema import STATUS_CLOSED, STATUS_LABELS, ProgramRecord

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

    # ── 섹션 카드 (K안) ──
    # 예전에는 본문 전체가 흰 카드 하나였고 그 안에 h2 와 블록이 평평하게 늘어섰다.
    # 3,500px 를 스크롤하는 동안 경계가 없어 지금 어느 항목을 읽는지 목차를 봐야 알았다.
    # 이제 항목마다 카드 하나를 주고 머리줄에 번호를 붙인다.
    #
    # 번호는 목차 번호와 같은 순서다 — h2 를 세는 program.js 의 목차와 여기 seq 가
    # 같은 순서로 증가하므로, 목차의 04 와 본문 카드의 04 가 항상 같은 항목을 가리킨다.
    # (본문에 h3 를 쓰기 시작하면 이 대응이 깨진다. 지금은 h4 만 쓴다.)
    seq = 0

    def sec(heading: str, blocks: list[str], *, key: bool = False,
            prose_written: bool = False) -> list[str]:
        """제목 한 줄 + 본문 블록을 카드 하나로 묶는다.

        `key=True` 는 '지원 내용' 전용이다. 금액이 적힌 곳이 거기뿐이라
        테두리와 머리줄을 다르게 줘서 눈이 먼저 가게 한다.

        `prose_written=True` 는 원문이 아니라 이 사이트가 쓴 문장이라는 표시다.
        재구성으로 해설 카드가 원문 카드보다 **위로** 올라왔다. 그 사실이 페이지
        맨 아래 출처표시에만 적혀 있으면 스크롤 끝까지 가야 안다. 지원금은 틀린
        정보가 곧 실제 피해라, 카드 단위로 구분되어야 한다.
        """
        nonlocal seq
        seq += 1
        out = [
            f'<section class="cn-sec{" is-key" if key else ""}" data-cat="{cat}">',
            '  <div class="cn-sec-head">',
            f'    <span class="cn-sec-no">{seq:02d}</span>',
            f'    <h2 class="cn-h">{_esc(heading)}</h2>',
        ]
        if key:
            out.append('    <span class="cn-sec-tag">금액이 적힌 항목</span>')
        elif prose_written:
            out.append('    <span class="cn-sec-tag is-prose">본 사이트가 쓴 문장</span>')
        out.append('  </div>')
        out.append('  <div class="cn-sec-body">')
        out += blocks
        out += ["  </div>", "</section>", ""]
        return out

    def fold(heading: str, value) -> list[str]:
        """공공데이터 원문을 접기 블록으로. 문구는 손대지 않는다."""
        return [
            f'<details class="cn cn-fold" data-cat="{cat}">',
            f'  <summary>{_esc(heading)} 원문 펼치기'
            f'<span class="cn-fold-hint">공공데이터 원문</span></summary>',
            '  <div class="cn-fold-body">',
            _render_lines(value),
            "  </div>",
            "</details>",
        ]

    # ── 항목 순서 ──
    # 예전 순서는 공공데이터 항목이 오는 순서였다(신청 창구 → 지원 대상 → 지원 내용 → …).
    # 사람이 묻는 순서는 다르다: 얼마 → 나도 되나 → 어떻게 → (확인용) 원문 → 창구.
    # 37건을 재보니 '나도 받을 수 있나요?' 가 다섯째라 금액을 본 뒤 자격을 보려면
    # 카드 셋을 지나야 했다.

    # ── 1) 지원 내용 — 금액이 적힌 유일한 곳 ──
    # ⚠️ 접지 않는다. 접으면 페이지에서 금액이 사라진다.
    if str(record.benefit_raw).strip():
        parts += sec("지원 내용",
                     [open_block("cn-raw"), _render_lines(record.benefit_raw), "</div>"],
                     key=True)

    # ── 2) 나도 받을 수 있나요 ──
    eligibility = [c for c in (prose.get("eligibility") or []) if str(c).strip()]
    if eligibility:
        block = [f'<ul class="cn cn-check" data-cat="{cat}">']
        for item in eligibility:
            block.append(f"  <li>{_esc(item)}</li>")
        block.append("</ul>")
        parts += sec("나도 받을 수 있나요?", block, prose_written=True)

    # ── 3) 어떻게 신청하나요 — 준비 서류를 여기 흡수한다 ──
    # 서류는 신청 절차의 일부다. 따로 카드를 두니 세로 지분 1위(18.2%)를 먹으면서
    # 37건 중 10건은 "해당없음" 한 단어짜리 빈 카드였다.
    steps = [s for s in (prose.get("steps") or []) if s.get("body")]
    docs = _real_documents(record.documents_raw)
    if steps or docs:
        block: list[str] = []
        if steps:
            block.append(f'<div class="cn cn-steps" data-cat="{cat}">')
            for index, step in enumerate(steps, 1):
                title = re.sub(r"^\s*\d+\s*[.)]\s*", "", str(step.get("title", "")))
                block += [
                    '  <div class="cn-step">',
                    f'    <span class="cn-step-no">{index}</span>',
                    '    <div class="cn-step-body">',
                    f"      <h4>{_esc(title)}</h4>",
                    f'      <p>{_esc(step.get("body", ""))}</p>',
                    "    </div>",
                    "  </div>",
                ]
            block.append("</div>")
        if docs:
            # h4 를 쓰는 이유: 목차는 h2 만 센다. 여기에 h3 를 쓰면 목차 번호와
            # 카드 번호의 대응이 깨진다.
            block.append('<h4 class="cn-sub">준비 서류·서식</h4>')
            block.append(f'<ul class="cn cn-check" data-cat="{cat}">')
            for doc in docs:
                block.append(f"  <li>{_esc(doc)}</li>")
            block.append("</ul>")
        parts += sec("어떻게 신청하나요?", block, prose_written=bool(steps))

    # ── 4) 지원 대상·선정 기준 — 원문 한 카드에 ──
    # 둘은 원문 기준으로 겹칠 때가 있다(최대 유사도 0.94). 한쪽이 다른 쪽에 통째로
    # 들어 있으면 하나만 싣는다. 애매하게 비슷한 정도로는 지우지 않는다 —
    # 지원금 정보에서 '비슷해 보여서 뺐다' 는 위험한 판단이다.
    target = str(record.target_raw or "").strip()
    criteria = str(record.criteria_raw or "").strip()
    if criteria and target and _contains(target, criteria):
        criteria = ""
    blocks: list[str] = []
    names: list[str] = []
    if target:
        blocks += fold("지원 대상", target)
        names.append("지원 대상")
    if criteria:
        blocks += fold("선정 기준", criteria)
        names.append("선정 기준")
    if blocks:
        parts += sec("·".join(names), blocks)

    # ── 5) 신청 창구 ──
    # 오른쪽 신청 레일에는 '얼마 · 언제까지 · 신청 버튼' 만 둔다. 스크롤을 따라다니는
    # 자리라 행동에 필요한 값만 있어야 한다.
    # 소관 기관·지원 지역은 '누가 운영하나' 쪽 정보라 접수 기관·문의처와 한 표에 모은다.
    #
    # 예전에 따로 있던 '공식 창구' 카드는 없앴다. 링크 둘 중 '온라인으로 신청하기' 는
    # 레일 버튼과 주소까지 같았고, 남는 건 기관 안내 링크 하나뿐이라 이 표 아래로 옮겼다.
    meta_rows = [
        ("소관 기관", record.org),
        ("지원 지역", record.region.label),
        ("접수 기관", record.receiver_raw),
        ("문의처", record.contact_raw),
        ("근거 법령", record.law_raw),
    ]
    rows = [(label, value) for label, value in meta_rows if str(value).strip()]
    if rows or record.official_url:
        block = []
        if rows:
            block += [open_block("cn-table cn-spec"), "<table>", "  <tbody>"]
            for label, value in rows:
                block.append(f"    <tr><th>{_esc(label)}</th><td>{_esc_lines(value)}</td></tr>")
            block += ["  </tbody>", "</table>", "</div>"]
        if record.official_url:
            block += [
                f'<div class="cn cn-links" data-cat="{cat}">',
                f'  <a href="{_attr(record.official_url)}" target="_blank" rel="noopener nofollow">'
                f'<i class="ti ti-external-link"></i> 소관 기관에서 자세히 보기'
                f' <span class="cn-link-ext">↗</span></a>',
                "</div>",
            ]
        parts += sec("신청 창구", block)

    # ── 6) FAQ ──
    # 생성된 질문의 76%(55개 중 42개)가 바로 위 카드에 답이 있는 것이었다.
    # "…금액은 얼마인가요?" 의 답은 '지원 내용' 원문에 그대로 있다.
    # 되묻는 질문을 걸러내고, 남는 게 없으면 항목 자체를 렌더하지 않는다.
    faq = [f for f in (prose.get("faq") or []) if f.get("q") and f.get("a")]
    faq = _useful_faq(faq, record, eligibility=bool(eligibility), steps=bool(steps),
                      docs=bool(docs))
    if faq:
        block = [f'<div class="cn cn-faq" data-cat="{cat}">']
        for item in faq:
            block += [
                "  <details>",
                f'    <summary>{_esc(item["q"])}</summary>',
                f'    <div class="cn-faq-body">{_esc(item["a"])}</div>',
                "  </details>",
            ]
        block.append("</div>")
        parts += sec("자주 묻는 질문", block, prose_written=True)

    # ── 주의 안내 ──
    # 카드로 만들지 않는다. 제목이 없는 경고 한 줄이라 번호를 붙이면 목차에 없는
    # 항목이 본문에만 생겨 번호가 어긋난다. 카드 사이에 낀 알림으로 둔다.
    note = prose.get("note")
    if note:
        parts += [
            open_block("cn-note"),
            '  <i class="ti ti-alert-triangle"></i>',
            f"  <p>{_esc(note)}</p>",
            "</div>",
            "",
        ]

    # ── 신청 일정 항목은 없앴다 ──
    # 있던 9건 전부가 오른쪽 레일의 '신청 기간' 과 같은 날짜였다. 같은 값을
    # 241px 짜리 카드로 다시 쓸 이유가 없다. 종료·예정 안내는 히어로 배지 옆 문장이 한다.

    return "\n".join(parts)


_NO_DOC_RE = re.compile(r"^(해당\s*없음|없음|불필요|미해당|-|없다)$")


def _real_documents(documents) -> list[str]:
    """'해당없음' 뿐인 서류 목록은 빈 목록으로 본다.

    원문에 서류 정보가 없다는 뜻인데, 그 한 단어 때문에 다른 항목과 같은 크기의
    카드가 화면에 섰다. 37건 중 7건이 정확히 이 경우였다.
    '공고 확인' 같은 값은 지우지 않는다 — 그건 안내이지 부재가 아니다.
    """
    items = [str(d).strip() for d in (documents or []) if str(d).strip()]
    if not items:
        return []
    if all(_NO_DOC_RE.match(re.sub(r"[\s·•○●\-]+", " ", i).strip()) for i in items):
        return []
    return items


# 질문이 어느 항목의 영역인지 알아보는 어구. 값이 아니라 '주제' 만 본다.
_FAQ_TOPICS = (
    ("benefit",     r"금액|얼마|지원금|지원 ?규모|얼마나 받|지원 ?내용|주요 ?내용|주요 ?서비스"),
    ("eligibility", r"대상|자격|누가|받을 수 있|해당되|신청할 수 있는"),
    ("steps",       r"어떻게 신청|신청 ?방법|어디서 신청|어디에 신청|신청하려면|어떻게 받"),
    ("docs",        r"서류|구비|준비물"),
    ("period",      r"언제까지|신청 ?기간|마감|접수 ?기간|언제 신청"),
    ("contact",     r"문의|어디에 물어|연락"),
)


def _useful_faq(faq: list[dict], record: ProgramRecord, *, eligibility: bool,
                steps: bool, docs: bool) -> list[dict]:
    """페이지 다른 곳에 이미 답이 있는 질문을 뺀다.

    37건을 재보니 생성된 질문 55개 중 42개가 되묻기였다. "…금액은 얼마인가요?"
    18개의 답은 바로 위 '지원 내용' 원문에 그대로 있다. FAQ 가 154px 를 쓰면서
    새로 알려 주는 것이 없었다.

    ⚠️ 주제어가 겹친다고 무조건 빼지 않는다. **그 답을 담은 항목이 이 페이지에
       실제로 있을 때만** 뺀다. 서류 항목이 없는 제도에서 '서류' 질문은 유일한
       정보원이므로 남긴다.

    이 판정은 렌더 단계에서 한다. 저장된 해설(`_prose`)은 그대로 두므로,
    규칙을 고치면 Groq 재호출 없이 rerender.py 만으로 다시 반영된다.
    """
    period = record.apply_period
    covered = {
        "benefit": bool(str(record.benefit_raw or "").strip()),
        "eligibility": eligibility,
        "steps": steps,
        "docs": docs,
        "period": bool(period.always or period.start or period.end),
        "contact": bool(str(record.contact_raw or "").strip()),
    }
    out = []
    for item in faq:
        question = str(item.get("q", ""))
        if any(covered[key] and re.search(pat, question) for key, pat in _FAQ_TOPICS):
            continue
        out.append(item)
    return out


def _contains(outer: str, inner: str) -> bool:
    """공백·구두점을 지운 뒤 한쪽이 다른 쪽을 통째로 품고 있는지."""
    def norm(t: str) -> str:
        return re.sub(r"[\s·,.()\[\]○●◦□■▪•\-*]+", "", t)
    a, b = norm(outer), norm(inner)
    return bool(b) and b in a


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
