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
    dropped: list[str] = field(default_factory=list)      # 버려진 문장
    emptied: list[str] = field(default_factory=list)      # 내용이 다 날아간 필드

    @property
    def ok(self) -> bool:
        return not self.violations

    @property
    def fatal(self) -> bool:
        """요약이 통째로 날아갔으면 이 결과물은 쓸 수 없다."""
        return "summary" in self.emptied

    def summary_line(self) -> str:
        if self.ok:
            return "검증 통과"
        return (f"위반 수치 {len(self.violations)}건({', '.join(self.violations[:5])}) "
                f"· 문장 {len(self.dropped)}개 폐기")


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


def scrub_text(text: str, allowed: set[str], report: VerifyReport) -> str:
    """원본에 없는 수치가 든 문장을 제거한다."""
    kept: list[str] = []
    for sentence in _split_sentences(text):
        bad = [t for t in fact_tokens(sentence) if t not in allowed]
        if bad:
            report.violations.extend(bad)
            report.dropped.append(sentence)
            continue
        kept.append(sentence)
    return " ".join(kept).strip()


def scrub(prose: dict, record: ProgramRecord) -> tuple[dict, VerifyReport]:
    """생성된 해설에서 검증 실패 문장을 걷어낸다.

    반환한 prose 는 그대로 렌더에 넣어도 안전하다.
    """
    allowed = allowed_numbers(record)
    report = VerifyReport()
    cleaned = dict(prose)

    # ── 단문 필드 ──
    for key in ("summary", "note"):
        if cleaned.get(key):
            value = scrub_text(str(cleaned[key]), allowed, report)
            cleaned[key] = value
            if not value:
                report.emptied.append(key)

    # ── 리스트 필드 ──
    if cleaned.get("eligibility"):
        items = [scrub_text(str(c), allowed, report) for c in cleaned["eligibility"]]
        cleaned["eligibility"] = [c for c in items if c]
        if not cleaned["eligibility"]:
            report.emptied.append("eligibility")

    # ── steps ──
    if cleaned.get("steps"):
        steps = []
        for step in cleaned["steps"]:
            body = scrub_text(str(step.get("body", "")), allowed, report)
            if body:
                steps.append({"title": step.get("title", ""), "body": body})
        cleaned["steps"] = steps
        if not steps:
            report.emptied.append("steps")

    # ── FAQ — 질문·답변 중 하나라도 비면 항목째 버린다 ──
    if cleaned.get("faq"):
        faq = []
        for item in cleaned["faq"]:
            question = scrub_text(str(item.get("q", "")), allowed, report)
            answer = scrub_text(str(item.get("a", "")), allowed, report)
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
