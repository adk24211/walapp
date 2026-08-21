"""이미 저장된 레코드의 http:// 링크를 https:// 로 올린다.

수집 단계(collect/adapters/base.py)는 앞으로 들어오는 레코드를 알아서 올린다.
이 스크립트는 그 전에 저장된 것들을 한 번 훑기 위한 것이다.

**네트워크가 필요하다.** 대상은 정부·공공기관 사이트인데 개발 컨테이너에서는
막혀 있는 경우가 많다. 그럴 때는 전부 '확인 안 됨' 이 되어 아무것도 바꾸지
않는다 — 그게 맞는 동작이다. 확인하지 못한 주소를 올리면 신청 링크가 죽을 수
있고, 지원금 페이지에서 신청 버튼이 죽는 건 http 로 나가는 것보다 나쁘다.
실제 전환은 GitHub Actions 처럼 밖으로 나갈 수 있는 곳에서 돌려야 한다.

content_hash 는 바뀐 주소에 맞춰 다시 계산하되 revision 과 last_updated 는
건드리지 않는다. rerender.py 와 같은 이유다: 제도 내용이 바뀐 게 아니라 우리가
같은 곳을 가리키는 더 나은 주소를 쓰게 된 것뿐인데 last_updated 를 오늘로
올리면 페이지가 '오늘 갱신됨' 이라고 거짓말을 한다.

⚠️ 해시는 _records/ 와 registry.json **양쪽** 을 맞춰야 한다. 변경 감지는
   원장 쪽 해시로 하는데(Registry.is_changed) save_record 는 _records/ 에만
   쓴다. 한동안 이 스크립트가 원장을 안 맞추고 있어서, 여기 적힌 "다음
   동기화도 '변경됨' 으로 잡지 않는다" 가 사실이 아니었다 — 주소를 올린
   제도는 다음 실행에서 해설이 통째로 다시 만들어졌다.
   (Registry.sync_hash 주석 참고)

    python3 scripts/upgrade_urls.py --dry-run   # 뭐가 바뀔지만 본다
    python3 scripts/upgrade_urls.py             # 레코드를 고치고 페이지를 다시 찍는다
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
from collect import url_https  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("upgrade_urls")

FIELDS = ("apply_url", "official_url")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 바뀔 것만 센다")
    args = ap.parse_args()

    if url_https.skip_probe():
        log.error("WALAPP_SKIP_HTTPS_PROBE 가 켜져 있습니다. 확인을 해야 올릴 수 있습니다.")
        return 1

    records = registry.load_all_records()
    if not records:
        log.error("_records/ 가 비어 있습니다.")
        return 1

    # 먼저 http 가 몇 건인지 세어 둔다. 프로브가 다 실패했을 때
    # '할 게 없었다' 와 '못 올렸다' 를 구분해서 말하기 위해서다.
    targets = [
        (pid, field) for pid, rec in sorted(records.items()) for field in FIELDS
        if str(getattr(rec, field, "") or "").lower().startswith("http://")
    ]
    if not targets:
        log.info("http:// 주소가 없습니다. 할 일 없음.")
        return 0
    log.info("http:// 주소 %d건 (레코드 %d개)", len(targets), len({pid for pid, _ in targets}))

    changed: list[tuple[str, str, str, str]] = []   # (id, 필드, 전, 후)
    for pid, field in targets:
        rec = records[pid]
        before = getattr(rec, field)
        after = url_https.upgrade(before)
        if after != before:
            setattr(rec, field, after)
            changed.append((pid, field, before, after))

    log.info(url_https.summary())

    if not changed:
        log.warning("올릴 수 있는 주소가 없었습니다 — 확인된 호스트가 하나도 없습니다.")
        log.warning("이 환경에서 해당 사이트로 나갈 수 있는지 먼저 보세요.")
        return 0

    for pid, field, before, after in changed:
        log.info("  %s %s: %s → %s", pid, field, before, after)

    if args.dry_run:
        log.info("완료(dry-run) — 주소 %d건이 바뀔 예정. 파일은 쓰지 않았습니다.", len(changed))
        return 0

    reg = registry.Registry()
    written = skipped = unregistered = 0
    for pid in sorted({pid for pid, _, _, _ in changed}):
        rec = records[pid]

        # ⚠️ save_record 는 prose 를 넘기지 않으면 저장돼 있던 해설(_prose)을
        #    통째로 날린다. 반드시 읽어서 그대로 다시 넘길 것.
        prose = registry.load_prose(pid)

        rec.content_hash = schema.compute_hash(rec)
        registry.save_record(rec, prose)

        # 원장 쪽 해시도 맞춘다. 위 주석 참고 — 이걸 빼면 다음 동기화가
        # 주소를 올린 제도를 '변경됨' 으로 잡아 해설을 다시 만든다.
        if not reg.sync_hash(rec):
            unregistered += 1

        if prose is None:
            # 해설이 없으면 본문을 다시 찍을 수 없다. 레코드는 고쳐 뒀으니
            # 다음 갱신 때 정상 경로로 페이지가 만들어진다.
            log.warning("해설 없음 [%s] — 레코드만 고치고 페이지는 건너뜁니다.", pid)
            skipped += 1
            continue

        path = registry.PROGRAMS_DIR / rec.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render.to_markdown(rec, prose), encoding="utf-8")
        written += 1

    reg.save()

    log.info("완료 — 주소 %d건 · 레코드 %d개 · 페이지 %d건 다시 씀%s",
             len(changed), len({p for p, _, _, _ in changed}), written,
             f" · {skipped}건 건너뜀" if skipped else "")
    log.info("원장 해시 %d건 갱신%s",
             len({p for p, _, _, _ in changed}) - unregistered,
             f" · {unregistered}건은 미발행이라 건너뜀" if unregistered else "")
    log.info("revision·last_updated 는 건드리지 않았습니다. 다음 동기화에서 '동일'로 잡힙니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
