"""저장된 레코드의 대상(audiences)을 지금의 분류 규칙으로 다시 매긴다.

taxonomy.classify_audiences 를 고쳤을 때 쓴다. 수집 단계는 앞으로 들어오는
레코드만 새 규칙으로 분류하므로, 이미 발행된 것은 옛 규칙의 결과를 그대로
달고 있다.

처음 이 스크립트가 필요했던 이유(2026-08):
  분류가 `any(kw in blob)` 단순 부분일치라, 키워드가 본문에 있기만 하면 태그가
  붙었다. 그런데 그 자리가 신청 대상을 가리키지 않는 경우가 있었다 —
    · 전기 요금 복지할인 → 어르신   "노인복지주택 … 감액대상에서 제외합니다"
    · 모두의창업(로컬트랙) → 양육가정  "창업을 위한 보육공간"(인큐베이팅)
    · 자영업자 실업급여 → 어르신     "노인장기요양기관을 운영하는 사람"
    · 특별현금급여 → 저소득         "수급자에게 233,400원"(소득수준과 무관)

⚠️ audiences 는 해시 대상이다(schema._HASHED_FIELDS). 그래서 content_hash 를
   다시 계산하되 revision 과 last_updated 는 건드리지 않는다. 제도 내용이
   바뀐 게 아니라 우리 분류가 나아진 것뿐인데 last_updated 를 오늘로 올리면
   페이지가 '오늘 갱신됨' 이라고 거짓말한다.

⚠️⚠️ **_records/ 만 고치면 소용이 없다.** 변경 감지는 registry.json 의 해시로
   한다(registry.Registry.is_changed). save_record 는 _records/ 에만 쓰므로,
   registry 쪽 해시를 함께 맞추지 않으면 다음 동기화가 이 제도들을 '변경됨' 으로
   잡아 해설을 통째로 다시 만든다 — 우리가 아끼려던 바로 그 LLM 호출이다.

   mark_updated 는 쓰면 안 된다. 그건 revision 을 올리고 last_updated 를 오늘로
   바꾼다. 여기서는 해시 하나만 맞춘다.

primary_audience 도 audiences 에서 파생되므로 함께 다시 고른다.

    python3 scripts/reclassify_audiences.py --dry-run   # 뭐가 바뀔지만 본다
    python3 scripts/reclassify_audiences.py             # 고치고 페이지를 다시 찍는다
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import registry   # noqa: E402
import render     # noqa: E402
import schema     # noqa: E402
import taxonomy   # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("reclassify")

# 수집 단계가 분류에 쓰는 것과 같은 텍스트. base.py 의 blob 과 맞춰야 한다 —
# 다르면 여기서 매긴 결과와 다음 수집이 매길 결과가 어긋난다.
BLOB_FIELDS = ("name", "target_raw", "benefit_raw", "criteria_raw",
               "source_category_raw", "org")


def blob_of(rec) -> str:
    return " ".join(str(getattr(rec, f, "") or "") for f in BLOB_FIELDS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 바뀔 것만 본다")
    args = ap.parse_args()

    records = registry.load_all_records()
    if not records:
        log.error("_records/ 가 비어 있습니다.")
        return 1

    changed = []
    for pid, rec in sorted(records.items(), key=lambda kv: kv[1].name):
        blob = blob_of(rec)
        before = list(rec.audiences or [])
        after = taxonomy.classify_audiences(blob)
        if before == after:
            continue
        changed.append((pid, rec, before, after))

    if not changed:
        log.info("바뀌는 레코드가 없습니다. 규칙과 저장분이 이미 일치합니다.")
        return 0

    removed = added = 0
    for _, rec, before, after in changed:
        gone = [a for a in before if a not in after]
        new = [a for a in after if a not in before]
        removed += len(gone)
        added += len(new)
        log.info("■ %s", rec.name[:44])
        if gone:
            log.info("     − %s", ", ".join(gone))
        if new:
            log.info("     ＋ %s", ", ".join(new))
        # 대상이 통째로 비면 그 제도는 어느 대상 허브에도 안 뜬다. 눈에 띄게 남긴다.
        if not after:
            log.warning("     ⚠ 대상이 하나도 남지 않았습니다 — 대상 허브에서 사라집니다")

    log.info("레코드 %d개 · 태그 제거 %d · 추가 %d", len(changed), removed, added)

    if args.dry_run:
        log.info("완료(dry-run) — 파일은 쓰지 않았습니다.")
        return 0

    reg = registry.Registry()
    written = skipped = stale = 0
    for pid, rec, _, after in changed:
        # ⚠️ save_record 는 prose 를 넘기지 않으면 저장돼 있던 해설을 통째로
        #    날린다. 반드시 읽어서 그대로 다시 넘길 것.
        prose = registry.load_prose(pid)

        rec.audiences = after
        rec.primary_audience = taxonomy.pick_primary_audience(after, blob_of(rec))
        rec.content_hash = schema.compute_hash(rec)
        registry.save_record(rec, prose)

        # registry 쪽 해시도 맞춘다. 위 주석 참고 — 이걸 빼면 다음 동기화가
        # 전부 '변경됨' 으로 잡는다. revision·last_updated 는 손대지 않는다.
        entry = reg.get(pid)
        if entry is not None:
            entry.content_hash = rec.content_hash
        else:
            stale += 1
            log.warning("registry 에 항목 없음 [%s] — 아직 발행되지 않은 레코드", pid)

        if prose is None:
            log.warning("해설 없음 [%s] — 레코드만 고치고 페이지는 건너뜁니다.", pid)
            skipped += 1
            continue

        path = registry.PROGRAMS_DIR / rec.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render.to_markdown(rec, prose), encoding="utf-8")
        written += 1

    reg.save()

    log.info("완료 — 레코드 %d개 · 페이지 %d건 다시 씀%s", len(changed), written,
             f" · {skipped}건 건너뜀" if skipped else "")
    log.info("registry 해시 %d건 갱신%s", len(changed) - stale,
             f" · {stale}건은 미발행이라 건너뜀" if stale else "")
    log.info("revision·last_updated 는 그대로입니다. 다음 동기화에서 '동일'로 잡힙니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
