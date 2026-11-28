"""저장분으로 다시 찍는 두 경로(상태만 바뀜 · 상세 링크만 바뀜)가 제대로 도는지 본다.

왜 만들었나
───────────
2026-11-28 에 두 가지를 한꺼번에 찾았다. 둘 다 '해설을 다시 만들지 않고 저장된
해설로 페이지만 다시 찍는' 자리에서 났고, 둘 다 눈으로는 안 보였다.

  ① 원천이 상세 링크만 옮겼는데(gov.kr → plus.gov.kr, 10-28) 링크가 해시 대상이라
     650건이 '내용 변경' 이 됐다. 하루 10건씩 해설을 새로 만드는 줄에 섰고, 그동안
     확인일이 10-28 에 멈춰 11-27 에 449건이 한꺼번에 30일을 넘겼다.
     → sync._link_only 가 '링크만' 을 가려 저장분으로 다시 찍는다(토큰 0).

  ② 상태만 바뀐 제도를 다시 찍는 경로가 **구비서류·신청 링크를 지웠다.** 그 둘은
     목록이 아니라 상세 조회로 채우는데, 그 경로는 목록 값을 그대로 저장했다.
     9번 일어났고, 12-01 에 상태가 바뀔 9건 중 8건이 또 그렇게 될 참이었다.
     → publish._carry_enriched 가 저장된 레코드에서 되가져온다.

무엇을 하나
───────────
실제 레코드를 임시 폴더에 복사해 놓고, 그 복사본에서 sync → publish 를 **진짜
코드로** 돌린다. 원천 API 와 LLM 은 부르지 않는다 — 목록 응답 모양(상세분이 빈
레코드)을 저장분에서 만들어 넣는다. 작업 트리는 건드리지 않는다.

  · 링크만 바뀐 제도는 '링크만변경' 으로 잡히고, 다시 찍은 뒤 새 링크·오늘
    확인일을 갖고, 구비서류·신청URL·해설·판·수정일은 그대로이며, 이튿날 '동일' 이다.
  · 링크와 내용이 함께 바뀐 제도, 해설이 없는 제도는 '변경' 으로 남는다
    (해설 없는 것을 저장분 경로로 보내면 하루 갱신 상한을 우회하게 된다).
  · 마감일이 지나 상태만 바뀐 제도는 다시 찍은 뒤에도 구비서류·신청URL 이 남는다.

    python3 scripts/check_rerender.py
"""
from __future__ import annotations

import copy
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
NEW_LINK = ("https://plus.gov.kr/portal/benefitV2/benefitTotalSrvcList/benefitSrvcDtl"
            "?svcSeq=1&bnefType=all&svcId={}")
SAMPLE = 40   # 링크 시험에 쓸 제도 수. 전량(수백 건)은 몇십 초가 걸려 표본으로 본다.


def outer() -> int:
    """임시 폴더에 복사본을 만들고 그 안에서 이 파일을 다시 돌린다."""
    with tempfile.TemporaryDirectory(prefix="walapp-rerender-") as tmp:
        tmp = Path(tmp)
        for name in ("scripts", "_records", "_programs", "_data"):
            shutil.copytree(ROOT / name, tmp / name,
                            ignore=shutil.ignore_patterns("__pycache__"))
        proc = subprocess.run([sys.executable, "-I", str(tmp / "scripts" / Path(__file__).name),
                               "--inside"], cwd=tmp, capture_output=True, text=True)
        out = [l for l in proc.stdout.splitlines() if l.strip()]
        print("\n".join(out))
        if proc.returncode != 0 and proc.stderr.strip():
            print(proc.stderr.strip().splitlines()[-1])
        return proc.returncode


