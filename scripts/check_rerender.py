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
  · 해설을 새로 만드는 경로에서 상세 조회가 **실패하면** 저장된 상세 값을 이어
    쓰고, 조회에 **성공했는데** 비어 있으면 되살리지 않는다.
  · 표적 재생성(regenerate.py)이 더 얇게 써서 되돌리면 원장 항목·레코드 파일·
    페이지 파일이 **한 글자도 안 바뀐 채** 남고, 그 제도는 원문이 바뀌기 전까지
    한동안 다시 고르지 않는다. 더 두껍게 쓴 것은 평소처럼 받아들인다.
    (되돌린다면서 판·수정일을 올려 둔 채로 두던 것이 513번, 같은 제도를 매일
     다시 골라 재생성 몫의 4분의 3을 버리던 것 — 2026-11-28)

처음 만든 판에서 고친 것 (2026-11-28 리뷰)
──────────────────────────────────────────
  · 표본을 '저장 레코드와 원장 해시가 맞는 것' 에서만 뽑는다. reclassify_audiences
    ·upgrade_urls 는 일부러 원장 해시를 안 맞춰 다음 동기화가 재생성하게 하는데,
    그런 제도가 표본에 들면 진짜 코드는 바르게 '변경' 으로 잡는데도 이 검사가
    실패하고 배포를 막았다. 그리고 엉뚱하게 mark_relinked 를 탓했다.
  · 상태만 바뀐 절은 실제 마감일에 기대지 않는다. 데이터의 날짜는 전부 2026년이라
    2027-01-01 부터는 후보가 없어 이 절이 조용히 건너뛰고 ✅ 를 냈을 것이다.
    복사본 안에서 마감일을 만들어 넣고, 후보가 없으면 실패로 본다.
  · 페이지에 '새 링크가 있다' 는 정확한 주소로 본다. 'plus.gov.kr' 이 들어 있는지만
    보던 판은 표본 40건 중 39건이 이미 그 주소라 아무것도 확인하지 않았다.
  · --inside 를 손으로 실제 저장소에서 돌리면 진짜 레코드를 망가뜨린다. 복사본
    안에서만 돌도록 막았고, 실패하면 오류 전문을 보여 줘서 손으로 돌릴 일이 없게 했다.

    python3 scripts/check_rerender.py
