"""원장(registry.json) 해시를 맞추는 일이 제대로 되는지 고정한다.

이 함정에 두 번 걸렸다. 레코드를 고치는 스크립트(upgrade_urls·
reclassify_audiences)는 _records/*.json 만 쓰는데, 변경 감지는 registry.json 의
해시로 한다. 원장을 안 맞추면 다음 동기화가 그 제도들을 '변경됨' 으로 잡아
해설을 통째로 다시 만든다 — 그 스크립트들이 아끼려던 바로 그 LLM 호출이다.

게다가 조용히 틀린다. 스크립트는 성공했다고 로그를 찍고, 청구서는 다음 날
다른 실행에서 나온다. 그래서 기계가 봐야 한다.

    python3 scripts/check_registry.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import registry  # noqa: E402
import schema    # noqa: E402

# 원장 항목에서 sync_hash 가 건드리면 안 되는 값들.
# revision 이나 last_updated 가 올라가면 페이지가 '오늘 갱신됨' 이라고 거짓말한다.
FROZEN = ("revision", "last_updated", "last_checked", "first_published", "status", "name", "slug")

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'}  {label}{'  — ' + detail if detail else ''}")
    if not ok:
        failures.append(label)


def main() -> int:
    reg = registry.Registry()
    records = registry.load_all_records()
    if not records:
        check("_records/ 에 레코드가 있어야 검사할 수 있다", False, "비어 있음")
        return 1

    pid, rec = next(iter(sorted(records.items())))
    rec = copy.deepcopy(rec)
    before = copy.deepcopy(reg.get(pid))
    if before is None:
        check("원장에 항목이 있는 레코드를 골라야 한다", False, pid)
        return 1

    # 해시 대상 필드를 하나 바꾼다 (upgrade_urls 가 apply_url 을 바꾸는 것과 같다)
    rec.apply_url = "https://example.go.kr/checked-by-check-registry"
    rec.content_hash = schema.compute_hash(rec)

    check("맞추기 전에는 '변경됨' 으로 잡힌다", reg.is_changed(rec) is True,
          "이게 False 면 검사 자체가 무의미하다")
    check("sync_hash 가 항목을 찾아 맞춘다", reg.sync_hash(rec) is True)
    check("맞춘 뒤에는 '변경됨' 으로 잡히지 않는다", reg.is_changed(rec) is False,
          "여기가 True 면 다음 동기화가 해설을 다시 만든다")

    after = reg.get(pid)
    drifted = [f for f in FROZEN if getattr(before, f) != getattr(after, f)]
    check(f"건드리면 안 되는 값 {len(FROZEN)}개가 그대로다",
          not drifted, "바뀐 것: " + ", ".join(drifted) if drifted else "")

    # mark_updated 와 헷갈리면 안 된다 — 그건 revision 을 올리는 게 맞는 동작이다.
    reg2 = registry.Registry()
    b2 = copy.deepcopy(reg2.get(pid))
    reg2.mark_updated(rec, "2099-01-01")
    a2 = reg2.get(pid)
    check("대조: mark_updated 는 revision 을 올린다(그게 그쪽 일이다)",
          a2.revision == b2.revision + 1 and a2.last_updated == "2099-01-01")

    # ⚠️ 어느 경로에서도 파일을 쓰지 않는다. reg.save() 를 부르지 않았다.
    check("검사가 registry.json 을 건드리지 않는다",
          registry.Registry().get(pid).content_hash == before.content_hash)

    print()
    if failures:
        print(f"✗ {len(failures)}건 실패")
        return 1
    print("✅ 전부 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