def inside() -> int:
    sys.path.insert(0, str(Path(__file__).parent))
    import logging
    logging.disable(logging.CRITICAL)
    import registry, schema, sync, publish  # noqa: E401
    from collect import adapters

    failures: list[str] = []
    recs = registry.load_all_records()

    def as_list_row(r):
        """목록 응답만 받은 모양 — 상세 조회로 채우는 칸이 비어 있다."""
        x = copy.copy(r)
        for f in adapters.enriched_fields(r.source):
            setattr(x, f, [] if isinstance(getattr(x, f), list) else "")
        x.deferred_detail = True
        return x

    def feed(rows):
        class Fake:
            source = "bojo24"
            def fetch(self, limit=None):  # noqa: E301
                return [copy.copy(x) for x in rows]
        adapters.load_adapters = lambda mock=None: [Fake()]

    # ── ① 링크만 바뀐 날 ──
    pool = [pid for pid, r in sorted(recs.items())
            if registry.load_prose(pid) is not None and r.official_url
            and (r.documents_raw or r.apply_url)]
    linked = pool[:SAMPLE]
    if len(linked) < 3:
        print("시험할 레코드가 모자랍니다.")
        return 1
    both, no_prose = linked[0], linked[1]
    rows = []
    for pid, r in sorted(recs.items()):
        x = as_list_row(r)
        if pid in linked:
            x.official_url = NEW_LINK.format(r.source_id)
        if pid == both:
            x.benefit_raw += " (금액 인상)"
        x.content_hash = schema.compute_hash(x)
        rows.append(x)
    # 해설 없는 제도를 만든다 (복사본 안에서만)
    registry.save_record(recs[no_prose], None)

    reg = registry.Registry()
    before = {pid: (e.revision, e.last_updated, e.first_published, e.path)
              for pid, e in reg.entries.items()}
    stored_before = {pid: registry.load_record(pid) for pid in linked}
    prose_before = {pid: registry.load_prose(pid) for pid in linked}
    today = date(2030, 1, 2)
    feed(rows)
    res = sync.run(reg, today)
    relinked = {r.id for r in res.relinked}
    changed = {r.id for r in res.changed}
    expect = set(linked) - {both, no_prose}
    if relinked != expect:
        failures.append(f"링크만변경 판정이 어긋납니다 — 기대 {len(expect)}건, 실제 {len(relinked)}건 "
                        f"(빠짐 {len(expect - relinked)} · 잘못 들어옴 {len(relinked - expect)})")
    for pid, why in ((both, "링크와 내용이 함께 바뀐"), (no_prose, "해설이 없는")):
        if pid not in changed:
            failures.append(f"{why} 제도가 '변경' 으로 남지 않았습니다 ({pid})")

    publish.run([], [], reg, today, client=None, relinked_records=res.relinked)
    reg.save()
    reg = registry.Registry()
    for pid in sorted(relinked & expect):
        s, b, e = registry.load_record(pid), stored_before[pid], reg.get(pid)
        name = s.name[:24]
        if s.official_url != NEW_LINK.format(s.source_id):
            failures.append(f"{name}: 링크가 새 주소로 안 바뀌었습니다")
        for f in adapters.enriched_fields(s.source):
            if getattr(s, f) != getattr(b, f):
                failures.append(f"{name}: 상세 조회로 채웠던 {f} 가 달라졌습니다")
        if (e.revision, e.last_updated, e.first_published, e.path) != before[pid]:
            failures.append(f"{name}: 원장의 판·수정일·경로가 바뀌었습니다")
        if e.last_checked != today.isoformat():
            failures.append(f"{name}: 확인일이 오늘이 아닙니다 ({e.last_checked})")
        if registry.load_prose(pid) != prose_before[pid]:
            failures.append(f"{name}: 해설이 달라졌습니다")
        page = (registry.PROGRAMS_DIR / s.path()).read_text(encoding="utf-8")
        if "plus.gov.kr" not in page:
            failures.append(f"{name}: 페이지에 새 링크가 없습니다")

    feed(rows)
    res2 = sync.run(reg, today + timedelta(days=1))
    again = {r.id for r in res2.relinked} | ({r.id for r in res2.changed} & expect)
    if again:
        failures.append(f"이튿날 같은 목록인데 {len(again)}건이 또 바뀐 것으로 잡힙니다 — 원장 해시를 안 맞췄습니다")
    print(f"링크만 바뀐 날: 표본 {len(linked)}건 · 링크만변경 {len(relinked)} · 변경 {len(changed)} "
          f"· 이튿날 다시 잡힘 {len(again)}")

    # ── ② 상태만 바뀐 날 ──
    recs = registry.load_all_records()
    cands = sorted((r.apply_period.end, pid) for pid, r in recs.items()
                   if r.status == "active" and r.apply_period.end
                   and re.match(r"\d{4}-\d{2}-\d{2}$", r.apply_period.end)
                   and registry.load_prose(pid) is not None
                   and any(getattr(r, f) for f in adapters.enriched_fields(r.source)))
    if not cands:
        print("상태가 바뀔 시험 대상이 없습니다 — 이 절은 건너뜁니다.")
    else:
        end, _ = cands[-1]   # 가장 늦게 끝나는 것 — 그날이 지나면 앞의 것들도 함께 바뀐다
        day = date.fromisoformat(end) + timedelta(days=1)
        rows = []
        for pid, r in sorted(recs.items()):
            x = as_list_row(r)
            x.content_hash = schema.compute_hash(x)
            rows.append(x)
        reg = registry.Registry()
        feed(rows)
        res = sync.run(reg, day)
        ids = [r.id for r in res.restatused]
        before = {pid: registry.load_record(pid) for pid in ids}
        publish.run([], [], reg, day, client=None, restatused_records=res.restatused)
        lost = []
        for pid in ids:
            s, b = registry.load_record(pid), before[pid]
            for f in adapters.enriched_fields(s.source):
                if getattr(b, f) and not getattr(s, f):
                    lost.append(f"{s.name[:24]} ({f})")
        if not ids:
            failures.append("마감일을 넘겼는데 상태만 바뀐 제도가 하나도 잡히지 않았습니다")
        if lost:
            failures.append(f"상태만 바뀌어 다시 찍은 {len(ids)}건 중 {len(lost)}곳에서 상세분이 "
                            f"지워졌습니다: {', '.join(lost[:4])}")
        print(f"상태만 바뀐 날({day}): {len(ids)}건 다시 찍음 · 상세분 사라짐 {len(lost)}")

    if failures:
        print()
        for f in failures[:20]:
            print(f"  ✗ {f}")
        print(f"\n저장분으로 다시 찍는 경로에 문제가 있습니다 — {len(failures)}건.")
        return 1
    print("\n✅ 저장분으로 다시 찍는 두 경로가 링크·상세분·판·확인일을 바르게 다룹니다.")
    return 0


if __name__ == "__main__":
    sys.exit(inside() if "--inside" in sys.argv else outer())
