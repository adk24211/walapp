"""고를 수 있는 표적 재생성 — 원문은 넉넉한데 우리 문장이 얇은 제도만 다시 쓴다.

동기화는 **원문이 바뀐** 제도만 다시 쓴다. 그래서 프롬프트를 고쳐도 기존
페이지는 그대로 남는다. 이 스크립트는 그 간극을 메운다.

무엇을 고르나 (기본값):
    원문(지원대상+지원내용+선정기준+신청방법) 600자 이상  · own_chars 500자 미만
    = 원문에 쓸 것이 있는데 우리가 안 쓴 페이지. 조회수 높은 순으로 채운다.

    원문 자체가 얇은 제도는 대상이 아니다. 거기서 더 쓰는 것은 지어내는 것이다.
    (장기전세 주택공급은 원문 149자에 우리가 이미 236자를 썼다)

왜 필요했나: 출력 형식의 항목 수가 원문 길이와 무관하게 고정이라 1,300자짜리
원문과 150자짜리가 같은 봉투를 받았다. 상한을 원문에 맞춰 나눈 뒤
(generate_program.build_prompt), 이미 발행된 것에도 그 변경을 적용하려면
표적 재생성이 필요하다.

⚠️ LLM 을 쓴다. 하루 토큰 한도(TPD)가 있으므로 --limit 을 반드시 확인할 것.
   한도가 소진되면 그 자리에서 멈추고, 그때까지 다시 쓴 것은 그대로 남는다.

⚠️ publish._write_one 을 그대로 쓰므로 **상세 보강(adapter.enrich)이 함께 돈다.**
   즉 이 스크립트는 GROQ_API_KEY 말고 DATA_GO_KR_API_KEY 도 필요하고,
   원천의 상세 조회 쿼터를 대상 건수만큼 쓴다. 대신 다시 쓸 때 원문도 최신이
   되므로, 그 사이 원천이 바뀌었으면 그 변경까지 반영된다.

   같은 이유로 last_updated 가 오늘로 바뀌고 revision 이 1 오른다. 제도 정보가
   바뀐 게 아니라 우리 문장이 바뀐 것이지만, 페이지 내용이 실제로 달라지므로
   dateModified 가 오늘이 되는 것은 맞다.

    python3 scripts/regenerate.py --dry-run        # 대상만 본다 (LLM 호출 없음)
    python3 scripts/regenerate.py --limit 40       # 실제로 다시 쓴다
    python3 scripts/regenerate.py --name 구직급여  # 이름으로 지정 (여러 번 가능)
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import generate_program  # noqa: E402
import publish           # noqa: E402
import registry          # noqa: E402
import run_all           # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("regenerate")

RAW_FIELDS = ("target_raw", "benefit_raw", "criteria_raw", "how_to_raw")


def raw_len(record) -> int:
    return sum(len(str(getattr(record, f, "") or "")) for f in RAW_FIELDS)


def own_len(record) -> int:
    """저장된 해설의 글자 수. render.py 의 own_chars 와 같은 셈법이다."""
    prose = registry.load_prose(record.id) or {}
    total = len(str(prose.get("summary") or ""))
    total += sum(len(str(x or "")) for x in (prose.get("eligibility") or []))
    for step in (prose.get("steps") or []):
        total += len(str(step.get("title") or "")) + len(str(step.get("body") or ""))
    for item in (prose.get("faq") or []):
        total += len(str(item.get("q") or "")) + len(str(item.get("a") or ""))
    total += len(str(prose.get("note") or ""))
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-raw", type=int, default=600, help="이 글자 수 이상인 원문만 대상 (기본 600)")
    ap.add_argument("--max-own", type=int, default=500, help="이 글자 수 미만인 해설만 대상 (기본 500)")
    ap.add_argument("--limit", type=int, default=40, help="최대 몇 건까지 다시 쓸지 (기본 40)")
    ap.add_argument("--name", action="append", default=[], help="제도명으로 직접 지정. 조건을 무시한다")
    ap.add_argument("--dry-run", action="store_true", help="대상만 보고 끝낸다. LLM 을 부르지 않는다")
    args = ap.parse_args()

    records = registry.load_all_records()
    if not records:
        log.error("_records/ 가 비어 있습니다.")
        return 1

    if args.name:
        wanted = set(args.name)
        targets = [r for r in records.values() if r.name in wanted]
        missing = wanted - {r.name for r in targets}
        for m in missing:
            log.warning("그런 제도가 없습니다: %s", m)
    else:
        targets = [r for r in records.values()
                   if r.status != "closed"
                   and raw_len(r) >= args.min_raw
                   and own_len(r) < args.max_own]
        # 조회수 높은 것부터. 한도에 걸려 잘리더라도 많이 보는 쪽이 먼저 나아진다.
        targets.sort(key=lambda r: -(r.view_count or 0))

    if not targets:
        log.info("대상이 없습니다 (원문 %d자 이상 · 해설 %d자 미만).", args.min_raw, args.max_own)
        return 0

    over = len(targets) - args.limit
    targets = targets[:args.limit]

    log.info("대상 %d건%s", len(targets), f" (조건에 맞는 것 {len(targets) + over}건 중 상위)" if over > 0 else "")
    for r in targets:
        log.info("  자체 %4d자 · 원문 %5d자 · 조회 %9s  %s",
                 own_len(r), raw_len(r), f"{r.view_count or 0:,}", r.name)
    if over > 0:
        log.info("  … --limit 때문에 %d건은 이번에 제외됐습니다.", over)

    if args.dry_run:
        log.info("dry-run — LLM 을 부르지 않았고 파일도 쓰지 않았습니다.")
        return 0

    # 동기화와 같은 클라이언트를 쓴다. 키가 없으면 None 이 오고 오프라인
    # 폴백(원문 재배치)으로 떨어지는데, 그건 다시 쓰는 의미가 없다 — 막는다.
    client = run_all._groq_client()
    if client is None:
        log.error("GROQ_API_KEY 가 없습니다. 표적 재생성은 실제 모델이 있어야 의미가 있습니다.")
        log.error("(오프라인 폴백은 원문을 재배치할 뿐이라 지금 문장보다 나아지지 않습니다)")
        return 1

    reg = registry.Registry()
    result = publish.WriteResult()
    today = date.today()

    # 갱신 경로로 넘긴다(is_update=True). 원장 기록·검증·렌더가 동기화와 같아야
    # 다음 실행이 이 제도들을 '변경' 으로 다시 잡지 않는다.
    try:
        for record in targets:
            before = own_len(record)
            publish._write_one(record, reg, today, client, True, False, result)
            after = own_len(record)
            if after != before:
                log.info("  └ 자체 문장 %d자 → %d자 (%+d)", before, after, after - before)
    except generate_program.DailyQuotaExhausted as e:
        log.warning("일일 한도 소진 — 여기서 멈춥니다: %s", e)
        log.warning("다시 쓴 %d건은 그대로 남습니다. 내일 이어서 돌리면 됩니다.", len(result.updated))

    reg.save()
    log.info("완료 — 다시 씀 %d건 · 반려 %d건", len(result.updated), len(result.rejected))
    for item in result.rejected:
        log.warning("  반려 [%s] %s", item.get("name"), item.get("reason"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
