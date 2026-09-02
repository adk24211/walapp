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
    duplicates: list[str] = field(default_factory=list)   # 같은 말을 나눠 적은 항목
    ungrounded: list[str] = field(default_factory=list)   # 원문에 근거어가 없는 조건

    @property
    def ok(self) -> bool:
        return not self.violations and not self.language and not self.duplicates

    @property
    def fatal(self) -> bool:
        """요약이 통째로 날아갔으면 이 결과물은 쓸 수 없다."""
        return "summary" in self.emptied

    def summary_line(self) -> str:
        if self.ok:
            return "검증 통과"
        bits = []
        if self.duplicates:
            bits.append(f"같은 말 반복 {len(self.duplicates)}건")
        if self.ungrounded:
            bits.append(f"원문에 없는 조건어 {', '.join(self.ungrounded[:5])}")
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
    """원본에서 허용되는 숫자 집합.

    ⚠️ 알려진 한계: **단위를 보지 않는다.** 원문 어디에든 '31' 이 있으면
       생성문의 '31세' 도 '31일' 도 '31회' 도 통과한다. 원문이 길수록 허용
       집합이 커지므로(800자+ 구간 중앙값 15개 · 최대 49개) 긴 원문일수록
       느슨하다.

       (숫자, 단위) 쌍으로 바꾸는 것을 재 봤다. 385건의 저장된 해설에서
       수치가 든 문장 796개 중 **달라지는 것은 9개뿐**이고, 그 9개가 전부
       정상 문장이었다 — 원문 '3년' 에 생성문 '3년간', 원문 '12개월' 에
       생성문 '1년' 처럼 같은 사실을 다른 말로 쓴 것들이다. 잡는 것 없이
       멀쩡한 문장만 버리므로 바꾸지 않는다.

       바꾸고 싶어지면 먼저 다시 재 볼 것. 코퍼스가 달라지면 답도 달라진다.
    """
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


# ─────────────────────────────────────────────────────────────
#  같은 말을 나눠 적기 · 원문에 근거가 없는 조건
# ─────────────────────────────────────────────────────────────
# 왜 필요해졌나: 출력 항목 수 상한을 원문 길이에 맞춰 올렸다(자격 최대 6 → 9개).
# 그런데 그때 프롬프트에 "자리를 채우려고 같은 말을 나눠 적거나 원문에 없는
# 조건을 만들어 넣으면 검증에서 걸러집니다" 라고 적어 놓고, 정작 그 검사가
# 코드에 없었다. 위의 수치 검증은 **숫자가 붙은 문장만** 본다.
#
# 실제로 재현됐다. 유아학비(원문 1,096자 · 최대 등급)에 원문 근거가 전혀 없는
# 자격 9개("소득 기준을 충족해야 합니다", "재산 기준이 적용됩니다" …)를 넣으면
# violations=[] · dropped=0 으로 전량 통과하고, 페이지와 FAQPage 구조화
# 데이터에까지 실린다. 상한만 올리고 방어를 안 둔 것이다.
#
# 여기서 두 가지를 잡는다. 둘 다 '숫자가 없어서' 기존 검사를 빠져나가는 것들이다.

_STOP_CHARS_RE = re.compile(r"[\s·,()（）\[\]「」/]+")

# 조건을 여는 핵심 명사. 이 말이 생성문에 있는데 원문 어디에도 없으면,
# 그 조건은 원천이 말한 적 없는 것이다.
#
# ⚠️ 여기에 흔한 말을 넣지 말 것. '대상'·'신청'·'지원' 같은 것은 어느 원문에나
#    있어서 검사가 무력해지고, 반대로 너무 좁으면 멀쩡한 문장을 버린다.
#    지어낸 자격 요건에 실제로 반복해서 나타난 것만 둔다.
GROUNDING_TERMS: tuple[str, ...] = (
    "소득", "재산", "자산", "거주", "주민등록", "중복", "가구원", "동의",
    "연령", "나이", "국적", "체류", "보험", "납부", "세대주",
)


def _normalize(text: str) -> str:
    return _STOP_CHARS_RE.sub("", str(text or ""))


def _near_duplicate(a: str, b: str) -> bool:
    """공백·기호를 지운 뒤 한쪽이 다른 쪽에 통째로 들어 있으면 같은 말로 본다.

    "3~5세 유아입니다" 와 "만 3세부터 5세까지의 유아입니다" 처럼 표현만 바꾼
    것까지 잡으려면 이보다 정교해야 하지만, 그 선을 넘으면 멀쩡한 항목을
    버리기 시작한다. 확실한 것만 잡는다.
    """
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return False
    short, long = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(short) < 6:
        return False
    return short in long


def drop_duplicates(items: list[str], report: VerifyReport) -> list[str]:
    """앞 항목과 같은 말을 하는 항목을 버린다."""
    kept: list[str] = []
    for item in items:
        if any(_near_duplicate(item, k) for k in kept):
            report.duplicates.append(item)
            continue
        kept.append(item)
    return kept


def ungrounded_terms(text: str, haystack: str) -> list[str]:
    """생성문에 있는데 원문에는 없는 조건 명사."""
    return [t for t in GROUNDING_TERMS if t in str(text or "") and t not in haystack]


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

    # 조건 명사가 원문에 있는지 볼 때 쓸 원문 뭉치.
    grounding_haystack = " ".join(str(t or "") for t in (
        record.name, record.target_raw, record.benefit_raw,
        record.criteria_raw, record.how_to_raw, " ".join(record.documents_raw),
    ))

    # ── 리스트 필드 ──
    if cleaned.get("eligibility"):
        items = [scrub_text(str(c), allowed, report, codes) for c in cleaned["eligibility"]]
        items = [c for c in items if c]

        # 원문에 근거어가 없는 조건은 버린다.
        #
        # "소득 기준을 충족해야 합니다" 는 숫자가 없어 수치 검증을 그대로
        # 빠져나간다. 그런데 원문에 '소득' 이라는 말이 한 번도 없으면 그 조건은
        # 원천이 말한 적 없는 것이다. 자격 요건은 사람이 '나는 해당하나' 를
        # 판단하는 자리라, 지어낸 조건 하나가 신청을 포기하게 만들 수 있다.
        grounded: list[str] = []
        for item in items:
            missing = ungrounded_terms(item, grounding_haystack)
            if missing:
                report.ungrounded.extend(missing)
                report.dropped.append(item)
                continue
            grounded.append(item)

        # 같은 말을 나눠 적은 것도 버린다.
        cleaned["eligibility"] = drop_duplicates(grounded, report)
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
            if not (question and answer):
                continue
            missing = ungrounded_terms(question + " " + answer, grounding_haystack)
            if missing:
                report.ungrounded.extend(missing)
                report.dropped.append(question)
                continue
            faq.append({"q": question, "a": answer})
        # 질문이 서로 같은 말이면 뒤엣것을 버린다.
        kept_q = drop_duplicates([f["q"] for f in faq], report)
        cleaned["faq"] = [f for f in faq if f["q"] in kept_q]

    # 요약이 날아갔으면 원본 지원내용으로 되돌린다 (사실이므로 언제나 안전)
    if not cleaned.get("summary"):
        cleaned["summary"] = record.benefit_raw

    report.violations = sorted(set(report.violations), key=lambda n: (len(n), n))
    report.ungrounded = sorted(set(report.ungrounded))
    if report.violations or report.duplicates or report.ungrounded:
        log.warning("[%s] %s", record.id, report.summary_line())
    return cleaned, report
