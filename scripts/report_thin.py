"""기준선마다 몇 건이 걸리는지 보여 준다 — 범위를 정하기 전에 재는 도구.

애드센스가 "가치가 별로 없는 콘텐츠" 로 반려한 뒤, 무엇을 얼마나 덜어낼지
정해야 했다. 그 결정을 감으로 하지 않으려고 만들었다.

기준은 `own_chars` — 원문 위에 이 사이트가 얹은 글자 수다(요약 + 자격 +
절차 + FAQ + 주의). 원문 인용·표·상용구는 세지 않는다. 그건 우리가 더한
것이 아니기 때문이다. render.py 가 계산해 front matter 로 내보낸다.

⚠️ own_chars 는 '품질' 이 아니라 '분량' 이다. 길다고 좋은 문장은 아니다.
   다만 400자 미만이면 원문 재진술 말고 들어갈 자리가 없다는 것은 맞다.
   기준선을 고른 뒤에는 걸린 페이지 몇 개를 직접 열어 볼 것.

    python3 scripts/report_thin.py            # 분포와 기준선별 건수
    python3 scripts/report_thin.py --list 400 # 400자 미만인 것을 나열
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).parent.parent
PROGRAMS = ROOT / "_programs"
RECORDS = ROOT / "_records"

# 원문 분량을 재는 필드. 표·문의처는 빼고 '읽을 내용' 만 센다.
RAW_FIELDS = ("target_raw", "benefit_raw", "criteria_raw", "how_to_raw")

# 기준선 후보. 진단이 제시한 '상위 40~60건만' 을 글자 수로 옮기면 이 근처다.
THRESHOLDS = (300, 400, 500, 600, 800)

# 글자 수 × 조회수 조합. 광고는 **둘 다** 미만일 때만 뺀다 —
# 사이트에서 가장 얇은 페이지(노후준비서비스제공 141자)의 조회수가 54만이기 때문이다.
PAIRS = ((300, 10_000), (400, 5_000), (400, 10_000), (400, 20_000), (500, 10_000))


def raw_lengths() -> dict[str, int]:
    """제도명 → 원문 글자 수. 우리 문장을 원문과 견주려면 이 값이 필요하다."""
    out: dict[str, int] = {}
    for path in RECORDS.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out[data.get("name", "")] = sum(
            len(str(data.get(f) or "")) for f in RAW_FIELDS)
    return out


def pages() -> list[tuple[int, int, str, str]]:
    """(own_chars, view_count, 분야, 제도명)"""
    out = []
    for path in sorted(PROGRAMS.glob("*/*.md")):
        text = path.read_text(encoding="utf-8")
        head = text.split("---", 2)[1] if text.startswith("---") else ""

        def field(key: str, default: str = "") -> str:
            m = re.search(rf'^{key}:\s*"?([^"\n]*)"?$', head, re.M)
            return m.group(1).strip() if m else default

        own = field("own_chars", "0")
        if not own.isdigit():
            continue
        views = field("view_count", "0")
        out.append((int(own), int(views) if views.isdigit() else 0,
                    field("category"), field("title")))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", type=int, metavar="N",
                    help="N자 미만인 제도를 짧은 순으로 나열한다")
    args = ap.parse_args()

    rows = pages()
    if not rows:
        print("own_chars 가 있는 제도 페이지가 없습니다. "
              "먼저 `python3 scripts/rerender.py` 를 돌리세요.")
        return 1

    rows.sort()
    chars = [c for c, *_ in rows]
    total = len(rows)

    if args.list is not None:
        hit = [r for r in rows if r[0] < args.list]
        print(f"{args.list}자 미만 {len(hit)}건 (전체 {total}건)\n")
        for own, views, cat, name in hit:
            print(f"  {own:>4}자  조회 {views:>9,}  [{cat:<9}] {name}")
        return 0

    print(f"제도 페이지 {total}건 · 자체 문장 글자 수\n")
    print(f"  중앙값 {int(statistics.median(chars))}자 · 평균 {int(statistics.mean(chars))}자 "
          f"· 최소 {min(chars)} · 최대 {max(chars)}")

    print("\n기준선별 — 걸리는 건수와, 남는 쪽의 상태")
    print(f"  {'기준':>6}  {'미만(덜어냄)':>14}  {'남음':>10}  {'남는 쪽 중앙값':>14}")
    for t in THRESHOLDS:
        below = [c for c in chars if c < t]
        above = [c for c in chars if c >= t]
        med = int(statistics.median(above)) if above else 0
        print(f"  {t:>5}자  {len(below):>6}건 ({len(below)*100//total:>2}%)  "
              f"{len(above):>6}건  {med:>10}자")

    print("\n두 조건을 함께 걸었을 때 — 광고를 빼는 규칙은 이쪽이다")
    print(f"  {'글자 / 조회':>16}  {'광고 제외':>12}  {'남는 쪽 중앙값':>14}  {'제외분 조회 지분':>16}")
    total_views = sum(v for _, v, *_ in rows) or 1
    for oc_t, vc_t in PAIRS:
        excl = [r for r in rows if r[0] < oc_t and r[1] < vc_t]
        keep = [r for r in rows if not (r[0] < oc_t and r[1] < vc_t)]
        med = int(statistics.median([r[0] for r in keep])) if keep else 0
        share = sum(r[1] for r in excl) * 100 / total_views
        print(f"  {oc_t:>5}자 / {vc_t:>6,}  {len(excl):>5}건 ({len(excl)*100//total:>2}%)  "
              f"{med:>10}자  {share:>14.1f}%")

    # 조회수 상위가 얇은 쪽에 있으면 그건 덜어낼 대상이 아니다.
    by_views = sorted(rows, key=lambda r: -r[1])[:15]
    thin_top = [r for r in by_views if r[0] < 400]
    print(f"\n조회수 상위 15건 중 400자 미만: {len(thin_top)}건")
    for own, views, cat, name in thin_top:
        print(f"  {own:>4}자  조회 {views:>9,}  {name}")
    if thin_top:
        print("  ↳ 사람이 가장 많이 찾는 제도가 얇다면, 덜어낼 것이 아니라 채울 것이다.")

    # ── 원문과 견주기 ──
    #
    # '얇다' 에는 두 가지가 섞여 있다. 원문 자체가 두어 문장뿐이라 더 쓸 게
    # 없는 것과, 원문은 넉넉한데 우리가 안 쓴 것. 앞은 코드로 못 고치고
    # 뒤는 고칠 수 있다. 섞어 놓으면 어느 쪽에 힘을 쓸지 알 수 없다.
    raws = raw_lengths()
    paired = [(own, views, raws.get(name, 0), name) for own, views, _, name in rows
              if name in raws]
    if paired:
        print("\n원문 길이대별 — 우리가 쓴 분량")
        for lo, hi in ((0, 150), (150, 300), (300, 500), (500, 800), (800, 1500), (1500, 10 ** 9)):
            band = [p for p in paired if lo <= p[2] < hi]
            if not band:
                continue
            label = f"{lo:>4}~{hi:<4}" if hi < 10 ** 9 else f"{lo:>4}~    "
            print(f"  원문 {label}자  {len(band):>3}건 · 자체 문장 중앙값 "
                  f"{int(statistics.median([p[0] for p in band])):>4}자")

        poor = [p for p in paired if p[2] < 400]
        print(f"\n원문이 400자 미만 — 코드로 못 늘리는 쪽: {len(poor)}건 / {len(paired)}")
        print("  원천이 두어 문장뿐이라 무엇을 고쳐도 길어지지 않는다. 사람이 취재하거나, 두는 수밖에 없다.")

        gap = sorted([p for p in paired if p[2] >= 600 and p[0] < 500], key=lambda p: -p[1])
        print(f"\n원문은 넉넉한데(600자+) 우리 문장이 얇은(500자 미만) 것: {len(gap)}건")
        print("  ↳ 여기가 코드로 고칠 수 있는 쪽이다. 재생성하면 늘어난다.")
        for own, views, raw, name in gap[:10]:
            print(f"    자체 {own:>4}자 · 원문 {raw:>5}자 · 조회 {views:>9,}  {name}")
        if len(gap) > 10:
            print(f"    … 외 {len(gap) - 10}건")

    print("\n덜어내는 방법은 둘뿐이다(진단 결론):")
    print("  · 광고만 빼기  — _config.yml 의 ads_min_own_chars / ads_min_view_count")
    print("  · 빌드에서 빼기 — 페이지 자체를 지운다. 되돌리기 어려우므로 신중히")
    print("  noindex 는 색인 지시일 뿐 광고 심사 범위를 좁히지 못한다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
