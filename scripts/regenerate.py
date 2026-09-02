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

⚠️ 저장된 원문으로 다시 쓴다. publish._write_one 안에 상세 보강(adapter.enrich)
   호출이 있지만, 이 스크립트는 collect.adapters 를 등록하지 않으므로
   adapters.get(source) 가 None 이 되어 그 블록은 항상 건너뛰어진다.
   (한때 독스트링과 워크플로 주석이 '보강이 함께 돈다' 고 적혀 있었다 —
    실행해 보면 adapters._ACTIVE 가 {} 다. 사실이 아니었다)

   그래서 수집 키가 필요 없고 원천의 상세 조회 쿼터도 쓰지 않는다. 대신
   원문은 마지막 동기화 시점 값이다. 최신 원문이 필요하면 동기화를 먼저 돌릴 것.

   last_updated 가 오늘로 바뀌고 revision 이 1 오른다. 제도 정보가 바뀐 게
   아니라 우리 문장이 바뀐 것이지만, 페이지 내용이 실제로 달라지므로
   dateModified 가 오늘이 되는 것은 맞다.

    python3 scripts/regenerate.py --dry-run        # 대상만 본다 (LLM 호출 없음)
    python3 scripts/regenerate.py --limit 40       # 실제로 다시 쓴다
    python3 scripts/regenerate.py --name 구직급여  # 이름으로 지정 (여러 번 가능)
"""
from __future__ import annotations

import argparse
import logging
import sys
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import generate_program  # noqa: E402
import publish           # noqa: E402
import registry          # noqa: E402
import render            # noqa: E402
import run_all           # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("regenerate")

RAW_FIELDS = ("target_raw", "benefit_raw", "criteria_raw", "how_to_raw")


def raw_len(record) -> int:
    return sum(len(str(getattr(record, f, "") or "")) for f in RAW_FIELDS)


def own_len(record) -> int:
    """화면에 실제로 실린 우리 문장의 글자 수.

    ⚠️ 저장된 prose 를 그대로 세지 말 것. 한 번 그렇게 썼다가 되돌렸다 —
       render_body 의 _useful_faq 가 되묻는 질문을 걸러내고 _useful_note 가
       상용구 주의를 버리므로, 생성된 것과 실린 것이 다르다. 385건 중 131건이
       그 상태였고(중앙값 +80자·최대 +217자), 그래서 '얇은 것' 을 고르는 이
       필터가 실제로 얇은 페이지를 걸러 냈다. 대상 55건 중 15건을 놓쳤다.

       render.to_markdown 과 같은 경로로 센다.
    """
    prose = registry.load_prose(record.id)
    if not prose:
        return 0
    manifest: dict = {}
    render.render_body(record, prose, manifest=manifest)
    total = manifest.get("own_chars", 0)
    if str(prose.get("summary") or "").strip():
        total += len(str(render._polite(prose.get("summary")) or ""))
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
    # .env 를 먼저 읽는다. 이걸 빼먹으면 .env 에 키를 둔 로컬 실행이
    # "키가 없습니다" 로 죽는다 — dry-run 은 client 확보 전에 끝나므로
    # dry-run 만 되고 본 실행만 안 되는 모양으로 나타난다.
    run_all._load_dotenv()
    client = run_all._groq_client()
    if client is None:
        log.error("GROQ_API_KEY 가 없습니다. 표적 재생성은 실제 모델이 있어야 의미가 있습니다.")
        log.error("(오프라인 폴백은 원문을 재배치할 뿐이라 지금 문장보다 나아지지 않습니다)")
        return 1

    reg = registry.Registry()
    result = publish.WriteResult()
    # run_all 과 같은 방식으로 날짜를 정한다. date.today() 를 쓰면 TZ 가 UTC 인
    # 곳에서 KST 새벽에 돌 때 하루가 어긋나고, POST_DATE override 도 무시된다.
    date_override = os.environ.get("POST_DATE")
    today: date = (
        datetime.strptime(date_override, "%Y-%m-%d").date()
        if date_override
        else datetime.now(ZoneInfo("Asia/Seoul")).date()
    )

    # 갱신 경로로 넘긴다(is_update=True). 원장 기록·검증·렌더가 동기화와 같아야
    # 다음 실행이 이 제도들을 '변경' 으로 다시 잡지 않는다.
    try:
        for record in targets:
            # ⚠️ 원장 값을 레코드에 되돌려 넣은 뒤에 넘긴다. sync.py:218-220 이
            #    하는 것과 같은 일이다.
            #
            #    안 하면 mark_updated 가 **지역에서 다시 계산한 해시**로 원장을
            #    덮어쓴다. 저장된 레코드는 clean_text 를 거쳐 저장되므로 수집
            #    시점 해시와 같다는 보장이 없고, 실제로 385건 중 156건이 이미
            #    다르다. 그러면 다음 동기화가 이 제도들을 '변경' 으로 다시 잡아
            #    재생성이 한 번 더 든다 — 원장을 맞추려던 것이 오히려 어긋난다.
            #    (registry.py 의 mark_checked 위 주석에 같은 사고가 적혀 있다.
            #     2026-08-22 에 그렇게 8건을 헛되이 재생성했다)
            entry = reg.get(record.id)
            if entry is not None:
                record.content_hash = entry.content_hash
                record.first_published = entry.first_published
                record.revision = entry.revision

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
