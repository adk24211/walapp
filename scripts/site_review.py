"""사이트를 훑어 고칠 거리를 찾아 **우선순위를 매겨** 내놓는다. 고치지는 않는다.

왜 만들었나
───────────
매일 아침 사람(또는 에이전트)이 "뭘 고치지" 부터 시작하면 매번 같은 곳을 다시
파게 되고, 그날의 기분에 따라 대상이 달라진다. 이 스크립트는 **재는 일**만 맡는다.
무엇을 고칠지 정하고 실제로 고치는 것은 읽는 쪽의 일이다.

여기 담긴 측정은 전부 2026-09-03 작업에서 **실제로 결함을 찾아낸 것들**이다.
새로 지어낸 지표가 아니라, 한 번 물고기를 잡은 그물만 남겼다.

  · 얇은 페이지          애드센스 반려 사유("가치가 별로 없는 콘텐츠")의 본체
  · 광고 붙은 얇은 페이지 심사에서 가장 먼저 눈에 띌 조합
  · 재생성 밀린 건수      늘고 있으면 발행 속도와 맞바꿈이 깨진 것
  · 대상이 빈 제도        어느 대상 허브에도 안 뜨는 페이지
  · 중복 콘텐츠          405건 중 1쌍뿐이었지만, 늘면 알아야 한다
  · 커버리지 표시        화면에 적힌 숫자가 실제와 어긋나는지
  · 기존 검사 전부        check_*.py / check_*.mjs

무엇을 하지 않나
────────────────
· **아무것도 고치지 않는다.** 파일을 쓰는 곳은 이력 파일 하나뿐이다.
· LLM 을 부르지 않는다. 토큰이 들지 않으므로 매일 돌려도 된다.
· 좋고 나쁨을 판단하지 않는다 — 센 값과, 어제와 달라진 것만 말한다.

    python3 scripts/site_review.py                # 사람이 읽는 보고서
    python3 scripts/site_review.py --json         # 기계가 읽는 것
    python3 scripts/site_review.py --no-history   # 이력에 기록하지 않는다
"""
from __future__ import annotations

import argparse
import glob
import itertools
import json
import re
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import registry   # noqa: E402
import taxonomy   # noqa: E402
import reclassify_audiences as rc  # noqa: E402

HISTORY_FILE = ROOT / "_data" / "review_history.json"
# 이력은 추세를 보려고 남기는 것이지 영구 기록이 아니다. 너무 길어지면
# _data 가 불필요하게 커지고 diff 가 지저분해진다.
HISTORY_KEEP = 60

# 제도 상세에 광고가 붙는 조건(_layouts/default.html 의 show_ads 와 같아야 한다).
# ⚠️ 두 문턱은 AND 다. 한쪽만 보면 조회수 높은 얇은 페이지를 잘못 센다.
ADS_MIN_OWN_CHARS = 400
ADS_MIN_VIEWS = 10000


# ─────────────────────────────────────────────────────────────
#  재기
# ─────────────────────────────────────────────────────────────
def read_pages() -> list[dict]:
    """발행된 제도 페이지에서 앞부분(front matter)과 본문 길이를 읽는다."""
    out = []
    for path in glob.glob(str(ROOT / "_programs" / "**" / "*.md"), recursive=True):
        text = Path(path).read_text(encoding="utf-8")
        def field(name, cast=str, default=None):
            m = re.search(rf'^{name}:\s*"?(.*?)"?\s*$', text, re.M)
            if not m:
                return default
            try:
                return cast(m.group(1))
            except (TypeError, ValueError):
                return default
        body = text.split("---", 2)[2] if text.count("---") >= 2 else text
        plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()
        out.append({
            "path": path,
            "title": field("title") or "?",
            "own_chars": field("own_chars", int, 0),
            "views": field("view_count", int, 0),
            "body_chars": len(plain),
            "last_checked": field("last_checked") or "",
            "body": plain,
        })
    return out


def thin_pages(pages) -> dict:
    vals = sorted(p["own_chars"] for p in pages)
    n = max(len(vals), 1)
    return {
        "count": len(vals),
        "median_own_chars": round(statistics.median(vals)) if vals else 0,
        "under_400": sum(1 for v in vals if v < 400),
        "under_400_pct": sum(1 for v in vals if v < 400) * 100 // n,
        "under_500": sum(1 for v in vals if v < 500),
    }


