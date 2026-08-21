"""대상 분류가 '신청 대상' 과 '그냥 본문에 나온 말' 을 가르는지 고정한다.

키워드가 본문에 있다고 그 사람이 신청 대상인 것은 아니다. 아래 표는 발행된
제도에서 실제로 잘못 붙었던 태그와, **반대로 절대 잃으면 안 되는 태그**를
함께 담는다. 둘을 같이 두는 이유가 있다:

  놓치는 쪽이 더 나쁘다. 태그를 잘못 주면 목록에 엉뚱한 제도가 한 줄 끼는
  것이지만, 태그를 잃으면 받을 수 있는 사람이 그 제도를 영영 못 찾는다.
  그래서 규칙을 조일 때마다 '살아 있어야 할 것' 을 함께 확인한다.

분류 규칙(taxonomy.NOT_AUDIENCE_PHRASES·NEGATION_MARKERS)을 손대면 이걸 먼저 돌린다.

    python3 scripts/check_audience.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import taxonomy  # noqa: E402

# (설명, 본문, 붙으면 안 되는 대상, 반드시 붙어야 하는 대상)
CASES: list[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = [
    # ── 붙으면 안 되는 것들 (실제로 잘못 붙었던 사례) ──
    ("제외 목록 안의 '노인'",
     "전기 요금 복지할인 다만, 다음 법령에 해당하는 사회복지시설은 감액대상에서 "
     "제외합니다. 노인복지법 제32조 제1항 제3호 노인복지주택",
     ("senior",), ()),
    ("창업 인큐베이팅의 '보육'",
     "모두의창업 예비창업자의 성공적인 창업을 위한 보육공간 및 창업프로그램 지원",
     ("parent",), ("business",)),
    ("기관 이름 안의 '노인'",
     "자영업자 실업급여 고유번호를 부여받은 자영업자로서 가정어린이집, "
     "민간어린이집, 노인장기요양기관을 운영하는 사람",
     ("senior",), ("business",)),
    ("다른 급여를 받는 사람이라는 뜻의 '수급자'",
     "특별현금급여 가족요양비 지급액 : 매월 수급자에게 233,400원 지급 "
     "소득수준과 상관없이 지급",
     ("lowincome",), ()),
    ("결혼이민자는 신혼부부가 아니다",
     "결혼이민자 통번역서비스 한국말이 서툰 결혼이민자의 가족·사회생활 지원",
     ("newlywed",), ()),
    ("'사업자등록 없는 자' 는 소상공인이 아니다",
     "근로·자녀장려금 사업자등록 없는 자의 사업소득, 사업자등록 없는 자에게 받은 근로소득",
     ("business",), ()),
    ("지급 제외 목록 안의 '수급자'",
     "훈련장려금 지급 자격을 충족하는 경우에 한하여 지급"
     "(실업급여수급자, 공공근로참여자 등 미지급)",
     ("lowincome",), ()),

    # ── 반드시 남아야 하는 것들 (본문 깊숙이 적힌 진짜 자격 경로) ──
    ("금리우대 대상은 진짜 자격이다",
     "내집마련 디딤돌 대출 금리우대 - 다자녀 가구 0.7%p, 장애인 가구, "
     "신혼 가구(결혼예정자 포함) 각각 우대",
     (), ("parent", "disabled", "newlywed")),
    ("'구직급여 수급자격' 은 구직자다 — 같은 문장의 '수급자' 만 걸러야 한다",
     "행복주택 공급 퇴직 후 1년이 지나지 않는 사람 중 구직급여 수급자격을 인정 받은 사람",
     (), ("jobseeker",)),
    ("'실업급여 수급자' 도 구직자 태그는 살아야 한다",
     "심리안정지원 프로그램 국민취업지원제도 참여자, 실업급여 수급자, 장기실직자 등",
     ("lowincome",), ("jobseeker",)),
    ("기초생활·차상위는 진짜 소득 기준이다",
     "정보통신 보조기기 보급 기초생활수급권자 및 차상위장애인은 90%까지 지원",
     (), ("lowincome", "disabled")),
    ("제목에 있는 대상은 무조건 인정",
     "한부모가족 임대주택 특별공급",
     (), ("parent",)),

    # ── 다문화가족(2026-08 추가) ──
    # '결혼' 이 들어 있다고 신혼부부가 아니다. newlywed 의 NOT_AUDIENCE_PHRASES
    # 에 '결혼이민' 을 넣은 것과 이 대상이 생긴 것이 한 짝이다.
    ("결혼이민자는 다문화가족이지 신혼부부가 아니다",
     "결혼이민자 통번역서비스 한국말이 서툰 결혼이민자의 가족·사회생활 지원",
     ("newlywed",), ("multicultural",)),
    ("금리우대의 '다문화 가구' 도 진짜 자격이다",
     "내집마련 디딤돌 대출 금리우대 - 다문화 가구, 장애인 가구 각각 우대",
     (), ("multicultural", "disabled")),
    ("'외국인' 만으로는 다문화가족이 아니다",
     "외국인등록증을 제출한 사업주에게 지급하는 고용장려금",
     ("multicultural",), ()),
]

failures: list[str] = []


def main() -> int:
    for label, blob, forbidden, required in CASES:
        got = set(taxonomy.classify_audiences(blob))
        bad = sorted(set(forbidden) & got)
        missing = sorted(set(required) - got)
        ok = not bad and not missing
        print(f"  {'✓' if ok else '✗'}  {label}")
        if bad:
            print(f"        붙으면 안 되는데 붙음: {', '.join(bad)}")
        if missing:
            print(f"        반드시 있어야 하는데 없음: {', '.join(missing)}")
        if not ok:
            failures.append(label)
        if not ok:
            print(f"        (판정 결과: {sorted(got) or '없음'})")

    print()
    if failures:
        print(f"✗ {len(failures)}건 실패")
        return 1
    print(f"✅ {len(CASES)}건 전부 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
