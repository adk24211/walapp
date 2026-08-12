"""⑤ 구 브리핑 마이그레이션 — 삭제하지 않고 `/brief/` 로 격리한다.

삭제하지 않는 이유 (REDESIGN.md §7.2):
  · 이미 색인된 URL을 대량 삭제하면 404가 급증해 사이트 전체 평가가 흔들린다
  · AdSense 승인 상태에서 콘텐츠가 급감하면 재심사 리스크가 있다

이 스크립트가 하는 일:
  1. 완전 중복 제목 그룹에서 가장 내용이 충실한 1건만 남기고,
     나머지에 `canonical_url` 을 달아 남긴 글로 정규화한다.
     (삭제 대신 정규화 — 유입이 있는 글을 잃지 않으면서 중복 신호는 제거한다.
      jekyll-seo-tag 가 canonical_url 을 <link rel="canonical"> 로 출력한다.)
  2. 모든 구 포스트에 `archived: true` 를 달아 레이아웃이 안내 배너를 띄우게 한다.

멱등하다. 여러 번 돌려도 결과가 같다.

    python3 scripts/migrate_brief.py [--dry-run]
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
POSTS_DIR = ROOT / "_posts"
CONFIG_FILE = ROOT / "_config.yml"

FRONT_MATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
TITLE_RE = re.compile(r'^title:\s*"?(.*?)"?\s*$', re.MULTILINE)
# 포스트 permalink 은 _config.yml 의 `/brief/:categories/:year/:month/:day/:title/` 를 따른다.
PERMALINK_TEMPLATE = "/brief/{category}/{year}/{month}/{day}/{slug}/"

FILENAME_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-(.+)\.md$")


def site_base() -> str:
    """`url` + `baseurl` — canonical 은 반드시 절대 URL 이어야 한다.

    jekyll-seo-tag 는 front matter 의 `canonical_url` 을 가공 없이 그대로 출력한다.
    상대 경로를 넣으면 baseurl(`/walapp`)이 빠져 존재하지 않는 주소를 가리키게 된다.
    """
    text = CONFIG_FILE.read_text(encoding="utf-8")
    url = re.search(r'^url:\s*"?([^"\n]*)"?', text, re.MULTILINE)
    baseurl = re.search(r'^baseurl:\s*"?([^"\n]*)"?', text, re.MULTILINE)
    return (url.group(1).strip() if url else "").rstrip("/") + \
           (baseurl.group(1).strip() if baseurl else "").rstrip("/")


def parse(path: Path) -> tuple[str, str, str] | None:
    """(front matter, body, title)"""
    text = path.read_text(encoding="utf-8")
    match = FRONT_MATTER_RE.match(text)
    if not match:
        return None
    front = match.group(1)
    body = text[match.end():]
    title_match = TITLE_RE.search(front)
    return front, body, (title_match.group(1).strip() if title_match else "")


def category_of(front: str) -> str:
    match = re.search(r"^categories:\s*\[(.*?)\]", front, re.MULTILINE)
    return match.group(1).strip() if match else "brief"


def url_of(path: Path, front: str) -> str:
    """Jekyll 이 만들 URL을 재현한다 (canonical 대상 지정용)."""
    name_match = FILENAME_RE.match(path.name)
    if not name_match:
        return ""
    year, month, day, slug = name_match.groups()
    return PERMALINK_TEMPLATE.format(
        category=category_of(front), year=year, month=month, day=day, slug=slug
    )


def set_field(front: str, key: str, value: str) -> str:
    """front matter 에 키를 넣거나 갱신한다."""
    line = f"{key}: {value}"
    pattern = re.compile(rf"^{re.escape(key)}:.*$", re.MULTILINE)
    if pattern.search(front):
        return pattern.sub(line, front)
    return front.rstrip("\n") + "\n" + line


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    posts = sorted(POSTS_DIR.glob("*.md"))
    if not posts:
        print("_posts 가 비어 있습니다.")
        return 0

    parsed: dict[Path, tuple[str, str, str]] = {}
    for path in posts:
        result = parse(path)
        if result:
            parsed[path] = result

    # ── 제목 기준 그룹핑 ──
    groups: dict[str, list[Path]] = defaultdict(list)
    for path, (_front, _body, title) in parsed.items():
        if title:
            groups[title].append(path)

    duplicates = {title: paths for title, paths in groups.items() if len(paths) > 1}
    canonical_count = 0
    archived_count = 0

    # ── 중복 그룹: 본문이 가장 긴 것을 정본으로 ──
    base = site_base()
    canonical_map: dict[Path, str] = {}
    for title, paths in duplicates.items():
        primary = max(paths, key=lambda p: len(parsed[p][1]))
        primary_path = url_of(primary, parsed[primary][0])
        if not primary_path:
            continue
        primary_url = base + primary_path
        for path in paths:
            if path != primary:
                canonical_map[path] = primary_url

    # ── 쓰기 ──
    for path, (front, body, _title) in parsed.items():
        updated = set_field(front, "archived", "true")
        archived_count += 1
        if path in canonical_map:
            updated = set_field(updated, "canonical_url", f'"{canonical_map[path]}"')
            canonical_count += 1
        if updated == front:
            continue
        if not dry_run:
            path.write_text(f"---\n{updated}\n---\n{body}", encoding="utf-8")

    print(f"포스트 {len(parsed)}건")
    print(f"  중복 제목 그룹 {len(duplicates)}개 → canonical 지정 {canonical_count}건")
    print(f"  archived 표시 {archived_count}건")
    if dry_run:
        print("  (dry-run — 파일을 쓰지 않았습니다)")
    if duplicates:
        print("\n중복 상위:")
        for title, paths in sorted(duplicates.items(), key=lambda kv: -len(kv[1]))[:8]:
            print(f"  {len(paths)}× {title}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
