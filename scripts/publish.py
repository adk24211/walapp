"""③ 발행 · ④ 갱신 — 레코드를 실제 페이지 파일로 쓴다.

발행과 갱신을 한 모듈에 두는 이유: 둘의 차이는 원장 기록 방식뿐이고,
"해설 생성 → 검증 → 파일 쓰기" 과정은 완전히 같다. 같은 코드를 두 번 쓰지 않는다.

파일 경로는 `record.path()` 로 결정된다. 같은 제도는 항상 같은 경로이므로
갱신은 자연스럽게 덮어쓰기가 된다. 이것이 중복 방지의 1계층이다.
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

    def summary(self) -> str:
        return (f"발행 {len(self.published)} · 갱신 {len(self.updated)} "
                f"· 상태갱신 {len(self.restatused)} · 반려 {len(self.rejected)}")


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

    for record in new_records:
        _write_one(record, reg, today, client, False, dry_run, result)
    for record in changed_records:
        _write_one(record, reg, today, client, True, dry_run, result)

    # 상태만 바뀐 것들 — 해설 재사용. 저장분이 없으면 일반 갱신으로 떨어뜨린다.
    for record in restatused_records or []:
        if not _restatus_one(record, reg, today, dry_run, result):
            log.info("저장된 해설 없음 [%s] — 일반 갱신 경로로 처리합니다.", record.id)
            _write_one(record, reg, today, client, True, dry_run, result)

    log.info("쓰기 완료 — %s", result.summary())
    return result
