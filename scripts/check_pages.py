"""페이지 파일과 원장이 같은 말을 하는지 본다. 빌드 결과가 있으면 화면까지 본다.

왜 만들었나
───────────
2026-09-27 에 페이지 582건을 세어 보니 서로 다른 제도 id 는 578개였다. 네 쌍이
같은 제도를 두 주소로 내보내고 있었고, 거기에 더해 **원장이 발행이라고 적어 둔
제도 하나는 화면에 아예 없었다.** 셋 다 눈으로는 찾을 수 없는 종류였다.

  ① 경로가 옮겨졌는데 예전 페이지가 남음 — 보훈요양원 세 곳이 분류가
     education 에서 health/care 로 바뀌었고, 어떤 제도는 이름이 짧아져
     슬러그가 달라졌다. 새 경로에 새 파일이 생기고 예전 파일은 그대로 남았다.
     (scripts/publish.py 의 _drop_moved_page 가 이제 치운다)

  ② slug 가 겹쳐 한 제도가 다른 제도의 페이지를 덮어씀 — 자산형성지원사업
     희망저축Ⅰ·Ⅱ 가 로마숫자가 버려지며 같은 파일을 가리켰다. 나중 것이
     앞의 것을 덮어써서 Ⅰ은 해설까지 만들어 두고도 아무도 볼 수 없었다.
     (scripts/schema.py 의 _NUMERAL_MAP 이 이제 숫자로 옮긴다)

  ③ 화면의 확인일이 원장보다 낡음 — 동기화는 내용이 안 바뀐 제도에도 '오늘
     대조했다' 를 기록하지만 그건 원장만 갱신한다. 페이지는 내용이 바뀔 때만
     다시 찍히므로 582건 중 566건이 실제보다 낡은 날짜를 보여 주고 있었다
     (최대 45일). 이제 템플릿이 원장에서 읽는다 — 그게 정말 그런지 여기서 본다.

세 가지 모두 '한 번 어긋나면 아무도 모르게 오래 남는' 부류다. 그래서 세는 일을
사람 눈에서 떼어 냈다.

무엇을 보나
───────────
  · 페이지마다 program_id 가 있는가
  · 같은 program_id 를 가진 페이지가 둘 이상인가            ①
  · 페이지가 원장이 가리키는 경로에 있는가                   ①
  · 원장에 있는 제도의 페이지가 실제로 있는가                ②
  · 원장 안에서 두 제도가 같은 경로를 가리키지 않는가        ②
  · (빌드가 있으면) 화면의 확인일 == 원장의 last_checked     ③

무엇을 보지 않나
────────────────
본문의 내용·품질을 보지 않는다. 그건 site_review.py 와 check_verify.py 의 일이다.
여기서 보는 것은 "무엇이 몇 개 있고 어디에 있는가" 뿐이다.

    python3 scripts/check_pages.py
    python3 scripts/check_pages.py --site _site_check   # 화면까지 본다
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import registry  # noqa: E402

# 화면에 찍힌 확인일. _layouts/program.html 의 <dt>확인일</dt> 블록과 짝이다.
CHECKED_RE = re.compile(r"<dt>확인일</dt>\s*<dd>([0-9-]+)</dd>")

failures: list[str] = []


def page_index() -> dict[str, list[Path]]:
    """{program_id: [페이지 경로…]}. id 가 없는 페이지는 '' 키로 모인다."""
    index: dict[str, list[Path]] = defaultdict(list)
    for path in sorted(registry.PROGRAMS_DIR.rglob("*.md")):
        index[registry.page_owner(path) or ""].append(path)
    return index


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def check_files(reg: registry.Registry, index: dict[str, list[Path]]) -> None:
    pages = sum(len(v) for v in index.values())
    print(f"페이지 {pages}건 · 서로 다른 제도 id {len([k for k in index if k])}개 "
          f"· 원장 {len(reg.entries)}건")

    for path in index.get("", []):
        failures.append(f"{rel(path)}: 앞부분에 program_id 가 없습니다.")

    # ① 같은 제도가 두 주소에
    for pid, paths in index.items():
        if not pid or len(paths) < 2:
            continue
        entry = reg.get(pid)
        canon = entry.path if entry else "(원장에 없음)"
        lines = "\n".join(
            f"        {'정본' if canon == rel(p) else '고아'}  {rel(p)}" for p in paths
        )
        failures.append(
            f"{pid}: 같은 제도가 페이지 {len(paths)}개로 나가고 있습니다 — 중복 콘텐츠입니다.\n"
            f"        원장이 가리키는 곳: {canon}\n{lines}"
        )

    # ① 경로가 원장과 다른 곳에 있는 페이지
    for pid, paths in index.items():
        entry = reg.get(pid) if pid else None
        if entry is None or len(paths) != 1:
            continue
        if rel(paths[0]) != entry.path:
            failures.append(
                f"{pid}: 페이지가 원장이 가리키는 곳에 없습니다.\n"
                f"        원장: {entry.path}\n        실제: {rel(paths[0])}"
            )

    # ② 원장에는 있는데 페이지가 없는 제도
    for pid, entry in reg.entries.items():
        if pid in index:
            continue
        failures.append(
            f"{pid} ({entry.name}): 원장에는 발행으로 적혀 있는데 페이지가 없습니다 — "
            f"아무도 볼 수 없고, 원장이 발행이라 하므로 동기화가 다시 만들지도 않습니다.\n"
            f"        원장: {entry.path}"
        )

    # ② 두 제도가 같은 경로를 가리키는 경우 (slug 충돌)
    by_path: dict[str, list[str]] = defaultdict(list)
    for pid, entry in reg.entries.items():
        by_path[entry.path].append(pid)
    for path, pids in by_path.items():
        if len(pids) < 2:
            continue
        names = ", ".join(f"{p}({reg.get(p).name})" for p in sorted(pids))
        failures.append(
            f"{path}: 제도 {len(pids)}개가 같은 경로를 가리킵니다 — 하나가 나머지를 "
            f"덮어씁니다. slug 규칙을 볼 것(schema.make_slug).\n        {names}"
        )


def check_rendered(reg: registry.Registry, site: Path) -> None:
    """화면에 찍힌 확인일이 원장과 같은가.

    템플릿이 어떻게 쓰여 있는지 보지 않고 **찍혀 나온 결과**를 본다. 앞부분에서
    읽든 원장에서 읽든, 화면에 원장과 다른 날짜가 나오면 여기서 걸린다.
    """
    seen = missing = 0
    wrong: list[str] = []
    for pid, entry in reg.entries.items():
        url = entry.path.removeprefix("_programs/").removesuffix(".md")
        index = site / "support" / f"{url}" / "index.html"
        if not index.exists():
            missing += 1
            continue
        m = CHECKED_RE.search(index.read_text(encoding="utf-8"))
        if not m:
            continue
        seen += 1
        if m.group(1) != entry.last_checked:
            wrong.append(f"        {entry.name[:34]}  화면 {m.group(1)} / 원장 {entry.last_checked}")

    print(f"화면의 확인일을 읽은 페이지 {seen}건 · 어긋남 {len(wrong)}건"
          + (f" · 빌드에 없는 페이지 {missing}건" if missing else ""))
    if wrong:
        head = "\n".join(wrong[:10])
        more = f"\n        … 외 {len(wrong) - 10}건" if len(wrong) > 10 else ""
        failures.append(
            "화면의 확인일이 원장과 다릅니다 — 화면은 '이 날 원문과 대조했다' 고 "
            f"약속하고 있습니다({len(wrong)}건).\n{head}{more}"
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", nargs="?", const="_site_check", default=None,
                    help="빌드 결과 경로. 주면 화면의 확인일까지 본다 (기본 _site_check)")
    args = ap.parse_args()

    reg = registry.Registry()
    check_files(reg, page_index())

    if args.site:
        site = ROOT / args.site
        if not site.exists():
            failures.append(f"빌드 결과가 없습니다: {args.site} — 먼저 jekyll build 를 실행하세요.")
        else:
            check_rendered(reg, site)

    if failures:
        print()
        for f in failures:
            print(f"  ✗ {f}")
        print(f"\n페이지와 원장이 어긋납니다 — {len(failures)}건.")
        return 1
    print("\n✅ 페이지와 원장이 맞습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
