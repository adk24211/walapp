"""생성물 사실 후검증 — LLM이 만들어 낸 숫자를 원본과 대조한다.

구 파이프라인은 이 검증이 원리적으로 불가능했다. 기사 본문을 통째로 넘기고
제목·수치·본문을 자유 생성시켰으니 '무엇이 사실이어야 하는지' 자체가 정의되지
않았다. 그 결과가 `2026-08-12-curious.md` 의 "빛의 속도를 능가하는 에너지 발견"
같은 문장이다.

지금은 사실이 `ProgramRecord` 의 `*_raw` 필드에 고정돼 있다. 따라서
"생성물에 등장한 수치 중 원본에 없는 것"을 기계적으로 골라낼 수 있다.
(REDESIGN.md §6.3)

검증 방식:
  · 숫자 뒤에 '사실 단위'(원·세·개월·%·회 …)가 붙은 토큰만 검사 대상으로 본다.
    단위 없는 숫자는 '3단계', '두 가지' 같은 서술이라 사실 주장이 아니다.
  · 원본 전체(지원대상·지원내용·선정기준·신청방법·서류·기간)에서 뽑은 숫자 집합에
    없으면 위반으로 판정하고, 그 숫자가 들어간 **문장을 통째로 버린다.**
  · 문장을 버려도 남는 내용이 있으면 통과, 아무것도 안 남으면 재생성 신호를 준다.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import schema
from schema import ProgramRecord

log = logging.getLogger(__name__)

# 이 단위가 붙은 숫자는 '사실 주장'으로 본다.
FACT_UNITS = (
    "원", "%", "퍼센트", "세", "개월", "년", "년간", "회", "명", "일", "주",
    "억", "만", "천", "배", "점", "등급", "구간", "평", "제곱미터", "시간",
)
_UNIT_ALT = "|".join(sorted(FACT_UNITS, key=len, reverse=True))

# 예: '최대 20만 원', '19세', '60%', '12개월', '1,200만 원'
_FACT_TOKEN_RE = re.compile(rf"(\d[\d,]*)\s*(?:{_UNIT_ALT})")
_ANY_NUMBER_RE = re.compile(r"\d[\d,]*")

# 문장 분리 — 존댓말 종결 + 마침표/물음표/느낌표
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|(?<=다\.)\s*|(?<=요\.)\s*")


@dataclass
class VerifyReport:
    violations: list[str] = field(default_factory=list)   # 원본에 없던 숫자
    language: list[str] = field(default_factory=list)     # 한국어가 아니거나 코드값
    dropped: list[str] = field(default_factory=list)      # 버려진 문장
    emptied: list[str] = field(default_factory=list)      # 내용이 다 날아간 필드

    @property
    def ok(self) -> bool:
        return not self.violations and not self.language

    @property
    def fatal(self) -> bool:
        """요약이 통째로 날아갔으면 이 결과물은 쓸 수 없다."""
        return "summary" in self.emptied

    def summary_line(self) -> str:
        if self.ok:
            return "검증 통과"
        bits = []
        if self.violations:
            bits.append(f"위반 수치 {len(self.violations)}건({', '.join(self.violations[:5])})")
        if self.language:
            bits.append(f"언어 {len(self.language)}건({', '.join(self.language[:3])})")
        bits.append(f"문장 {len(self.dropped)}개 폐기")
        return " · ".join(bits)


# ─────────────────────────────────────────────────────────────
#  언어 검사 — 한국어가 아닌 것, 그리고 원천 코드값
# ─────────────────────────────────────────────────────────────
# 숫자 검증만으로는 못 잡는 두 가지가 실제로 발행됐다.
#
#  · 중국어 혼입 6건. "온라인이나 방문申请 방법을 통해", "最近 5년 이내",
#    "海外" 가 "外海" 로 뒤집힌 것까지. 모델이 한국어와 중국어를 함께 배운
#    탓이다. 프롬프트에도 못을 박았지만(generate_program.SYSTEM_PROMPT)
#    지시만으로는 새어 나올 수 있으니 여기서 한 번 더 막는다.
#
#  · 원천 코드값 '직접입력' 7건. 게시 기관이 자유 입력란을 골랐다는 뜻인데
#    LLM 이 신청 방법으로 착각해 "직접입력을 통해 신청할 수 있습니다" 라고
#    썼다. 읽는 사람에게 아무 뜻이 없는 문장이다. 지금은 프롬프트에 아예
#    넘기지 않지만(schema.apply_methods), 다른 코드값이 늘어날 수 있다.
#
# 아는 오타는 먼저 고치고, 그러고도 남으면 그 문장을 버린다. 한 글자 때문에
# 멀쩡한 문장을 버리는 게 아깝지만, 한국어 지원금 안내에 중국어가 남아 있는
# 것보다는 낫다. 버린 것은 전부 보고된다.
_CJK_REPAIR = {
    "申请": "신청",
    "最近": "최근",
    "外海": "해외",   # '해외' 가 뒤집혀 나온 것
    "海外": "해외",
}
# 가나 + 한자. prose 는 우리가 생성한 한국어 문장이라 한자가 낄 자리가 없다
# (원문 그대로인 *_raw 필드는 이 검사를 거치지 않는다).
_NON_KOREAN_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")


# 프롬프트의 뼈대를 그대로 옮겨 적는 경우가 있다. '고정 사실' 은 우리가
# 원문 블록에 붙인 이름이지 읽는 사람에게는 아무 뜻이 없는 말이다.
# 실제로 gpt-oss-120b 첫 발행분 FAQ 에 "고정 사실에 따르면 …" 이 나왔다.
# 프롬프트에도 쓰지 말라고 적었지만, 지시만으로는 새어 나온다.
#
# 문장을 버리지 않고 그 어구만 덜어 낸다 — 뒤에 붙은 내용은 멀쩡한 답이다.
#   "고정 사실에 따르면 대상은 내국인입니다." → "대상은 내국인입니다."
_SCAFFOLD_RE = re.compile(
    r"(제공된\s*|주어진\s*)?고정\s*사실(에 따르면|에 근거하면|을 보면|에서는|에는|상)?[,]?\s*")


def repair_language(text: str) -> str:
    """아는 혼입 글자를 한국어로 되돌리고, 프롬프트 뼈대 표현을 걷어낸다."""
    for bad, good in _CJK_REPAIR.items():
        text = text.replace(bad, good)
    return _SCAFFOLD_RE.sub("", text)


def language_violations(sentence: str, code_values: set[str]) -> list[str]:
    """이 문장을 버려야 하는 이유들. 비어 있으면 통과."""
    reasons = []
    found = _NON_KOREAN_RE.findall(sentence)
    if found:
        reasons.append("비한국어 문자 " + "".join(sorted(set(found))))
    for code in code_values:
        if code and code in sentence:
            reasons.append(f"원천 코드값 '{code}'")
    return reasons


def _numbers(text: str) -> set[str]:
    """텍스트에 등장하는 모든 숫자(쉼표 제거)."""
    return {m.group(0).replace(",", "").lstrip("0") or "0"
            for m in _ANY_NUMBER_RE.finditer(str(text or ""))}


def allowed_numbers(record: ProgramRecord) -> set[str]:
    """원본에서 허용되는 숫자 집합."""
    sources = [
        record.name, record.org,
        record.target_raw, record.benefit_raw,
        record.criteria_raw, record.how_to_raw,
        record.apply_period.start, record.apply_period.end,
        " ".join(record.documents_raw),
    ]
    allowed: set[str] = set()
    for text in sources:
        allowed |= _numbers(text)
    # 날짜에서 뽑은 '03' 을 '3월' 로 쓰는 경우가 흔하다
    allowed |= {n.lstrip("0") for n in allowed if n.lstrip("0")}
    return allowed


def fact_tokens(text: str) -> list[str]:
    """검사 대상 숫자(사실 단위가 붙은 것)만."""
    return [m.group(1).replace(",", "").lstrip("0") or "0"
            for m in _FACT_TOKEN_RE.finditer(str(text or ""))]


def _split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(str(text or "")) if p and p.strip()]
    return parts or ([text.strip()] if str(text or "").strip() else [])


def scrub_text(text: str, allowed: set[str], report: VerifyReport,
               code_values: set[str] | None = None) -> str:
    """원본에 없는 수치가 든 문장, 한국어가 아닌 문장을 제거한다."""
    kept: list[str] = []
    for sentence in _split_sentences(repair_language(text)):
        bad = [t for t in fact_tokens(sentence) if t not in allowed]
        if bad:
            report.violations.extend(bad)
            report.dropped.append(sentence)
            continue
        reasons = language_violations(sentence, code_values or set())
        if reasons:
            report.language.extend(reasons)
            report.dropped.append(sentence)
            continue
        kept.append(sentence)
    return " ".join(kept).strip()


def scrub(prose: dict, record: ProgramRecord) -> tuple[dict, VerifyReport]:
    """생성된 해설에서 검증 실패 문장을 걷어낸다.

    반환한 prose 는 그대로 렌더에 넣어도 안전하다.
    """
    allowed = allowed_numbers(record)
    # 이 제도의 원문에 실제로 들어 있던 코드값만 검사한다. 원문에 없던 말이면
    # LLM 이 지어낸 것이고, 그건 숫자 검증이 아니라 다른 문제다.
    codes = {c for c in schema.APPLY_METHOD_DROP if c in str(record.how_to_raw or "")}
    report = VerifyReport()
    cleaned = dict(prose)

    # ── 단문 필드 ──
    for key in ("summary", "note"):
        if cleaned.get(key):
            value = scrub_text(str(cleaned[key]), allowed, report, codes)
            cleaned[key] = value
            if not value:
                report.emptied.append(key)

    # ── 리스트 필드 ──
    if cleaned.get("eligibility"):
        items = [scrub_text(str(c), allowed, report, codes) for c in cleaned["eligibility"]]
        cleaned["eligibility"] = [c for c in items if c]
        if not cleaned["eligibility"]:
            report.emptied.append("eligibility")

    # ── steps ──
    if cleaned.get("steps"):
        steps = []
        for step in cleaned["steps"]:
            body = scrub_text(str(step.get("body", "")), allowed, report, codes)
            if body:
                steps.append({"title": step.get("title", ""), "body": body})
        cleaned["steps"] = steps
        if not steps:
            report.emptied.append("steps")

    # ── FAQ — 질문·답변 중 하나라도 비면 항목째 버린다 ──
    if cleaned.get("faq"):
        faq = []
        for item in cleaned["faq"]:
            question = scrub_text(str(item.get("q", "")), allowed, report, codes)
            answer = scrub_text(str(item.get("a", "")), allowed, report, codes)
            if question and answer:
                faq.append({"q": question, "a": answer})
        cleaned["faq"] = faq

    # 요약이 날아갔으면 원본 지원내용으로 되돌린다 (사실이므로 언제나 안전)
    if not cleaned.get("summary"):
        cleaned["summary"] = record.benefit_raw

    report.violations = sorted(set(report.violations), key=lambda n: (len(n), n))
    if report.violations:
        log.warning("[%s] %s", record.id, report.summary_line())
    return cleaned, report
