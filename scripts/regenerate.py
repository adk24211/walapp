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

   단, **더 얇게 써서 되돌린 것은 아무것도 바뀌지 않아야 한다** — 원장 항목·
   레코드·페이지를 통째로 되돌리고, 그 제도는 30일 동안 다시 고르지 않는다
   (regenerate_one · COOLDOWN_DAYS 주석). 2026-11-28 까지는 판·수정일이 남아
   513번 "오늘 고쳤다" 고 말했고, 같은 제도를 매일 다시 골라 재생성 몫을 버렸다.

    python3 scripts/regenerate.py --dry-run        # 대상만 본다 (LLM 호출 없음)
    python3 scripts/regenerate.py --limit 40       # 실제로 다시 쓴다
    python3 scripts/regenerate.py --name 구직급여  # 이름으로 지정 (여러 번 가능)
"""
from __future__ import annotations

import argparse
import copy
import json
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

# ── 되돌린 제도는 한동안 다시 고르지 않는다 ──
#
# 왜 필요했나 (2026-11-28 측정)
# ─────────────────────────────
# 다시 쓴 것이 더 얇으면 되돌린다(아래 regenerate_one). 그런데 되돌린 페이지는
# 그대로 얇으니 **이튿날 또 대상이 되고**, 조회수 순으로 고르므로 늘 맨 앞이다.
# 같은 원문에 같은 프롬프트라 결과도 대개 같다 — 또 얇아지고 또 되돌린다.
#
#   09-03 ~ 11-28 동안 되돌림 513번, 37개 제도. 그중 30개가 전체의 98%.
#   '구직자 취업지원 서비스 제공'(조회 21만) 71번, '한식진흥 및 음식관광활성화' 45번.
#   매일 재생성 몫 8건 중 평균 5.9건(최근엔 6~7건)이 이렇게 버려졌다 — 토큰 약 240만.
#   그리고 조회수가 높은 그 제도들이 앞자리를 차지해, 조건에 맞는 나머지 28건은
#   한 번도 차례가 오지 않았다.
#
# 그래서 되돌린 제도는 기억해 두고 COOLDOWN_DAYS 동안 고르지 않는다. 원문이
# 바뀌면(원장 해시가 달라지면) 기다리지 않는다 — 쓸 거리가 달라졌으니 다시
# 써 볼 만하다. --name 으로 직접 지정하면 기억을 무시한다.
#
# 영영 빼지 않고 날짜로 두는 이유: 모델 출력은 매번 조금씩 다르다. 오늘
# 전세보증금반환보증 보증료 지원은 같은 줄에서 +106자로 성공했다. 한 달에 한 번
# 다시 시도할 값은 있다.
COOLDOWN_DAYS = 30
REVERTED_FILE = registry.DATA_DIR / "regen_reverted.json"


def load_reverted() -> dict:
    try:
        data = json.loads(REVERTED_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_reverted(memory: dict) -> None:
    REVERTED_FILE.write_text(json.dumps(memory, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                             encoding="utf-8")


def cooling_down(pid: str, entry, memory: dict, today: date) -> bool:
    """최근에 되돌렸고, 그 뒤로 원문이 그대로인가."""
    m = memory.get(pid)
    if not m or entry is None:
        return False
    if m.get("content_hash") != entry.content_hash:
        return False   # 원문이 바뀌었다 — 다시 써 볼 만하다
    try:
        return (today - date.fromisoformat(m["date"])).days < COOLDOWN_DAYS
    except (KeyError, ValueError):
        return False


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


def regenerate_one(record, reg: registry.Registry, today: date, client,
                   result: publish.WriteResult, memory: dict) -> str:
    """한 제도를 다시 쓴다. 'accepted' · 'reverted' · 'rejected' 중 하나를 돌려준다.

    한도가 소진되면 generate_program.DailyQuotaExhausted 를 그대로 올린다.
    """
    # ⚠️ 원장 값을 레코드에 되돌려 넣은 뒤에 넘긴다. sync.py 가 하는 것과 같은 일이다.
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

    # ⚠️ 되돌릴 때 쓸 '이전 상태' 는 **사본으로** 떠 둔다.
    #
    #    예전에는 위의 entry 를 그대로 붙잡고 있다가 되돌릴 때 거기서 판·날짜를
    #    다시 읽었다. 그런데 entry 는 원장 안의 **바로 그 객체**이고, _write_one 이
    #    mark_updated 로 그 객체를 제자리에서 바꾼다(판 +1, 수정일·확인일 = 오늘).
    #    그래서 '되돌린' 판·날짜가 이미 바뀐 값이었다 — 해설만 돌아가고 원장·레코드·
    #    페이지는 "오늘 고쳤다" 고 말했다. dateModified 와 사이트맵 lastmod 가 매일
    #    오늘이 됐고, 513번 그랬다(위 COOLDOWN_DAYS 주석).
    #
    #    판·날짜를 하나하나 되돌리지 않고 **파일과 원장 항목을 통째로** 되돌린다.
    #    "아무 일도 없었던 것처럼" 은 하나를 빠뜨리는 순간 거짓이 된다.
    saved_entry = copy.copy(entry) if entry is not None else None
    record_file = registry.RECORDS_DIR / f"{record.id}.json"
    page_file = registry.PROGRAMS_DIR / record.path()
    saved_record_text = record_file.read_text(encoding="utf-8") if record_file.exists() else None
    saved_page_text = page_file.read_text(encoding="utf-8") if page_file.exists() else None

    # ⚠️ 다시 쓴 것이 더 얇으면 되돌린다.
    #
    #    2026-09-02 배치에서 28건 중 2건이 그렇게 됐다. 특히
    #    '구직자 취업지원 서비스 제공'(조회 209,401)은 439자 → 205자로
    #    반 토막이 났다 — 자격 3개가 2개("구직자"/"취업희망자", 사실상
    #    제목 되풀이)로 줄고, 절차 2단계가 뭉뚱그린 1단계가 되고,
    #    자주 묻는 질문 절이 통째로 사라졌다. 원문 635자짜리라
    #    프롬프트가 요구한 하한(자격 4~7 · 절차 2~4)에도 못 미친다.
    #
    #    모델이 하한을 지키지 않는 일은 막을 수 없지만, 그 결과를
    #    **받아들일지는** 우리가 정할 수 있다. 얇은 페이지를 두껍게
    #    하려고 도는 작업이 페이지를 얇게 만들면 그건 그냥 손해다.
    #    되돌리는 데 토큰이 들지 않는다 — 이전 해설이 아직
    #    prev_prose 에 있다.
    #
    #    '같으면' 이 아니라 '더 얇으면' 만 되돌린다. 길이가 줄지 않은
    #    재작성은 문장이 나아졌을 수 있으므로 판단하지 않는다.
    prev_prose = registry.load_prose(record.id)
    before = own_len(record)
    updated_before = len(result.updated)
    publish._write_one(record, reg, today, client, True, False, result)
    if len(result.updated) == updated_before:
        return "rejected"   # 생성·검증에서 반려 — 아무것도 쓰지 않았다
    after = own_len(record)

    if prev_prose and after < before:
        log.warning("  ⤺ %s — %d자 → %d자 로 얇아져 이전 문장을 되돌립니다.",
                    record.name, before, after)
        if saved_entry is not None:
            reg.entries[record.id] = saved_entry
        if saved_record_text is not None:
            record_file.write_text(saved_record_text, encoding="utf-8")
        else:
            registry.save_record(record, prev_prose)
        if saved_page_text is not None:
            page_file.write_text(saved_page_text, encoding="utf-8")
        else:
            page_file.parent.mkdir(parents=True, exist_ok=True)
            page_file.write_text(render.to_markdown(record, prev_prose), encoding="utf-8")
        result.updated.remove(record.id)
        prev = memory.get(record.id) or {}
        memory[record.id] = {
            "name": record.name,
            "date": today.isoformat(),
            "content_hash": saved_entry.content_hash if saved_entry else record.content_hash,
            "before": before, "after": after,
            "times": int(prev.get("times", 0)) + 1,
        }
        return "reverted"

    memory.pop(record.id, None)   # 받아들였다 — 기억할 이유가 없다
    if after != before:
        log.info("  └ 자체 문장 %d자 → %d자 (%+d)", before, after, after - before)
    return "accepted"


def select_targets(records: dict, reg: registry.Registry, memory: dict, today: date, *,
                   min_raw: int, max_own: int, names: list[str]) -> tuple[list, int]:
    """다시 쓸 대상과, 최근에 되돌려 이번에 뺀 수."""
    if names:
        wanted = set(names)
        targets = [r for r in records.values() if r.name in wanted]
        for m in wanted - {r.name for r in targets}:
            log.warning("그런 제도가 없습니다: %s", m)
        return targets, 0
    eligible = [r for r in records.values()
                if r.status != "closed"
                and raw_len(r) >= min_raw
                and own_len(r) < max_own]
    targets = [r for r in eligible if not cooling_down(r.id, reg.get(r.id), memory, today)]
    # 조회수 높은 것부터. 한도에 걸려 잘리더라도 많이 보는 쪽이 먼저 나아진다.
    targets.sort(key=lambda r: -(r.view_count or 0))
    return targets, len(eligible) - len(targets)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-raw", type=int, default=600, help="이 글자 수 이상인 원문만 대상 (기본 600)")
    ap.add_argument("--max-own", type=int, default=500, help="이 글자 수 미만인 해설만 대상 (기본 500)")
    ap.add_argument("--limit", type=int, default=40, help="최대 몇 건까지 다시 쓸지 (기본 40)")
    ap.add_argument("--name", action="append", default=[], help="제도명으로 직접 지정. 조건과 되돌림 기억을 무시한다")
    ap.add_argument("--dry-run", action="store_true", help="대상만 보고 끝낸다. LLM 을 부르지 않는다")
    args = ap.parse_args()

    records = registry.load_all_records()
    if not records:
        log.error("_records/ 가 비어 있습니다.")
        return 1

    # run_all 과 같은 방식으로 날짜를 정한다. date.today() 를 쓰면 TZ 가 UTC 인
    # 곳에서 KST 새벽에 돌 때 하루가 어긋나고, POST_DATE override 도 무시된다.
    date_override = os.environ.get("POST_DATE")
    today: date = (
        datetime.strptime(date_override, "%Y-%m-%d").date()
        if date_override
        else datetime.now(ZoneInfo("Asia/Seoul")).date()
    )
    reg = registry.Registry()
    memory = load_reverted()

    targets, cooling = select_targets(records, reg, memory, today, min_raw=args.min_raw,
                                      max_own=args.max_own, names=args.name)
    if cooling:
        log.info("최근 %d일 안에 되돌려 이번에 뺀 것 %d건 (원문이 바뀌면 다시 고른다).",
                 COOLDOWN_DAYS, cooling)

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

    result = publish.WriteResult()
    reverted: list[str] = []
    # 갱신 경로로 넘긴다(is_update=True). 원장 기록·검증·렌더가 동기화와 같아야
    # 다음 실행이 이 제도들을 '변경' 으로 다시 잡지 않는다.
    try:
        for record in targets:
            if regenerate_one(record, reg, today, client, result, memory) == "reverted":
                reverted.append(record.name)
    except generate_program.DailyQuotaExhausted as e:
        log.warning("일일 한도 소진 — 여기서 멈춥니다: %s", e)
        log.warning("다시 쓴 %d건은 그대로 남습니다. 내일 이어서 돌리면 됩니다.", len(result.updated))

    reg.save()
    save_reverted(memory)
    log.info("완료 — 다시 씀 %d건 · 되돌림 %d건 · 반려 %d건",
             len(result.updated), len(reverted), len(result.rejected))
    for name in reverted:
        m = next((v for v in memory.values() if v.get("name") == name), {})
        log.warning("  되돌림 [%s] %s자 → %s자 — %d일 동안 다시 고르지 않습니다 (지금까지 %s번)",
                    name, m.get("before"), m.get("after"), COOLDOWN_DAYS, m.get("times"))
    for item in result.rejected:
        log.warning("  반려 [%s] %s", item.get("name"), item.get("reason"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
