"""저장해 둔 레코드 + 해설로 제도 페이지를 전부 다시 찍는다.

템플릿(render.py)을 고쳤을 때 쓴다. 원천 API 를 호출하지 않고 Groq 도 쓰지 않는다 —
`_records/*.json` 에 레코드와 그때 생성된 해설(`_prose`)이 함께 들어 있기 때문이다.
(그러라고 publish.py 가 둘을 같이 저장한다. registry.save_record 주석 참고)

내용이 바뀌는 게 아니라 표현만 바뀌므로 `content_hash` 와 `revision` 은 건드리지 않는다.
동기화가 다음 날 이 제도들을 '변경됨'으로 잡으면 안 된다.

    python3 scripts/rerender.py            # 전부 다시 찍기
    python3 scripts/rerender.py --dry-run  # 몇 건이 바뀌는지만 보기
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("rerender")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 변경 건수만 센다")
    args = ap.parse_args()

    records = registry.load_all_records()
    if not records:
        log.error("_records/ 가 비어 있습니다. 먼저 파이프라인을 한 번 돌리세요.")
        return 1

    changed = unchanged = skipped = 0
    for program_id, record in sorted(records.items()):
        prose = registry.load_prose(program_id)
        if prose is None:
            # 해설이 없으면 본문을 지어낼 수 없다. 건너뛰고 다음 갱신 때 정상 경로로 처리한다.
            log.warning("해설 없음 [%s] — 건너뜁니다.", program_id)
            skipped += 1
            continue

        path = registry.PROGRAMS_DIR / record.path()
        markdown = render.to_markdown(record, prose)
        before = path.read_text(encoding="utf-8") if path.exists() else ""

        if before == markdown:
            unchanged += 1
            continue

        changed += 1
        if not args.dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(markdown, encoding="utf-8")

    verb = "바뀔 예정" if args.dry_run else "다시 씀"
    log.info("완료 — %d건 %s · %d건 동일 · %d건 건너뜀 (전체 %d건)",
             changed, verb, unchanged, skipped, len(records))
    log.info("content_hash·revision 은 건드리지 않았습니다. 다음 동기화에서 '동일'로 잡힙니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
