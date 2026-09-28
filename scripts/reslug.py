"""저장된 레코드의 slug 를 제도명에서 **다시 계산해** 페이지를 옮긴다. 토큰이 들지 않는다.

왜 필요했나
───────────
slug 는 제도명에서 나오는 파생값인데 레코드에 그대로 저장된다. 동기화는 매번
원천 값으로 레코드를 새로 만들므로 제도명이 바뀌면 slug 도 따라 바뀐다 —
어긋나는 경우는 하나뿐이다: **slug 규칙 자체를 고쳤을 때.** 그때는 이름이 그대로라
동기화가 '동일' 로 잡고, 저장된 옛 slug 가 영원히 남는다.

2026-09-27 에 schema.make_slug 가 로마숫자·동그라미 숫자를 숫자로 옮기도록
바뀌었다. 그 글자들이 통째로 버려져 서로 다른 두 제도가 같은 파일을 가리키고
있었기 때문이다(그 함수 위 주석에 경위가 있다). 이 스크립트가 그 변경을
저장된 레코드에 반영한다.

무엇을 하나
───────────
  · 레코드의 slug 를 make_slug(name) 로 다시 계산한다.
  · 페이지를 새 경로로 옮긴다 — 새 경로에 쓰고 예전 경로를 지운다.
  · 원장의 slug·path 도 함께 맞춘다. 원장과 파일이 다른 말을 하면
    check_pages.py 가 잡는다.

무엇을 하지 않나
────────────────
· content_hash·revision·날짜를 건드리지 않는다. 제도 정보가 바뀐 게 아니라
  주소가 바뀐 것이다. 다음 동기화가 이 제도들을 '변경' 으로 잡으면 안 된다.
· 해설을 다시 만들지 않는다. `_records/*.json` 의 `_prose` 를 그대로 쓴다.
· **주소가 바뀐다.** 예전 주소는 404 가 된다(GitHub Pages 라 리다이렉트를
  둘 수 없다). 그래서 한 건도 조용히 넘기지 않고 전부 로그로 남긴다.

    python3 scripts/reslug.py --dry-run
    python3 scripts/reslug.py
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
import schema    # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("reslug")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 대상만 보여 준다")
    args = ap.parse_args()

    records = registry.load_all_records()
    if not records:
        log.error("_records/ 가 비어 있습니다.")
        return 1

    reg = registry.Registry()
    moved: list[tuple[str, str, str]] = []

    for program_id, record in sorted(records.items()):
        new_slug = schema.make_slug(record.name, record.source_id)
        if new_slug == record.slug:
            continue

        old_rel = record.path()
        record.slug = new_slug
        new_rel = record.path()
        moved.append((record.name, old_rel, new_rel))
        log.warning("  %s\n      %s\n   →  %s", record.name, old_rel, new_rel)

        if args.dry_run:
            continue

        prose = registry.load_prose(program_id)
        if prose is None:
            log.warning("     해설이 없어 페이지를 쓰지 못했습니다 — 레코드만 고칩니다.")
        else:
            new_path = registry.PROGRAMS_DIR / new_rel
            new_path.parent.mkdir(parents=True, exist_ok=True)
            new_path.write_text(render.to_markdown(record, prose), encoding="utf-8")

        # ⚠️ 예전 페이지를 지우기 전에 **그 파일의 주인**을 확인한다. slug 충돌로
        #    두 제도가 같은 파일을 가리키던 상황을 정리하는 중이므로, 확인 없이
        #    지우면 다른 제도의 페이지를 지울 수 있다.
        old_path = registry.PROGRAMS_DIR / old_rel
        if old_path.exists() and registry.page_owner(old_path) == program_id:
            old_path.unlink()
            log.info("     예전 페이지 삭제: %s", old_rel)

        registry.save_record(record, prose)
        entry = reg.get(program_id)
        if entry is not None:
            entry.slug = new_slug
            entry.path = f"_programs/{new_rel}"

    if not moved:
        log.info("slug 가 규칙과 어긋나는 레코드가 없습니다.")
        return 0

    if args.dry_run:
        log.info("dry-run — %d건이 대상입니다. 파일은 바꾸지 않았습니다.", len(moved))
        return 0

    reg.save()
    log.info("완료 — %d건의 주소가 바뀌었습니다. 예전 주소는 404 가 됩니다.", len(moved))
    log.info("content_hash·revision 은 건드리지 않았습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
