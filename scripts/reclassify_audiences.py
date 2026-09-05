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

⚠️ 원장(registry.json)의 해시는 건드리지 않는다. 한 번 맞춰 봤다가 되돌렸다 —
   자세한 이유는 registry.py 의 mark_checked 위 주석에 적어 뒀다.

   그래서 **분류가 바뀐 레코드는 다음 동기화에서 한 번씩 재생성된다.** 분류를
   해시에 넣기로 한 이상 피할 수 없는 비용이고, 한 번으로 끝난다. 규칙을 자주
   바꾸지 말아야 할 이유이기도 하다 — 2026-08-22 실행에서 8건이 그렇게
   재생성되어 그날 한도 32건 중 8건을 썼다.

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

import audience_overrides  # noqa: E402
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
    """대상 분류에 넘길 글. 수집 단계(collect/adapters/base.py)와 **같아야 한다**.

    둘이 어긋나면 재분류가 수집이 매기는 것과 다른 답을 내고, 다음 동기화가
    그 차이를 '변경' 으로 잡아 재생성이 한 번 더 든다. 한 번 겪은 일이다
    (registry.py 의 mark_checked 위 주석 참고). 그래서 원천 분류 문자열을
    다듬는 규칙은 taxonomy 에 한 번만 정의해 두고 양쪽이 그것을 부른다.
    """
    parts = []
    for f in BLOB_FIELDS:
        v = str(getattr(rec, f, "") or "")
        if f == "source_category_raw":
            v = taxonomy.audience_source_category(v)
        parts.append(v)
    # ⚠️ 줄바꿈으로 잇는다. 공백으로 이으면 strip_exclusion_sections 가
    #    '지원 제외 대상' 다음 필드까지 통째로 삼킨다 — 자세한 사정은
    #    collect/adapters/base.py 의 audience_blob 주석에 적어 뒀다.
    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 바뀔 것만 본다")
    args = ap.parse_args()

    records = registry.load_all_records()
    if not records:
        log.error("_records/ 가 비어 있습니다.")
        return 1

    # ⚠️ 수집(collect/adapters/base.py)과 **같은 순서**로 적용한다 —
    #    규칙으로 뽑고, 그 위에 손으로 적은 덮어쓰기를 얹는다. 한쪽만 얹으면
    #    둘이 다른 답을 내고 다음 동기화가 그 차이를 '변경' 으로 잡는다.
    overrides = audience_overrides.load()
    if overrides:
        log.info("손으로 적은 대상 덮어쓰기 %d건을 함께 적용합니다.", len(overrides))

    changed = []
    for pid, rec in sorted(records.items(), key=lambda kv: kv[1].name):
        blob = blob_of(rec)
        before = list(rec.audiences or [])
        after = audience_overrides.apply(pid, taxonomy.classify_audiences(blob), overrides)
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

    written = skipped = 0
    for pid, rec, _, after in changed:
        # ⚠️ save_record 는 prose 를 넘기지 않으면 저장돼 있던 해설을 통째로
        #    날린다. 반드시 읽어서 그대로 다시 넘길 것.
        prose = registry.load_prose(pid)

        rec.audiences = after
        rec.primary_audience = taxonomy.pick_primary_audience(after, blob_of(rec))
        rec.content_hash = schema.compute_hash(rec)
        registry.save_record(rec, prose)

        if prose is None:
            log.warning("해설 없음 [%s] — 레코드만 고치고 페이지는 건너뜁니다.", pid)
            skipped += 1
            continue

        path = registry.PROGRAMS_DIR / rec.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render.to_markdown(rec, prose), encoding="utf-8")
        written += 1

    log.info("완료 — 레코드 %d개 · 페이지 %d건 다시 씀%s", len(changed), written,
             f" · {skipped}건 건너뜀" if skipped else "")
    log.info("revision·last_updated 는 그대로입니다.")
    log.info("⚠ 다음 동기화에서 이 %d건은 한 번 재생성됩니다(위 주석 참고).", len(changed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