def ads_on_thin(pages) -> list[dict]:
    """광고가 붙는데 본문이 아주 짧은 페이지.

    애드센스 심사자가 표본으로 볼 가능성이 가장 높은 조합이다 — 조회수가
    높아서 광고 문턱을 넘는데, 정작 실린 글은 얼마 없는 페이지.
    """
    out = []
    for p in pages:
        has_ads = not (p["own_chars"] < ADS_MIN_OWN_CHARS and p["views"] < ADS_MIN_VIEWS)
        if has_ads and p["body_chars"] < 700:
            out.append({"title": p["title"], "views": p["views"],
                        "body_chars": p["body_chars"], "own_chars": p["own_chars"]})
    out.sort(key=lambda x: -x["views"])
    return out


def regen_backlog() -> int:
    """표적 재생성 대상 건수. regenerate.py 와 같은 조건으로 직접 센다."""
    records = registry.load_all_records()
    raw_fields = ("target_raw", "benefit_raw", "criteria_raw", "how_to_raw")
    import render
    n = 0
    for r in records.values():
        if r.status == "closed":
            continue
        raw = sum(len(str(getattr(r, f, "") or "")) for f in raw_fields)
        if raw < 600:
            continue
        prose = registry.load_prose(r.id)
        if not prose:
            continue
        manifest: dict = {}
        render.render_body(r, prose, manifest=manifest)
        own = manifest.get("own_chars", 0)
        if str(prose.get("summary") or "").strip():
            own += len(str(render._polite(prose.get("summary")) or ""))
        if own < 500:
            n += 1
    return n


def audience_signals(records) -> dict:
    """대상 분류에서 손볼 거리 — 양쪽 방향 모두."""
    empty = [{"title": r.name, "views": r.view_count or 0}
             for r in records.values() if not r.audiences]
    empty.sort(key=lambda x: -x["views"])

    # ⚠️ 대상 **오분류** 탐지기는 여기 없다. 세 번 시도하고 세 번 버렸다.
    #
    #    2026-09-03 에 '사업주체' 안의 '사업주'(조회 669,273 페이지를 사업주
    #    허브로 보냈다), '주택사업자', '신청년도' 를 찾아냈다. 그래서 기계로도
    #    같은 것을 잡을 수 있겠거니 하고 만들어 봤는데, 전부 시끄러웠다.
    #
    #      ① "긴 낱말 안에 키워드가 있다"      → 25종. '보육료를'·'아동수당을'
    #                                            같은 멀쩡한 말이 대부분이었다.
    #      ② "홀로 선 자리가 하나도 없다"      → 한국어는 조사가 붙는 언어라
    #                                            '구직자에게' 도 홀로 선 적이 없다.
    #                                            조회수 1~2위 페이지가 걸렸다.
    #      ③ "근거가 한 자리뿐이다"            → 942개 태그 중 223개. 그중
    #                                            대부분이 맞는 태그였다
    #                                            (디딤돌 대출의 '다문화 가구 우대').
    #
    #    매일 아침 틀린 경고를 내는 항목은 없느니만 못하다 — 읽는 쪽이 이 보고서
    #    전체를 흘려 보게 된다. 세 사례는 전부 **문맥을 읽어야** 갈렸다.
    #    지금 그 자리를 지키는 것은 check_audience.py 의 회귀 케이스 38건이다.
    #    새 오분류를 찾는 것은 사람의 일로 남긴다.

    return {"empty": empty}


