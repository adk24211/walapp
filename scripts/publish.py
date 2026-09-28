"""③ 발행 · ④ 갱신 — 레코드를 실제 페이지 파일로 쓴다.

발행과 갱신을 한 모듈에 두는 이유: 둘의 차이는 원장 기록 방식뿐이고,
"해설 생성 → 검증 → 파일 쓰기" 과정은 완전히 같다. 같은 코드를 두 번 쓰지 않는다.

파일 경로는 `record.path()` 로 결정된다. 같은 제도는 **대개** 같은 경로이므로
갱신은 자연스럽게 덮어쓰기가 된다. 이것이 중복 방지의 1계층이다.

⚠️ '항상 같은 경로' 는 아니다. 경로는 분류와 제도명에서 나오고 둘 다 원천에서
   바뀐다 — 보훈요양원 세 곳이 education 에서 health/care 로 옮겨졌고, 어떤
   제도는 이름이 짧아지며 슬러그가 달라졌다. 그럴 때 새 경로에 새 파일이 생기고
   예전 파일은 남는다. 같은 내용이 두 주소로 서는 것이라 _drop_moved_page 가
   치운다. 아래 그 함수의 주석을 볼 것.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import generate_program
import registry
import schema
from collect import adapters
import render
import verify
from schema import ProgramRecord

log = logging.getLogger(__name__)


@dataclass
class WriteResult:
    published: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    restatused: list[str] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    paths: list[Path] = field(default_factory=list)
    # 경로가 옮겨져 치운 예전 페이지. 세지 않으면 조용히 지워진다.
    removed: list[Path] = field(default_factory=list)

    def summary(self) -> str:
        line = (f"발행 {len(self.published)} · 갱신 {len(self.updated)} "
                f"· 상태갱신 {len(self.restatused)} · 반려 {len(self.rejected)}")
        if self.removed:
            line += f" · 옮겨져 치운 페이지 {len(self.removed)}"
        return line


def _drop_moved_page(record: ProgramRecord, reg: registry.Registry, dry_run: bool) -> Path | None:
    """제도명·분류가 바뀌어 경로가 옮겨졌으면 **예전 페이지를 지운다.**

    ⚠️ 이 장치가 없어서 같은 제도가 두 경로에 나란히 서 있었다. 2026-09-27 에
       페이지 582건 중 서로 다른 제도 id 는 578개였다 — 네 쌍이 겹쳐 있었다.

         입소 이용서비스(대구보훈요양원)   education/… 와 health/…
         입소 이용서비스(김해보훈요양원)   education/… 와 care/…
         입소 이용서비스(대전보훈요양원)   education/… 와 health/…
         귀화허가·국적회복허가 …          제도명이 짧아지며 슬러그가 바뀜

       앞의 셋은 원천이 분류를 education 에서 health/care 로 고친 것이고, 넷째는
       제도명이 바뀌어 슬러그가 달라진 것이다. 어느 쪽이든 record.path() 가
       가리키는 곳이 달라지므로 새 경로에 새 파일이 생기는데, **예전 파일을
       치우는 코드가 아무 데도 없었다.** 3주 넘게 똑같은 내용이 두 주소로
       서 있었고, 그동안 사이트맵·분류 목록·대상 허브에 둘 다 실렸다.
       애드센스 반려 사유가 '가치가 별로 없는 콘텐츠' 인 사이트에서
       제 손으로 만든 중복이다.

    ⚠️ 반드시 `reg.mark_updated` **전에** 불러야 한다. 그 함수가 entry.path 를
       새 경로로 덮어쓰므로, 뒤에 부르면 예전 경로를 알 방법이 사라진다.
       (그래서 원장만 봐서는 이미 생긴 고아 페이지를 찾을 수 없었다 —
        scripts/check_pages.py 가 파일 쪽에서 본다.)
    """
    entry = reg.get(record.id)
    if entry is None:
        return None
    old_rel = (entry.path or "").removeprefix("_programs/")
    if not old_rel or old_rel == record.path():
        return None
    old_path = registry.PROGRAMS_DIR / old_rel
    if not old_path.exists():
        return None
    # 원장이 가리키는 경로만 믿고 지우지 않는다. 그 자리에 다른 제도의 페이지가
    # 서 있을 수 있다 — slug 가 겹치면 그렇게 된다(schema._NUMERAL_MAP 주석).
    owner = registry.page_owner(old_path)
    if owner is not None and owner != record.id:
        log.warning("경로 이동: %s → %s — 예전 자리에 다른 제도(%s)의 페이지가 있어 두었습니다.",
                    old_rel, record.path(), owner)
        return None
    log.info("경로 이동: %s → %s (예전 페이지 삭제)", old_rel, record.path())
    if not dry_run:
        old_path.unlink()
    return old_path


def _write_one(
    record: ProgramRecord,
    reg: registry.Registry,
    today: date,
    client,
    is_update: bool,
    dry_run: bool,
    result: WriteResult,
) -> None:
    today_str = today.isoformat()
    record.last_checked = today_str
    record.last_updated = today_str
    if not record.first_published:
        record.first_published = today_str

    # ── 상세 보강 ──
    # 상세 조회에 일일 트래픽 제한이 있는 소스는 수집 단계에서 전부 받지 않는다.
    # 그날 실제로 쓸 레코드에만 붙인다. (collect/adapters/base.py:enrich 참고)
    adapter = adapters.get(record.source)
    if adapter is not None:
        try:
            adapter.enrich(record)
        except Exception as e:
            log.warning("상세 보강 실패 [%s]: %s — 목록 정보만으로 진행합니다.", record.id, e)

    # 보강 뒤에도 필수 필드가 비면 발행하지 않는다. 지원대상 없는 빈 페이지를
    # 양산하느니 다음 실행에 다시 시도하는 편이 낫다.
    if not record.is_complete():
        log.warning("필수 필드 누락 [%s]: %s — 발행하지 않습니다.",
                    record.id, ", ".join(record.missing_fields()))
        result.rejected.append({
            "id": record.id, "name": record.name,
            "reason": "상세 보강 후에도 필수 필드 누락: " + ", ".join(record.missing_fields()),
        })
        return

    # ── 해설 생성 ──
    try:
        prose = generate_program.generate(record, client)
    except generate_program.ModelUnavailable:
        # 설정이 깨진 것이라 제도별 반려로 삼키면 안 된다. 그대로 두면 오늘 치
        # 후보 전부가 조용히 반려되고, 로그에는 '나쁜 데이터 몇 건' 처럼 보인다.
        raise
    except generate_program.DailyQuotaExhausted as e:
        # 오늘 토큰을 다 썼다. 이 건은 반려로 남기되, 남은 후보를 계속 도는 것은
        # 무의미하다 — 전부 같은 이유로 실패한다. 위(run)에서 루프를 끊는다.
        result.rejected.append({
            "id": record.id, "name": record.name, "reason": f"일일 한도 소진: {e}",
        })
        raise
    except Exception as e:
        log.error("해설 생성 실패 [%s]: %s", record.id, e)
        result.rejected.append({"id": record.id, "name": record.name, "reason": f"생성 실패: {e}"})
        return

    # ── 사실 검증 ──
    prose, report = verify.scrub(prose, record)
    if report.fatal:
        log.error("검증 치명적 실패 [%s] — 발행하지 않습니다", record.id)
        result.rejected.append({
            "id": record.id, "name": record.name,
            "reason": "요약이 검증에서 전량 폐기됨",
            "violations": report.violations,
        })
        return

    # ── 렌더 ──
    markdown = render.to_markdown(record, prose)
    path = registry.PROGRAMS_DIR / record.path()

    moved_from = _drop_moved_page(record, reg, dry_run)
    if moved_from is not None:
        result.removed.append(moved_from)

    if dry_run:
        log.info("[DRY RUN] %s\n%s", path.relative_to(registry.ROOT), markdown[:280])
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8")
        # 해설을 레코드와 함께 저장한다 → 나중에 상태만 바뀔 때 LLM 없이 재렌더.
        registry.save_record(record, prose)
        result.paths.append(path)

    # ── 원장 기록 ──
    if is_update:
        reg.mark_updated(record, today_str)
        result.updated.append(record.id)
        log.info("갱신: %s (rev %d)", record.name, reg.entries[record.id].revision)
    else:
        reg.register(record, today_str)
        result.published.append(record.id)
        log.info("발행: %s", record.name)

    if report.violations:
        log.info("  └ 검증: %s", report.summary_line())


def _restatus_one(
    record: ProgramRecord,
    reg: registry.Registry,
    today: date,
    dry_run: bool,
    result: WriteResult,
) -> bool:
    """상태만 바뀐 제도를 저장해 둔 해설로 다시 찍는다. LLM 을 쓰지 않는다.

    저장된 해설이 없으면 False 를 돌려준다 — 호출부가 일반 갱신 경로로 넘긴다.
    """
    prose = registry.load_prose(record.id)
    if prose is None:
        return False

    today_str = today.isoformat()
    record.last_checked = today_str
    entry = reg.get(record.id)
    if entry is not None:
        record.first_published = entry.first_published
        record.last_updated = entry.last_updated
        record.revision = entry.revision

    markdown = render.to_markdown(record, prose)
    path = registry.PROGRAMS_DIR / record.path()

    # 상태만 바뀐 경우에도 경로가 옮겨질 수 있다 — 분류가 바뀐 세 보훈요양원이
    # 그 경로로 들어왔다. mark_checked 는 entry.path 를 건드리지 않으므로
    # 여기서 지우고, 원장 경로도 새 경로로 맞춘다.
    moved_from = _drop_moved_page(record, reg, dry_run)
    if moved_from is not None:
        result.removed.append(moved_from)
        entry = reg.get(record.id)
        if entry is not None:
            entry.path = f"_programs/{record.path()}"
            entry.slug = record.slug

    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8")
        registry.save_record(record, prose)
        result.paths.append(path)

    # revision 은 올리지 않는다. 내용이 바뀐 게 아니라 날짜가 지난 것뿐이다.
    reg.mark_checked(record.id, today_str, record.status)
    result.restatused.append(record.id)
    log.info("상태 갱신: %s → %s", record.name,
             schema.STATUS_LABELS.get(record.status, record.status))
    return True


def run(
    new_records: list[ProgramRecord],
    changed_records: list[ProgramRecord],
    reg: registry.Registry,
    today: date,
    client=None,
    dry_run: bool = False,
    restatused_records: list[ProgramRecord] | None = None,
) -> WriteResult:
    result = WriteResult()

    # 일일 한도가 소진되면 남은 후보는 전부 같은 이유로 실패한다. 그때는 루프를
    # 끊되 **이미 발행한 것은 그대로 둔다** — 예외를 위로 올리면 run_all 이
    # 실행을 실패로 처리해 그날 나간 것까지 배포되지 않는다. 여기서 받는다.
    #
    # 상태 갱신(_restatus_one)은 저장된 해설을 다시 찍는 것이라 LLM 을 쓰지
    # 않는다. 한도와 무관하므로 소진 뒤에도 계속 돈다.
    quota_note: str | None = None
    try:
        for record in new_records:
            _write_one(record, reg, today, client, False, dry_run, result)
        for record in changed_records:
            _write_one(record, reg, today, client, True, dry_run, result)
    except generate_program.DailyQuotaExhausted as e:
        quota_note = str(e)

    # 상태만 바뀐 것들 — 해설 재사용. 저장분이 없으면 일반 갱신으로 떨어뜨린다.
    for record in restatused_records or []:
        if not _restatus_one(record, reg, today, dry_run, result):
            if quota_note is not None:
                # 일반 갱신 경로는 LLM 을 쓴다. 한도가 없으니 시도하지 않는다.
                log.info("저장된 해설 없음 [%s] — 한도 소진으로 건너뜁니다.", record.id)
                result.rejected.append({
                    "id": record.id, "name": record.name,
                    "reason": "일일 한도 소진 — 저장된 해설이 없어 갱신 보류",
                })
                continue
            log.info("저장된 해설 없음 [%s] — 일반 갱신 경로로 처리합니다.", record.id)
            _write_one(record, reg, today, client, True, dry_run, result)

    if quota_note is not None:
        log.warning("━━━ 오늘 쓸 수 있는 토큰을 다 썼습니다 — 남은 후보는 건너뜁니다 ━━━")
        log.warning("  %s", quota_note)
        log.warning("  이미 발행된 것은 그대로 배포됩니다. 남은 제도는 다음 실행에서 다시 잡힙니다.")

    log.info("쓰기 완료 — %s", result.summary())
    return result
