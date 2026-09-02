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

    # ── 신청처를 지어내지 않는지 ──
    #
    # 실패 양상: '고정 사실' 에 접수 기관이 없어서 모델이 소관 부처를 방문처로
    # 삼았다. "보건복지부 지정기관을 방문합니다"(실제 접수: 시·군·구청).
    # 385건 중 101건이 그 상태였다 — 사람을 엉뚱한 건물로 보내는 문장이다.
    rec_with_receiver = record(org="보건복지부", receiver_raw="시·군·구청",
                               how_to_raw="방문신청", contact_raw="보건복지상담센터/129")
    org_cases = [
        ("소관 부처를 신청처로 대면 버린다",
         "준비한 서류를 지참하고 관할 보건복지부 지정기관을 직접 방문합니다.", False),
        ("접수 기관은 그대로 둔다",
         "시·군·구청에 방문하여 신청서를 제출합니다.", True),
        ("원문에 없는 창구를 지어내도 버린다",
         "가까운 주민센터를 방문해 신청하시면 됩니다.", False),
    ]
    for label, body, should_keep in org_cases:
        cleaned, report = verify.scrub(
            {"summary": "시험 제도입니다.", "steps": [{"title": "1단계", "body": body}]},
            rec_with_receiver)
        kept = bool(cleaned.get("steps"))
        ok = kept == should_keep
        print(f"  {'✓' if ok else '✗'}  {label}")
        if not ok:
            failures += 1
            print(f"        기대 {'유지' if should_keep else '폐기'} · 실제 {'유지' if kept else '폐기'}"
                  f" — 걸린 기관명 {report.orgs}")

    # 접수 기관이 비어 있으면 소관 기관은 쓸 수 있어야 한다(더 나은 정보가 없다)
    rec_no_receiver = record(org="보건복지부", receiver_raw="", how_to_raw="방문신청")
    cleaned, _ = verify.scrub(
        {"summary": "시험 제도입니다.",
         "steps": [{"title": "1단계", "body": "보건복지부에서 안내하는 절차에 따릅니다."}]},
        rec_no_receiver)
    ok = bool(cleaned.get("steps"))
    print(f"  {'✓' if ok else '✗'}  접수 기관이 없으면 소관 기관은 허용한다")
    if not ok:
        failures += 1

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
    print(f"✅ {len(CASES) + len(org_cases) + 2}건 전부 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
