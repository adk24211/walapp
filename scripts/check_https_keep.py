"""확인해 둔 https 주소가 http 로 되돌아가지 않는지 고정한다.

sync._keep_verified_https 는 한동안 **무력했다.** 원장 항목(Entry)을 넘기고
있었는데 Entry 에는 apply_url 이 없어서 getattr 이 늘 빈 문자열을 돌려줬다.
조건이 한 번도 참이 된 적이 없으니 로그에도 아무것도 안 남았다.

무력한 안전장치는 없는 것보다 나쁘다 — 있다고 믿게 되기 때문이다. 그래서
기계가 본다. 이 함수는 세 가지를 동시에 지켜야 한다:

  ① 스킴만 다르면 저장해 둔 https 를 되살린다 (오늘 확인을 못 한 것뿐이다)
  ② 원천이 주소 자체를 바꿨으면 건드리지 않는다 (그건 진짜 변경이다)
  ③ 저장된 레코드가 없어도 터지지 않는다 (신규 제도)

    python3 scripts/check_https_keep.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import registry  # noqa: E402
import sync      # noqa: E402

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'}  {label}{'  — ' + detail if detail else ''}")
    if not ok:
        failures.append(label)


def main() -> int:
    records = registry.load_all_records()
    found = next(((p, r) for p, r in sorted(records.items())
                  if str(getattr(r, "apply_url", "")).startswith("https://")), None)
    if found is None:
        check("https 로 저장된 레코드가 하나는 있어야 검사할 수 있다", False)
        return 1
    pid, stored = found
    https_url = stored.apply_url
    http_url = "http://" + https_url[len("https://"):]

    # ① 스킴만 다르면 되살린다
    fresh = copy.deepcopy(stored)
    fresh.apply_url = http_url
    sync._keep_verified_https(fresh, registry.load_record(pid))
    check("스킴만 다르면 저장해 둔 https 를 되살린다",
          fresh.apply_url == https_url,
          f"{http_url} → {fresh.apply_url}")

    # 되살렸으면 해시도 다시 계산돼야 한다 — 안 그러면 '변경됨' 으로 잡힌다
    check("되살린 뒤 content_hash 도 다시 계산한다",
          fresh.content_hash == __import__("schema").compute_hash(fresh))

    # ② 원천이 주소를 바꿨으면 건드리지 않는다
    moved = copy.deepcopy(stored)
    moved.apply_url = "http://some-other-host.kr/apply"
    sync._keep_verified_https(moved, registry.load_record(pid))
    check("원천이 주소 자체를 바꾸면 건드리지 않는다",
          moved.apply_url == "http://some-other-host.kr/apply",
          moved.apply_url)

    # ③ 저장된 레코드가 없어도 터지지 않는다
    try:
        blank = copy.deepcopy(stored)
        blank.apply_url = http_url
        sync._keep_verified_https(blank, None)
        check("저장된 레코드가 없어도 터지지 않는다", True)
    except Exception as exc:  # noqa: BLE001
        check("저장된 레코드가 없어도 터지지 않는다", False, repr(exc))

    # ④ 원장 항목을 넘기면 아무 일도 못 한다 — 그 실수를 다시 하지 않도록 못박는다
    entry_arg = copy.deepcopy(stored)
    entry_arg.apply_url = http_url
    sync._keep_verified_https(entry_arg, registry.Registry().get(pid))
    check("원장 항목(Entry)으로는 되살릴 수 없다 — 반드시 레코드를 넘길 것",
          entry_arg.apply_url == http_url,
          "Entry 에는 주소 필드가 없다")

    print()
    if failures:
        print(f"✗ {len(failures)}건 실패")
        return 1
    print("✅ 전부 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
