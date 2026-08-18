"""저장된 해설을 지금의 검증 기준으로 다시 훑는다.

verify.py 에 검사를 더했을 때 쓴다. 이미 발행된 해설은 그때의 기준으로만
걸러진 것이라, 새 검사에 걸릴 문장이 페이지에 남아 있다.

처음 이 스크립트가 필요했던 이유(2026-08):
  · 중국어 혼입 6건 — "온라인이나 방문申请 방법을 통해", "最近 5년 이내",
    "海外" 가 "外海" 로 뒤집힌 것. 아는 글자는 고쳐서 살린다.
  · 원천 코드값 '직접입력' 7건 — "직접입력을 통해 신청할 수 있습니다" 는
    읽는 사람에게 아무 뜻이 없다. 그 문장만 버리고 나머지는 남긴다.

해설은 content_hash 대상이 아니므로(schema._HASHED_FIELDS) revision 과
last_updated 는 자연히 그대로다. 다음 동기화도 이걸 '변경됨' 으로 잡지 않는다.

    python3 scripts/rescrub_prose.py --dry-run   # 뭐가 바뀔지만 본다
    python3 scripts/rescrub_prose.py             # 고치고 페이지를 다시 찍는다
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import registry  # noqa: E402
import render    # noqa: E402
import verify    # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("rescrub")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 바뀔 것만 본다")
    args = ap.parse_args()

    records = registry.load_all_records()
    if not records:
        log.error("_records/ 가 비어 있습니다.")
        return 1

    changed = skipped = 0
    for pid, rec in sorted(records.items(), key=lambda kv: kv[1].name):
        prose = registry.load_prose(pid)
        if not prose:
            skipped += 1
            continue

        cleaned, report = verify.scrub(prose, rec)
        if cleaned == prose:
            continue

        changed += 1
        log.info("■ %s", rec.name)
        if report.language:
            log.info("     사유: %s", " · ".join(dict.fromkeys(report.language)))
        for sentence in report.dropped:
            log.info("     버림: %s", sentence[:90])
        if report.emptied:
            # 필드가 통째로 비면 페이지에서 그 항목이 사라진다. 눈에 띄게 남긴다.
            log.warning("     ⚠ 비게 된 필드: %s", report.emptied)

        if not args.dry_run:
            registry.save_record(rec, cleaned)
            path = registry.PROGRAMS_DIR / rec.path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(render.to_markdown(rec, cleaned), encoding="utf-8")

    verb = "바뀔 예정" if args.dry_run else "고침"
    log.info("완료 — %d건 %s · %d건 해설 없음 (전체 %d건)", changed, verb, skipped, len(records))
    log.info("해설은 해시 대상이 아니라 revision·last_updated 는 그대로입니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