def near_duplicates(pages, threshold=0.5) -> list[dict]:
    """본문이 서로 너무 닮은 쌍. 애드센스가 중복 콘텐츠를 특히 본다."""
    def shingles(text, n=6):
        w = text.split()
        return {" ".join(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}

    sh = {p["title"]: shingles(p["body"]) for p in pages}
    inv = defaultdict(list)
    for title, s in sh.items():
        for g in itertools.islice(s, 0, 400):
            inv[g].append(title)
    cand = set()
    for fs in inv.values():
        if 1 < len(fs) <= 12:
            cand.update(itertools.combinations(sorted(fs), 2))
    hits = []
    for a, b in cand:
        A, B = sh[a], sh[b]
        if not A or not B:
            continue
        j = len(A & B) / len(A | B)
        if j >= threshold:
            hits.append({"a": a, "b": b, "jaccard": round(j, 2)})
    hits.sort(key=lambda x: -x["jaccard"])
    return hits


def stale_pages(pages, days=30) -> int:
    """마지막으로 원문과 대조한 지 오래된 페이지. 화면이 '최종 확인일' 을 약속한다."""
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    n = 0
    for p in pages:
        try:
            d = date.fromisoformat(p["last_checked"])
        except (ValueError, TypeError):
            continue
        if (today - d).days > days:
            n += 1
    return n


def run_checks() -> list[dict]:
    """기존 검사를 전부 돌린다. 브라우저가 필요한 둘은 빌드가 있을 때만."""
    checks = [
        ("대상 분류", [sys.executable, "scripts/check_audience.py"]),
        ("대상 덮어쓰기", [sys.executable, "scripts/check_overrides.py"]),
        ("사실 검증", [sys.executable, "scripts/check_verify.py"]),
        ("공개 주장", [sys.executable, "scripts/check_claims.py"]),
        ("신청기한 파서", [sys.executable, "scripts/check_period.py"]),
    ]
    built = (ROOT / "_site_check").exists() or (ROOT / "_site").exists()
    if built:
        checks += [
            ("인라인 스크립트", ["node", "scripts/check_inline_js.mjs"]),
            ("검색 메타데이터", ["node", "scripts/check_seo.mjs"]),
        ]
    out = []
    for label, cmd in checks:
        try:
            p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=600)
            tail = [l for l in p.stdout.strip().split("\n") if l.strip()]
            out.append({"name": label, "ok": p.returncode == 0,
                        "last_line": tail[-1][:120] if tail else ""})
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            out.append({"name": label, "ok": False, "last_line": f"돌리지 못했습니다: {e}"})
    if not built:
        out.append({"name": "빌드가 필요한 검사", "ok": True,
                    "last_line": "_site_check 가 없어 건너뜀 (레이아웃·대비·인라인·SEO)"})
    return out


def coverage_drift() -> dict | None:
    """화면이 읽는 커버리지 숫자가 실제 발행분과 어긋나는지."""
    path = ROOT / "_data" / "coverage.json"
    if not path.exists():
        return None
    try:
        cov = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"error": "coverage.json 을 읽지 못했습니다."}
    published = len(glob.glob(str(ROOT / "_programs" / "**" / "*.md"), recursive=True))
    in_scope = (cov.get("source_total") or 0) - (cov.get("out_of_scope") or 0)
    return {
        "synced_at": cov.get("synced_at"),
        "source_total": cov.get("source_total"),
        "in_scope": in_scope,
        "published": published,
        # 화면은 '남은 것' 을 (범위 안 − 발행 − 검토대기)로 뺀다. 음수가 되면
        # 화면에 음수가 찍힌다.
        "remaining": in_scope - published - (cov.get("review_needed") or 0)
                     - (cov.get("incomplete") or 0),
    }


# ─────────────────────────────────────────────────────────────
#  이력 — 어제와 달라진 것만 눈에 띄게
# ─────────────────────────────────────────────────────────────
def load_history() -> list[dict]:
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def save_history(entries: list[dict]) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(
        json.dumps(entries[-HISTORY_KEEP:], ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )


def delta(now, prev, key, path=()):
    """전날 대비 증감. 이력이 없으면 None."""
    if not prev:
        return None
    node = prev
    for p in path:
        node = (node or {}).get(p, {})
    before = (node or {}).get(key)
    return None if before is None else now - before


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="기계가 읽는 형식으로")
    ap.add_argument("--no-history", action="store_true", help="이력에 기록하지 않는다")
    args = ap.parse_args()

    pages = read_pages()
    records = registry.load_all_records()
    aud = audience_signals(records)

    report = {
        "date": datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat(),
        "thin": thin_pages(pages),
        "ads_on_thin": ads_on_thin(pages),
        "regen_backlog": regen_backlog(),
        "audiences_empty": aud["empty"],
        "near_duplicates": near_duplicates(pages),
        "stale_over_30d": stale_pages(pages),
        "coverage": coverage_drift(),
        "checks": run_checks(),
    }

    history = load_history()
    prev = history[-1] if history else None

    if args.json:
        report["delta"] = {
            "under_400": delta(report["thin"]["under_400"], prev, "under_400", ("thin",)),
            "regen_backlog": delta(report["regen_backlog"], prev, "regen_backlog"),
            "count": delta(report["thin"]["count"], prev, "count", ("thin",)),
        }
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        _print_human(report, prev)

    if not args.no_history:
        # 이력에는 숫자만 남긴다. 목록까지 넣으면 파일이 금방 커지고, 추세를
        # 보는 데는 숫자면 충분하다.
        history.append({
            "date": report["date"],
            "thin": report["thin"],
            "regen_backlog": report["regen_backlog"],
            "ads_on_thin": len(report["ads_on_thin"]),
            "audiences_empty": len(report["audiences_empty"]),
            "near_duplicates": len(report["near_duplicates"]),
            "stale_over_30d": report["stale_over_30d"],
            "checks_failed": [c["name"] for c in report["checks"] if not c["ok"]],
        })
        save_history(history)

    return 1 if any(not c["ok"] for c in report["checks"]) else 0


