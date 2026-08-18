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
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

import registry
import schema
from collect import adapters
from schema import STATUS_SUPERSEDED, ProgramRecord

log = logging.getLogger(__name__)


# 초기 운영 범위. 중앙부처(전국) 제도부터 시작한다 — 데이터 품질이 균일하고,
# 지자체는 건수가 많아 초기에 품질 관리가 어렵다. (REDESIGN.md §11 확정)
# 지자체까지 넓힐 때는 REGION_SCOPE 환경변수에 "national,sido,sigungu" 를 준다.
DEFAULT_SCOPES = ("national",)


@dataclass
class PeriodStats:
    """신청기한 표기 분포 — 파서를 어디까지 넓힐지 정하는 근거.

    레코드 파일은 내용이 바뀐 것만 다시 쓰므로, 저장된 원문(ApplyPeriod.raw)만
    봐서는 이미 발행된 몇십 건밖에 알 수 없다. 반면 동기화는 매번 원천 전량을
    훑는다. 그 자리에서 세어 두면 만 건 규모의 실제 분포가 남는다.
    """

    total: int = 0
    always: int = 0        # 상시 접수 — 날짜가 없는 게 정상
    both: int = 0          # 시작·마감 둘 다
    start_only: int = 0
    end_only: int = 0
    no_raw: int = 0        # 원문 자체가 비어 있음
    unparsed: Counter = field(default_factory=Counter)   # 원문은 있는데 날짜를 못 뽑음
    sources: Counter = field(default_factory=Counter)

    def add(self, record) -> None:
        period = record.apply_period
        self.total += 1
        self.sources[record.source] += 1
        if period.always:
            self.always += 1
        elif period.start and period.end:
            self.both += 1
        elif period.start:
            self.start_only += 1
        elif period.end:
            self.end_only += 1
        elif not period.raw:
            self.no_raw += 1
        else:
            # 이 표기들이 곧 다음 파서 작업 목록이다
            self.unparsed[period.raw[:80]] += 1

    def to_dict(self, top: int = 40) -> dict:
        return {
            "total": self.total,
            "always": self.always,
            "both": self.both,
            "start_only": self.start_only,
            "end_only": self.end_only,
            "no_raw": self.no_raw,
            "unparsed": sum(self.unparsed.values()),
            "sources": dict(self.sources),
            # 빈도 상위 표기. 파서를 넓힐 때 여기 위쪽부터 본다.
            "unparsed_top": [{"raw": raw, "count": n}
                             for raw, n in self.unparsed.most_common(top)],
        }


@dataclass
class SyncResult:
    new: list[ProgramRecord] = field(default_factory=list)
    changed: list[ProgramRecord] = field(default_factory=list)
    # 내용은 그대로인데 상태만 바뀐 것 (시행중 → 종료 / 예정 → 시행중).
    # 해설을 다시 만들지 않고 저장분으로 페이지만 다시 찍는다.
    restatused: list[ProgramRecord] = field(default_factory=list)
    unchanged: list[ProgramRecord] = field(default_factory=list)
    incomplete: list[dict] = field(default_factory=list)
    review_needed: list[dict] = field(default_factory=list)
    out_of_scope: int = 0
    # 발행 여부와 무관하게 이번 실행이 훑은 전량의 신청기한 표기 분포
    period_stats: PeriodStats = field(default_factory=PeriodStats)

    @property
    def total(self) -> int:
        return (len(self.new) + len(self.changed) + len(self.restatused)
                + len(self.unchanged) + len(self.incomplete)
                + len(self.review_needed) + self.out_of_scope)

    def summary(self) -> str:
        text = (f"신규 {len(self.new)} · 변경 {len(self.changed)} "
                f"· 상태변경 {len(self.restatused)} · 동일 {len(self.unchanged)} "
                f"· 필드누락 {len(self.incomplete)} · 유사검토 {len(self.review_needed)}")
        if self.out_of_scope:
            text += f" · 범위밖 {self.out_of_scope}"
        return text


def run(
    reg: registry.Registry,
    today: date,
    mock: bool | None = None,
    limit: int | None = None,
    scopes: tuple[str, ...] = DEFAULT_SCOPES,
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

            # 발행 여부를 가리기 전에 센다 — 파서 진단은 전량이 대상이다
            result.period_stats.add(record)

            # ── 필수 필드 검사 ──
            # deferred_detail 인 소스는 목록 응답에 지원대상이 없다. 여기서 걸러 내면
            # 상세를 붙일 기회(publish 의 enrich)조차 오지 않는다. 발행 직전에 다시 본다.
            if not record.is_complete() and not record.deferred_detail:
                result.incomplete.append({
                    "id": record.id,
                    "name": record.name,
                    "source": record.source,
                    "missing": record.missing_fields(),
                })
                continue

            existing = reg.get(record.id)

            # ── 상태 판정 ──
            # 원장의 상태를 이어받지 않고 오늘 날짜로 매번 다시 계산한다.
            # 사람이 붙인 superseded 만 물려받는다 (schema.resolve_status 참고).
            if existing is not None and existing.status == STATUS_SUPERSEDED:
                record.status = STATUS_SUPERSEDED
            record.status = schema.resolve_status(record, today)

            # ── 운영 범위 검사 ──
            # 이미 발행된 제도는 범위와 무관하게 계속 추적한다. 범위를 좁혔다고
            # 살아 있는 페이지를 방치하면 정보가 낡은 채로 남는다.
            # 아직 발행 전인 제도만 범위 밖이면 건너뛴다 — 원천에서 매번 다시 읽으므로,
            # 나중에 REGION_SCOPE 를 넓히면 그날 신규로 잡혀 그대로 발행된다.
            if existing is None and record.region.scope not in scopes:
                result.out_of_scope += 1
                continue

            # ── 이미 발행된 제도 ──
            if existing is not None:
                record.first_published = existing.first_published
                record.revision = existing.revision
                if existing.content_hash != record.content_hash:
                    result.changed.append(record)
                elif existing.status != record.status:
                    # 내용은 그대로인데 날짜가 지나 상태만 바뀐 경우
                    # (예: 어제까지 시행중 → 오늘부터 종료).
                    # 페이지를 다시 찍지 않으면 마감된 제도가 계속 '시행중' 으로 보인다.
                    # 해설은 저장해 둔 것을 재사용하므로 LLM 호출이 들어가지 않는다.
                    record.last_updated = existing.last_updated
                    result.restatused.append(record)
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


def known_names_lookup(known: dict[str, str], program_id: str) -> str:
    for name, pid in known.items():
        if pid == program_id:
            return name
    return ""
