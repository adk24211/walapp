"""다시 쓰다가 오히려 얇아진 페이지를 이전 해설로 되살린다. **토큰이 들지 않는다.**

`_records/*.json` 에 그때의 해설(`_prose`)이 함께 들어 있고 그 파일이 git 에 있으므로,
이전 판의 해설은 언제든 꺼내 쓸 수 있다. rerender.py 가 공짜로 도는 것과 같은 이유다.

왜 필요했나
───────────
표적 재생성(regenerate.py)은 '원문은 넉넉한데 우리 문장이 얇은' 페이지를 두껍게 하려고
돈다. 그런데 2026-09-02 배치 28건 중 2건이 반대로 갔다.

    구직자 취업지원 서비스 제공   439자 → 205자   (조회 209,401)
    아동발달지원계좌(디딤씨앗통장)  451자 → 357자

앞의 것은 자격 3개가 2개("구직자"/"취업희망자" — 사실상 제목 되풀이)로 줄고, 절차
2단계가 뭉뚱그린 1단계가 되고, '자주 묻는 질문' 절이 통째로 사라졌다. 원문이 635자라
프롬프트가 요구한 하한(자격 4~7 · 절차 2~4)에도 못 미친다. 모델이 하한을 안 지키는 것을
막을 수는 없지만, 그 결과를 받아들일지는 우리가 정할 수 있다.

지금은 regenerate.py 가 그 자리에서 되돌린다. 이 스크립트는 **그 장치가 생기기 전에 이미
얇아진 것**을 위한 것이고, 앞으로도 가드 없이 돈 배치가 있으면 뒤늦게 쓸 수 있다.

무엇을 하지 않나
────────────────
· **한 배치만** 본다. 넓은 구간(예: 재생성 커밋의 부모 ~ HEAD)으로 잡으면 안 된다 —
  처음에 그렇게 돌렸다가 119건이 대상으로 나왔는데, 그 구간에 rescrub_prose 실행분
  (지어낸 접수 기관을 385건 중 134건에서 걷어낸 것)이 들어 있었다. 그 페이지들은
  **일부러** 얇아진 것이고, 되살리면 고친 것을 되돌리는 셈이다.
  그래서 인자를 배치 커밋 하나로 받는다: 그 커밋이 건드린 레코드만, 그 커밋 하나가
  얇게 만든 것만 본다.

· 되살린 뒤에는 `rescrub_prose.py` 를 이어서 돌릴 것. 되살린 해설은 그 배치 **이전**
  판이라 그 뒤에 추가된 검증(지어낸 기관 등)을 아직 안 거쳤다. 둘 다 토큰이 들지 않는다.
· content_hash 를 건드리지 않는다. 제도 정보가 바뀐 게 아니라 우리 문장이 되돌아간
  것이므로, 다음 동기화가 이 제도들을 '변경' 으로 다시 잡으면 안 된다.
· revision·last_updated 는 되살리는 판의 값으로 함께 되돌린다. 내용이 그대로 돌아갔는데
  "오늘 고쳤다" 고 말하는 dateModified 를 남기지 않는다.

    python3 scripts/restore_thinner.py --batch 5d26e7c3 --dry-run
    python3 scripts/restore_thinner.py --batch 5d26e7c3 && python3 scripts/rescrub_prose.py
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import registry  # noqa: E402
import render    # noqa: E402
from schema import ProgramRecord  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("restore_thinner")


def own_len(record: ProgramRecord, prose: dict) -> int:
    """화면에 실제로 실린 우리 문장의 글자 수.

    ⚠️ 저장된 prose 를 그대로 세지 말 것 — render_body 의 _useful_faq 가 되묻는 질문을
       걸러내고 _useful_note 가 상용구를 버리므로 생성된 것과 실린 것이 다르다.
       regenerate.own_len 과 같은 계산이어야 두 곳의 판단이 어긋나지 않는다.
    """
    manifest: dict = {}
    render.render_body(record, prose, manifest=manifest)
    total = manifest.get("own_chars", 0)
    if str(prose.get("summary") or "").strip():
        total += len(str(render._polite(prose.get("summary")) or ""))
    return total


def git_show(ref: str, path: str) -> dict | None:
    """그 시점의 레코드 JSON. 그때 없던 파일이면 None."""
    proc = subprocess.run(["git", "show", f"{ref}:{path}"],
                          cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        log.warning("%s 의 %s 를 읽지 못했습니다.", ref, path)
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", required=True,
                    help="살펴볼 재생성 커밋 하나 (예: 5d26e7c3). 그 커밋이 얇게 만든 것만 되살린다")
    ap.add_argument("--dry-run", action="store_true", help="바꾸지 않고 대상만 보여 준다")
    args = ap.parse_args()

    # 그 커밋이 건드린 레코드만 본다. 전량을 git show 하면 400번 넘게 프로세스를
    # 띄우게 되고, 그 배치가 안 건드린 것은 애초에 비교할 대상이 아니다.
    before_ref = f"{args.batch}^"
    proc = subprocess.run(
        ["git", "diff", "--name-only", before_ref, args.batch, "--", "_records/"],
        cwd=ROOT, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        log.error("git diff 실패: %s", proc.stderr.strip())
        return 1
    changed = [p for p in proc.stdout.split("\n") if p.strip().endswith(".json")]
    if not changed:
        log.info("%s 가 건드린 레코드가 없습니다.", args.batch)
        return 0
    log.info("%s 가 건드린 레코드 %d건을 살펴봅니다.", args.batch, len(changed))

    reg = registry.Registry()
    restored: list[tuple[str, int, int]] = []
    for rel in changed:
        program_id = Path(rel).stem
        old = git_show(before_ref, rel)
        if not old:
            continue  # 그때는 없던 제도 — 되돌릴 이전 판이 없다
        old_prose = old.get("_prose")
        if not isinstance(old_prose, dict) or not old_prose:
            continue

        after = git_show(args.batch, rel)
        after_prose = (after or {}).get("_prose")
        if not isinstance(after_prose, dict) or not after_prose:
            continue
        if after_prose == old_prose:
            continue  # 해설은 그대로고 원문 필드만 바뀐 경우

        record = registry.load_record(program_id)
        if record is None:
            continue

        # ⚠️ 판단은 그 배치의 **전 vs 후** 로만 한다. 지금 파일과 비교하면 그 뒤에
        #    일어난 일(rescrub_prose 가 지어낸 기관 문장을 걷어낸 것 등)까지
        #    "얇아졌다" 로 잡혀, 일부러 줄인 것을 되살리게 된다.
        #
        # ⚠️ 두 해설 모두 **지금 레코드** 로 렌더해 잰다. 옛 레코드로 재면 그 사이
        #    바뀐 원문·템플릿 차이가 섞여 들어와, 해설 때문에 얇아진 것인지
        #    원문이 줄어서인지 구분할 수 없다.
        after_len = own_len(record, after_prose)
        old_len = own_len(record, old_prose)
        if after_len >= old_len:
            continue

        # 그 배치 뒤에 해설이 또 바뀌었다면(rescrub 등) 손대지 않는다. 무엇을
        # 되살려야 맞는지 이 도구가 판단할 수 없다.
        now_prose = registry.load_prose(program_id)
        if now_prose != after_prose:
            log.info("  건너뜀 %s — 그 배치 뒤에 해설이 또 바뀌었습니다. 눈으로 볼 것.",
                     record.name)
            continue

        restored.append((record.name, after_len, old_len))
        log.warning("  ⤺ %s — 배치 후 %d자 · 배치 전 %d자 (%+d)",
                    record.name, after_len, old_len, old_len - after_len)
        if args.dry_run:
            continue

        # 판·날짜도 이전 값으로. 원장과 레코드가 같은 말을 해야 한다.
        for field in ("revision", "last_updated", "last_checked"):
            if field in old:
                setattr(record, field, old[field])
        entry = reg.get(program_id)
        if entry is not None:
            entry.revision = record.revision
            entry.last_updated = record.last_updated
            entry.last_checked = record.last_checked

        registry.save_record(record, old_prose)
        path = registry.PROGRAMS_DIR / record.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render.to_markdown(record, old_prose), encoding="utf-8")

    if not restored:
        log.info("얇아진 페이지가 없습니다. 되돌릴 것이 없습니다.")
        return 0

    if args.dry_run:
        log.info("dry-run — %d건이 대상입니다. 파일은 바꾸지 않았습니다.", len(restored))
        return 0

    reg.save()
    gained = sum(o - n for _, n, o in restored)
    log.info("완료 — %d건 되살림 (합계 %+d자). content_hash 는 건드리지 않았습니다.",
             len(restored), gained)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
