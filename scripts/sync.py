"""① 동기화 — 원천 API에서 제도 목록을 받아 원장과 대조한다.

레코드를 4개 통으로 나눈다:
  new       — 원장에 없음                    → 발행 후보
  changed   — 있는데 content_hash 다름        → 갱신 후보
  unchanged — 있고 해시도 같음                → last_checked 만 갱신
  blocked   — 필수 필드 누락 / 유사 제도 의심 → 격리, 발행하지 않음

'blocked' 를 따로 두는 이유: 지자체 데이터는 품질 편차가 커서 지원대상이
비어 있는 레코드가 섞여 들어온다. 이런 걸 그대로 발행하면 빈 페이지가 양산된다.
(REDESIGN.md §9)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

import registry
from collect import adapters
from schema import STATUS_CLOSED, ProgramRecord

log = logging.getLogger(__name__)


@dataclass
class SyncResult:
    new: list[ProgramRecord] = field(default_factory=list)
    changed: list[ProgramRecord] = field(default_factory=list)
    unchanged: list[ProgramRecord] = field(default_factory=list)
    incomplete: list[dict] = field(default_factory=list)
    review_needed: list[dict] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (len(self.new) + len(self.changed) + len(self.unchanged)
                + len(self.incomplete) + len(self.review_needed))

    def summary(self) -> str:
        return (f"신규 {len(self.new)} · 변경 {len(self.changed)} · 동일 {len(self.unchanged)} "
                f"· 필드누락 {len(self.incomplete)} · 유사검토 {len(self.review_needed)}")


def run(
    reg: registry.Registry,
    today: date,
    mock: bool | None = None,
    limit: int | None = None,
) -> SyncResult:
    result = SyncResult()
    today_str = today.isoformat()

    active_adapters = adapters.load_adapters(mock)
    if not active_adapters:
        log.error("활성 어댑터가 없습니다.")
        return result

    # 이번 실행에서 이미 본 id — 여러 어댑터가 같은 제도를 줄 때를 대비
    seen_ids: set[str] = set()
    # 유사도 비교 대상 = 기존 발행분 + 이번 실행에서 통과시킨 것
    known_names = reg.published_names()

    for adapter in active_adapters:
        try:
            records = adapter.fetch(limit)
        except Exception as e:
            log.error("수집 실패 [%s]: %s", adapter.source, e)
            continue
        log.info("수집 [%s]: %d건", adapter.source, len(records))

        for record in records:
            if record.id in seen_ids:
                continue
            seen_ids.add(record.id)

            _apply_status(record, today)

            # ── 필수 필드 검사 ──
            if not record.is_complete():
                result.incomplete.append({
                    "id": record.id,
                    "name": record.name,
                    "source": record.source,
                    "missing": record.missing_fields(),
                })
                continue

            existing = reg.get(record.id)

            # ── 이미 발행된 제도 ──
            if existing is not None:
                record.first_published = existing.first_published
                record.revision = existing.revision
                if existing.content_hash != record.content_hash:
                    result.changed.append(record)
                else:
                    record.last_updated = existing.last_updated
                    result.unchanged.append(record)
                    reg.mark_checked(record.id, today_str, record.status)
                continue

            # ── 신규 — 유사 제도 검사 ──
            similar = registry.find_similar(record, known_names)
            if similar:
                similar_id, score = similar
                result.review_needed.append({
                    "id": record.id,
                    "name": record.name,
                    "similar_to": similar_id,
                    "similar_name": known_names_lookup(known_names, similar_id),
                    "score": score,
                    "note": "자동 병합하지 않습니다. 같은 제도면 원장에 수동 병합하고, 다른 제도면 이 항목을 지우세요.",
                })
                continue

            known_names[record.name] = record.id
            result.new.append(record)

    log.info("동기화 결과 — %s", result.summary())
    return result


def _apply_status(record: ProgramRecord, today: date) -> None:
    """신청 기한이 지났으면 상태를 closed 로. 페이지는 지우지 않는다."""
    if record.apply_period.is_closed(today):
        record.status = STATUS_CLOSED


def known_names_lookup(known: dict[str, str], program_id: str) -> str:
    for name, pid in known.items():
        if pid == program_id:
            return name
    return ""
