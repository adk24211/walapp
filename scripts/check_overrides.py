"""손으로 적은 대상 덮어쓰기가 아직 필요한지, 그리고 근거가 살아 있는지 본다.

덮어쓰기(_data/audience_overrides.json)는 마지막 수단이다. 늘어나면 규칙의 결함이
그 뒤에 숨고, 다음 사람은 어떤 태그가 규칙에서 왔고 어떤 것이 손에서 왔는지
알 수 없게 된다. 그래서 셋을 강제한다.

  ① 근거가 살아 있는가 — `quote` 는 그 제도 원문에서 **그대로 옮긴** 문장이어야
     한다. 원문이 바뀌어 그 문장이 사라지면 여기서 실패한다. 덮어쓰기가
     스스로 만료되는 장치다. "예전엔 맞았던 덮어쓰기" 가 남는 것을 막는다.

  ② 아직 필요한가 — 규칙이 이미 같은 답을 내면 실패한다. 규칙을 고쳐서
     해결된 뒤에도 덮어쓰기가 남으면, 그 태그의 출처를 알 수 없다.

  ③ 형식이 맞는가 — 없는 제도 id, 없는 대상 이름, 빠진 reason·quote.

    python3 scripts/check_overrides.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import audience_overrides  # noqa: E402
import registry            # noqa: E402
import taxonomy            # noqa: E402
import reclassify_audiences as rc  # noqa: E402

# 근거를 찾을 원문 필드. 제도명은 넣지 않는다 — 제목만으로 되는 것은
# 애초에 규칙이 잡으므로 덮어쓸 이유가 없다.
QUOTE_FIELDS = ("target_raw", "criteria_raw", "benefit_raw", "how_to_raw")


def main() -> int:
    if not audience_overrides.OVERRIDES_FILE.exists():
        print("덮어쓰기 파일이 없습니다 — 볼 것이 없습니다.")
        return 0

    # load() 는 깨진 파일을 조용히 빈 dict 로 넘긴다(동기화를 세우지 않으려고).
    # 여기서는 반대로, 깨졌으면 알려야 한다.
    try:
        table = json.loads(audience_overrides.OVERRIDES_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"✗ {audience_overrides.OVERRIDES_FILE.name} 를 읽지 못했습니다: {e}")
        return 1
    if not isinstance(table, dict):
        print("✗ 최상위가 객체가 아닙니다. {program_id: {...}} 모양이어야 합니다.")
        return 1

    records = registry.load_all_records()
    failures: list[str] = []
    print(f"덮어쓰기 {len(table)}건")

    for pid, rule in table.items():
        label = f"{rule.get('name') or pid}"
        rec = records.get(pid)
        if rec is None:
            failures.append(f"{label}: '{pid}' 인 제도가 _records/ 에 없습니다.")
            continue

        # ③ 형식
        for field in ("reason", "quote"):
            if not str(rule.get(field) or "").strip():
                failures.append(f"{label}: {field} 가 비어 있습니다.")
        bad = [a for a in (rule.get("add") or []) + (rule.get("remove") or [])
               if a not in taxonomy.AUDIENCE_KEYS]
        if bad:
            failures.append(f"{label}: 없는 대상 이름 {bad}")
        if not (rule.get("add") or rule.get("remove")):
            failures.append(f"{label}: add 도 remove 도 비어 있습니다 — 아무 일도 하지 않습니다.")

        # ① 근거가 살아 있는가
        quote = str(rule.get("quote") or "").strip()
        if quote:
            haystack = " ".join(str(getattr(rec, f, "") or "") for f in QUOTE_FIELDS)
            if quote not in haystack:
                failures.append(
                    f"{label}: 근거로 적은 문장이 지금 원문에 없습니다 — 원문이 바뀌었는지 "
                    f"확인하고, 덮어쓰기가 아직 맞는지 다시 판단할 것.\n"
                    f"        적어 둔 근거: \"{quote[:60]}\""
                )

        # ② 아직 필요한가
        rule_only = taxonomy.classify_audiences(rc.blob_of(rec))
        with_override = audience_overrides.apply(pid, list(rule_only), table)
        if sorted(rule_only) == sorted(with_override):
            failures.append(
                f"{label}: 규칙이 이미 같은 답({sorted(rule_only)})을 냅니다 — "
                f"덮어쓰기를 지우십시오."
            )
        else:
            print(f"  ✓ {label}: 규칙 {sorted(rule_only)} → 덮어쓴 뒤 {sorted(with_override)}")

    if failures:
        print()
        for f in failures:
            print(f"  ✗ {f}")
        print(f"\n덮어쓰기에 문제가 있습니다 — {len(failures)}건.")
        return 1
    print("\n✅ 덮어쓰기가 전부 근거와 맞고, 아직 필요합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