def _print_human(r, prev) -> None:
    def arrow(now, key, path=()):
        d = delta(now, prev, key, path)
        if d is None:
            return ""
        if d == 0:
            return "  (어제와 같음)"
        return f"  ({d:+d} 어제 대비)"

    print(f"━━━ 사이트 점검 {r['date']} ━━━\n")

    t = r["thin"]
    print("■ 얇은 페이지")
    print(f"    제도 {t['count']}건{arrow(t['count'], 'count', ('thin',))}"
          f" · own_chars 중앙값 {t['median_own_chars']}")
    print(f"    400자 미만 {t['under_400']}건 ({t['under_400_pct']}%)"
          f"{arrow(t['under_400'], 'under_400', ('thin',))}")
    print(f"    표적 재생성 밀린 것 {r['regen_backlog']}건"
          f"{arrow(r['regen_backlog'], 'regen_backlog')}")

    print(f"\n■ 광고가 붙는데 본문이 700자 미만 — {len(r['ads_on_thin'])}건")
    for x in r["ads_on_thin"][:8]:
        print(f"    조회 {x['views']:>9,} · 본문 {x['body_chars']:>4}자 · 자체 {x['own_chars']:>3}자  {x['title'][:40]}")
    if len(r["ads_on_thin"]) > 8:
        print(f"    … 외 {len(r['ads_on_thin']) - 8}건")

    print(f"\n■ 대상이 하나도 없는 제도 — {len(r['audiences_empty'])}건")
    for x in r["audiences_empty"][:6]:
        print(f"    조회 {x['views']:>9,}  {x['title'][:44]}")

    print(f"\n■ 중복 콘텐츠 — 자카드 0.5 이상 {len(r['near_duplicates'])}쌍")
    for x in r["near_duplicates"][:5]:
        print(f"    {x['jaccard']}  {x['a'][:32]} ↔ {x['b'][:32]}")

    print(f"\n■ 30일 넘게 원문과 대조 안 한 페이지 — {r['stale_over_30d']}건")

    cov = r["coverage"]
    if cov and "error" not in cov:
        print(f"\n■ 커버리지 ({cov['synced_at']} 기준)")
        print(f"    원천 {cov['source_total']:,} · 범위 안 {cov['in_scope']:,}"
              f" · 발행 {cov['published']:,} · 남은 것 {cov['remaining']:,}")
        if cov["remaining"] < 0:
            print("    ⚠ '남은 것' 이 음수입니다 — 화면에 음수가 찍힙니다. coverage.json 을 확인할 것.")

    print("\n■ 검사")
    for c in r["checks"]:
        print(f"    {'✓' if c['ok'] else '✗'} {c['name']:<16} {c['last_line']}")

    failed = [c["name"] for c in r["checks"] if not c["ok"]]
    print()
    if failed:
        print(f"→ 먼저 볼 것: 실패한 검사 {', '.join(failed)}")
    elif r["ads_on_thin"]:
        print("→ 먼저 볼 것: 광고가 붙는데 본문이 얇은 페이지 (심사에서 가장 먼저 눈에 띈다)")
    else:
        print("→ 급한 것 없음.")


if __name__ == "__main__":
    sys.exit(main())
