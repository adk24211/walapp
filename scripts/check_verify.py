"""verify.scrub 회귀 검사 — 지어낸 자격 요건이 통과하지 못하는지 본다.

왜 있나: 출력 항목 수 상한을 원문 길이에 맞춰 올리면서(자격 최대 6 → 9개)
프롬프트에 "원문에 없는 조건을 만들어 넣으면 검증에서 걸러집니다" 라고 적었는데,
그 검사가 코드에 없었다. 수치 검증은 **숫자가 붙은 문장만** 본다.

실제로 유아학비(원문 1,096자)에 원문 근거 없는 자격 9개를 넣으면 전량 통과해
페이지와 FAQPage 구조화 데이터에까지 실렸다. 그 구멍을 막고, 다시 열리지
않게 여기에 고정한다.

    python3 scripts/check_verify.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import schema    # noqa: E402
import verify    # noqa: E402


def record(**kw) -> schema.ProgramRecord:
    base = dict(
        id="test-1", source="bojo24", source_id="1", slug="test", name="시험 제도",
        org="시험부", category="living",
        target_raw="○ 만 19세 이상 청년\n○ 소득이 기준 중위소득 100% 이하인 사람",
        benefit_raw="월 30만원을 지원합니다.",
        criteria_raw="", how_to_raw="온라인 신청", documents_raw=["신분증"],
    )
    base.update(kw)
    return schema.ProgramRecord(**base)


# (설명, prose, 살아남아야 하는 자격 수, 반드시 폐기돼야 하는 문구)
CASES = [
    ("원문에 근거어가 없는 조건은 버린다",
     {"summary": "시험 제도입니다.",
      "eligibility": ["소득이 기준을 충족해야 합니다.",
                      "재산 기준이 적용됩니다.",
                      "주민등록상 거주지 요건을 충족해야 합니다."]},
     1, ("재산", "거주")),

    ("같은 말을 나눠 적은 항목은 버린다",
     {"summary": "시험 제도입니다.",
      "eligibility": ["만 19세 이상 청년입니다.",
                      "만 19세 이상 청년입니다.",
                      "만 19세 이상 청년입니다."]},
     1, ()),

    ("원문에 있는 조건은 그대로 둔다",
     {"summary": "시험 제도입니다.",
      "eligibility": ["만 19세 이상 청년입니다.",
                      "소득이 기준 중위소득 100% 이하입니다."]},
     2, ()),

    ("원문에 없는 숫자는 여전히 문장째 버린다",
     {"summary": "시험 제도입니다.",
      "eligibility": ["만 19세 이상 청년입니다.",
                      "소득이 기준 중위소득 250% 이하입니다."]},
     1, ("250",)),
]


def main() -> int:
    failures = 0
    rec = record()
    for label, prose, expect_n, must_drop in CASES:
        cleaned, report = verify.scrub(dict(prose), rec)
        got = cleaned.get("eligibility") or []
        joined = " ".join(got)
        bad = [m for m in must_drop if m in joined]
        ok = len(got) == expect_n and not bad
        print(f"  {'✓' if ok else '✗'}  {label}")
        if not ok:
            failures += 1
            print(f"        기대 {expect_n}개 · 실제 {len(got)}개 — {got}")
            if bad:
                print(f"        버려졌어야 할 문구가 남음: {', '.join(bad)}")

    # FAQ 도 같은 방어를 받는지
    cleaned, _ = verify.scrub(
        {"summary": "시험 제도입니다.",
         "faq": [{"q": "재산 심사는 어떻게 하나요?", "a": "재산 기준으로 심사합니다."}]}, rec)
    ok = not cleaned.get("faq")
    print(f"  {'✓' if ok else '✗'}  FAQ 도 원문에 없는 조건이면 버린다")
    if not ok:
        failures += 1

    print()
    if failures:
        print(f"✗ {failures}건 실패")
        return 1
    print(f"✅ {len(CASES) + 1}건 전부 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