"""
from __future__ import annotations

import copy
import os
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
SANDBOX_ENV = "WALAPP_RERENDER_SANDBOX"


def outer() -> int:
    """임시 폴더에 복사본을 만들고 그 안에서 이 파일을 다시 돌린다."""
    with tempfile.TemporaryDirectory(prefix="walapp-rerender-") as tmp:
        tmp = Path(tmp)
        for name in ("scripts", "_records", "_programs", "_data"):
            shutil.copytree(ROOT / name, tmp / name,
                            ignore=shutil.ignore_patterns("__pycache__"))
        env = dict(os.environ, **{SANDBOX_ENV: str(tmp.resolve())})
        proc = subprocess.run([sys.executable, "-I", str(tmp / "scripts" / Path(__file__).name),
                               "--inside"], cwd=tmp, capture_output=True, text=True, env=env)
        out = [l for l in proc.stdout.splitlines() if l.strip()]
        print("\n".join(out))
        if proc.returncode != 0 and proc.stderr.strip():
            # 전문을 보여 준다. 마지막 한 줄만 보여 줬더니 원인을 보려고 --inside 를
            # 손으로 돌리고 싶어지는데, 그건 실제 저장소를 망가뜨린다(inside 의 가드).
            print(proc.stderr.rstrip())
        return proc.returncode


def inside() -> int:
    # ⚠️ 복사본 안에서만 돈다. 이 함수는 레코드를 지우고 가짜 링크와 미래 날짜를
    #    써 넣는다 — 실제 저장소에서 돌면 진짜 해설 하나가 지워지고 원장 확인일이
    #    2030년이 된다(리뷰에서 재현됐다).
    sandbox = os.environ.get(SANDBOX_ENV)
    here = Path(__file__).resolve()
    if not sandbox or Path(sandbox) not in here.parents:
        print("✗ --inside 는 임시 복사본 안에서만 돕니다. 인자 없이 실행하세요:\n"
              "    python3 scripts/check_rerender.py")
        return 2
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

    reg0 = registry.Registry()

    def consistent(pid, r) -> bool:
        """저장 레코드(상세분을 비운 것)의 해시가 원장 해시와 같은가."""
        e = reg0.get(pid)
        return e is not None and schema.compute_hash(as_list_row(r)) == e.content_hash

    # ── ① 링크만 바뀐 날 ──
    eligible = [pid for pid, r in sorted(recs.items())
                if registry.load_prose(pid) is not None and r.official_url
                and any(getattr(r, f) for f in adapters.enriched_fields(r.source))]
    pool = [pid for pid in eligible if consistent(pid, recs[pid])]
    skipped = len(eligible) - len(pool)
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
    # 해설 없는 제도를 만든다 (복사본 안에서만). ② 전에 되돌린다.
    no_prose_text = registry.load_prose(no_prose)
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
        if f'official_url: "{NEW_LINK.format(s.source_id)}"' not in page:
            failures.append(f"{name}: 페이지에 새 링크가 찍히지 않았습니다")

    feed(rows)
    res2 = sync.run(reg, today + timedelta(days=1))
    # 첫날 링크 갱신을 거친 것만 본다. 첫날 '변경' 이었던 것은 mark_relinked 를
    # 거치지 않았으니 이튿날 또 '변경' 인 게 맞다 — 그걸 세면 엉뚱한 함수를 탓한다.
    again = relinked & ({r.id for r in res2.relinked} | {r.id for r in res2.changed})
    if again:
        failures.append(f"이튿날 같은 목록인데 링크 갱신분 {len(again)}건이 또 바뀐 것으로 "
                        f"잡힙니다 — mark_relinked 가 원장 해시를 안 맞췄습니다")
    print(f"링크만 바뀐 날: 표본 {len(linked)}건 · 링크만변경 {len(relinked)} · 변경 {len(changed)} "
          f"· 이튿날 다시 잡힘 {len(again)}"
          + (f" (원장과 해시가 안 맞아 표본에서 뺀 것 {skipped}건 — 다음 동기화가 재생성할 것들)"
             if skipped else ""))

    # ── ② 상태만 바뀐 날 ──
    # 실제 마감일에 기대지 않는다(데이터의 날짜가 다 지나면 후보가 사라진다).
    # 복사본 안에서 몇 건에 2029년 기간을 넣고 원장 해시·상태를 맞춘 뒤, 2030-01-01
    # 에 동기화한다. 그날 그 제도들은 내용 그대로 '종료' 로 바뀌어야 한다.
    registry.save_record(registry.load_record(no_prose), no_prose_text)
    reg = registry.Registry()
    recs = registry.load_all_records()
    controls = {both, no_prose} | set(linked)
    planted = [pid for pid in pool if pid not in controls][:3]
    for pid in planted:
        r = recs[pid]
        r.apply_period.always = False
        r.apply_period.start, r.apply_period.end = "2029-01-01", "2029-12-31"
        r.status = schema.resolve_status(r, date(2029, 6, 1))
        registry.save_record(r, registry.load_prose(pid))
        e = reg.get(pid)
        e.content_hash = schema.compute_hash(as_list_row(r))
        e.status = r.status
    reg.save()
    day = date(2030, 1, 1)
    rows = []
    for pid, r in sorted(registry.load_all_records().items()):
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
    missing = [pid for pid in planted if pid not in ids]
    if len(planted) < 3:
        failures.append(f"상태 시험에 쓸 제도가 모자랍니다 ({len(planted)}건)")
    if missing:
        failures.append(f"기간을 넣어 둔 {len(missing)}건이 마감 다음 날 '상태변경' 으로 잡히지 않았습니다")
    if lost:
        failures.append(f"상태만 바뀌어 다시 찍은 {len(ids)}건 중 {len(lost)}곳에서 상세분이 "
                        f"지워졌습니다: {', '.join(lost[:4])}")
    print(f"상태만 바뀐 날({day}): {len(ids)}건 다시 찍음(심어 둔 {len(planted)}건 포함) "
          f"· 상세분 사라짐 {len(lost)}")

    # ── ③ 해설을 새로 만드는데 상세 조회가 실패한 날 ──
    # 진짜 _write_one 을 오프라인 생성기(client=None)로 돌린다. 상세 조회만 가짜로
    # 바꿔 끼운다: 실패(False) · 예외 · 성공했는데 비어 있음(True).
    reg = registry.Registry()
    recs = registry.load_all_records()
    trio = [pid for pid in pool if pid not in controls and pid not in planted][:3]
    outcomes = {}
    for pid, mode in zip(trio, ("fail", "raise", "empty")):
        stored = recs[pid]
        # ⚠️ 가짜 어댑터도 진짜와 같은 enriched_fields 를 가져야 한다. 활성 인스턴스가
        #    있으면 enriched_fields() 가 그걸 읽으므로, 빠뜨리면 빈 튜플이 되어 아래
        #    비교가 전부 '아무것도 안 봄 = 통과' 가 된다(처음 짰을 때 그랬다).
        fields = adapters.enriched_fields(stored.source)
        class Enricher:
            source = stored.source
            enriched_fields = fields
            def enrich(self, record, _mode=mode):  # noqa: E306
                if _mode == "raise":
                    raise TimeoutError("상세 조회 시간 초과(시험)")
                return _mode == "empty"
        adapters._ACTIVE[stored.source] = Enricher()
        x = as_list_row(stored)
        x.benefit_raw += " (내용 변경 — 시험)"
        x.content_hash = schema.compute_hash(x)
        wr = publish.WriteResult()
        publish._write_one(x, reg, day, None, True, False, wr)
        if pid not in wr.updated:
            # 저장하지 않고 반려됐다면 아래 비교는 아무것도 확인하지 않는다.
            failures.append(f"상세 조회 시험({mode}): _write_one 이 갱신하지 않았습니다 — "
                            f"{(wr.rejected or [{}])[0].get('reason', '이유 없음')}")
            continue
        after = registry.load_record(pid)
        compared = [f for f in fields if getattr(stored, f)]
        if not compared:
            failures.append(f"상세 조회 시험({mode}): 비교할 상세분이 없는 제도를 골랐습니다")
            continue
        outcomes[mode] = all(getattr(after, f) == getattr(stored, f) for f in compared)
    adapters._ACTIVE.clear()
    if len(outcomes) < 3:
        failures.append(f"상세 조회 시험에 쓸 제도가 모자랍니다 ({len(outcomes)}건)")
    if not outcomes.get("fail", True):
        failures.append("상세 조회가 실패(False)했는데 저장된 구비서류·신청URL 이 지워졌습니다")
    if not outcomes.get("raise", True):
        failures.append("상세 조회가 예외를 냈는데 저장된 구비서류·신청URL 이 지워졌습니다")
    if outcomes.get("empty", False):
        failures.append("상세 조회에 성공했고 비어 있었는데 저장된 값을 되살렸습니다 — "
                        "원천이 실제로 지운 서류가 다시 나옵니다")
    print("상세 조회 실패한 날: " + " · ".join(
        f"{m} → {'이어 씀' if k else '비움'}" for m, k in outcomes.items()))

    # ── ④ 표적 재생성이 더 얇게 쓴 날 ──
    # 생성기만 바꿔 끼우고 진짜 regenerate_one 을 돌린다(클라이언트는 쓰이지 않는다).
    import dataclasses
    import generate_program
    import regenerate
    reg = registry.Registry()
    recs = registry.load_all_records()
    used = controls | set(planted) | set(trio)
    # ⚠️ 닫힌 제도는 고르지 않는다. ② 가 복사본에서 2030-01-01 로 동기화해 기간이
    #    지난 제도를 전부 '종료' 로 바꿔 두었고, select_targets 는 종료된 것을 늘
    #    뺀다. 그런 제도를 고르면 아래 '다시 고르는가' 검사가 쿨다운 탓처럼 거짓으로
    #    실패한다(리뷰에서 재현됐다). 다시 읽은 레코드의 상태로 거른다.
    fat = [pid for pid in pool if pid not in used and pid in recs
           and recs[pid].status != "closed"
           and len((registry.load_prose(pid) or {}).get("eligibility") or []) >= 2
           and len((registry.load_prose(pid) or {}).get("steps") or []) >= 2]
    if len(fat) < 2:
        failures.append(f"재생성 시험에 쓸 제도가 모자랍니다 ({len(fat)}건)")
    else:
        thin_pid, thick_pid = fat[0], fat[1]
        memory: dict = {}
        real_generate = generate_program.generate
        kw = dict(min_raw=0, max_own=10 ** 9, names=[])
        # 양성 대조: 기억이 없으면 고르는 제도여야 아래 '안 고른다' 가 의미가 있다.
        baseline, _ = regenerate.select_targets(recs, reg, {}, day + timedelta(days=1), **kw)
        if thin_pid not in {r.id for r in baseline}:
            failures.append(f"재생성 시험 준비 실패: {thin_pid} 는 기억이 없어도 대상이 아닙니다 "
                            f"(상태 {recs[thin_pid].status}) — 시험 제도 고르기를 볼 것")

        # (가) 더 얇게 썼다 → 통째로 되돌린다
        prev = registry.load_prose(thin_pid)
        generate_program.generate = lambda r, c: dict(
            copy.deepcopy(prev), eligibility=prev["eligibility"][:1], steps=prev["steps"][:1], faq=[])
        rec = recs[thin_pid]
        e0 = dataclasses.asdict(reg.get(thin_pid))
        rec_file = registry.RECORDS_DIR / f"{thin_pid}.json"
        page_file = registry.PROGRAMS_DIR / rec.path()
        rec_text, page_text = rec_file.read_text(encoding="utf-8"), page_file.read_text(encoding="utf-8")
        outcome = regenerate.regenerate_one(rec, reg, day, object(), publish.WriteResult(), memory)
        reg.save()
        e1 = dataclasses.asdict(registry.Registry().get(thin_pid))
        name = rec.name[:24]
        if outcome != "reverted":
            failures.append(f"{name}: 더 얇게 썼는데 되돌리지 않았습니다 ({outcome})")
        else:
            moved = [k for k in e0 if e0[k] != e1[k]]
            if moved:
                failures.append(f"{name}: 되돌렸는데 원장의 {', '.join(moved)} 이(가) 바뀌어 있습니다")
            if rec_file.read_text(encoding="utf-8") != rec_text:
                failures.append(f"{name}: 되돌렸는데 레코드 파일이 바뀌어 있습니다")
            if page_file.read_text(encoding="utf-8") != page_text:
                failures.append(f"{name}: 되돌렸는데 페이지 파일이 바뀌어 있습니다 (수정일·사이트맵이 '오늘' 이 된다)")
            if memory.get(thin_pid, {}).get("date") != day.isoformat():
                failures.append(f"{name}: 되돌린 것을 기억하지 않았습니다 — 내일 또 고른다")

        # 이튿날 고르지 않아야 하고, 링크만 바뀌어도 계속 쉬어야 하고, 원문이 바뀌면
        # 다시 골라야 하고, 쉬는 기간이 지나면 다시 골라야 한다.
        reg = registry.Registry()
        recs = registry.load_all_records()
        nxt, cooling = regenerate.select_targets(recs, reg, memory, day + timedelta(days=1), **kw)
        if thin_pid in {r.id for r in nxt}:
            failures.append(f"{name}: 어제 되돌린 제도를 오늘 또 골랐습니다 (원문 그대로)")
        relinked = dict(recs)
        relinked[thin_pid] = copy.copy(recs[thin_pid])
        relinked[thin_pid].official_url = NEW_LINK.format(recs[thin_pid].source_id) + "&moved=again"
        moved, _ = regenerate.select_targets(relinked, reg, memory, day + timedelta(days=1), **kw)
        if thin_pid in {r.id for r in moved}:
            failures.append(f"{name}: 상세 링크만 바뀌었는데 쉬던 것이 풀렸습니다 — 프롬프트는 그대로라 "
                            f"또 얇게 쓰고 또 되돌린다")
        changed_src = dict(recs)
        changed_src[thin_pid] = copy.copy(recs[thin_pid])
        changed_src[thin_pid].benefit_raw = (recs[thin_pid].benefit_raw or "") + " 지원 금액이 올랐습니다."
        again, _ = regenerate.select_targets(changed_src, reg, memory, day + timedelta(days=1), **kw)
        if thin_pid not in {r.id for r in again}:
            failures.append(f"{name}: 원문이 바뀌었는데도 쉬는 중이라 고르지 않았습니다")
        later, _ = regenerate.select_targets(recs, reg, memory,
                                             day + timedelta(days=regenerate.COOLDOWN_DAYS), **kw)
        if thin_pid not in {r.id for r in later}:
            failures.append(f"{name}: {regenerate.COOLDOWN_DAYS}일이 지났는데도 고르지 않았습니다")

        # (나) 더 두껍게 썼다 → 평소처럼 받아들인다 (판 +1 · 수정일 오늘 · 기억 지움)
        reg = registry.Registry()
        prev2 = registry.load_prose(thick_pid)
        generate_program.generate = lambda r, c: dict(
            copy.deepcopy(prev2), eligibility=list(prev2["eligibility"]) + [
                "같은 가구의 다른 구성원이 이미 지원을 받고 있으면 중복 지원이 제한될 수 있습니다",
                "소득·재산 기준은 신청한 달의 공적 자료로 확인합니다"])
        memory[thick_pid] = {"date": "2000-01-01", "content_hash": "x", "times": 3}
        r0 = reg.get(thick_pid).revision
        outcome2 = regenerate.regenerate_one(recs[thick_pid], reg, day, object(), publish.WriteResult(), memory)
        e2 = reg.get(thick_pid)
        nm2 = recs[thick_pid].name[:24]
        if outcome2 != "accepted":
            failures.append(f"{nm2}: 더 두껍게 썼는데 받아들이지 않았습니다 ({outcome2})")
        elif e2.revision != r0 + 1 or e2.last_updated != day.isoformat():
            failures.append(f"{nm2}: 받아들였는데 판·수정일이 오르지 않았습니다")
        elif thick_pid in memory:
            failures.append(f"{nm2}: 받아들였는데 되돌림 기억이 남아 있습니다")
        generate_program.generate = real_generate
        print(f"표적 재생성이 더 얇게 쓴 날: {outcome} · 이튿날 다시 고름 "
              f"{'예' if thin_pid in {r.id for r in nxt} else '아니오'} · 더 두껍게 쓴 것 {outcome2}")

    if failures:
        print()
        for f in failures[:20]:
            print(f"  ✗ {f}")
        print(f"\n저장분으로 다시 찍는 경로에 문제가 있습니다 — {len(failures)}건.")
        return 1
    print("\n✅ 저장분으로 다시 찍기 · 상세 조회 실패 · 재생성 되돌리기가 링크·상세분·판·날짜를 바르게 다룹니다.")
    return 0


if __name__ == "__main__":
    sys.exit(inside() if "--inside" in sys.argv else outer())
