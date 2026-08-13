"""제도 레코드 표준 스키마.

원천 API(보조금24·복지로·온통청년)는 응답 형태가 제각각이다.
어댑터가 이 스키마로 변환한 뒤부터 파이프라인 전체는 동일한 구조만 다룬다.
→ 실제 API 필드명이 무엇으로 밝혀지든 어댑터만 고치면 된다. (REDESIGN.md §3.2)

핵심 규칙:
  * `id` 가 전역 primary key다. 같은 제도는 항상 같은 id → 같은 파일 경로 →
    두 번째 수집은 새 글이 아니라 갱신이 된다. 중복은 규칙이 아니라 자료구조로 막는다.
  * `*_raw` 필드는 원천 API 원문이다. LLM이 절대 건드리지 않는 사실 원본이며,
    페이지에도 이 값이 그대로 렌더된다.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date

import taxonomy

# ─────────────────────────────────────────────────────────────
#  상태
# ─────────────────────────────────────────────────────────────
STATUS_ACTIVE = "active"          # 시행중 — 신청 가능 / 상시
STATUS_UPCOMING = "upcoming"      # 예정 — 접수 시작일이 아직 오지 않음
STATUS_CLOSED = "closed"          # 종료 — 접수 마감 (페이지는 유지, noindex)
STATUS_SUPERSEDED = "superseded"  # 다른 제도로 대체됨

# 화면 표기. 파이썬과 Liquid 양쪽이 같은 문구를 쓰도록 여기서만 정의한다.
STATUS_LABELS = {
    STATUS_ACTIVE: "시행중",
    STATUS_UPCOMING: "예정",
    STATUS_CLOSED: "종료",
    STATUS_SUPERSEDED: "대체됨",
}

# 필수 필드가 비면 발행하지 않고 격리한다 (REDESIGN.md §9 지자체 데이터 품질 편차)
REQUIRED_RAW_FIELDS = ("target_raw", "benefit_raw")


@dataclass
class ApplyPeriod:
    start: str = ""          # YYYY-MM-DD, 미상이면 ""
    end: str = ""            # YYYY-MM-DD, 미상이면 ""
    always: bool = False     # 상시 접수 여부

    def is_closed(self, today: date) -> bool:
        if self.always or not self.end:
            return False
        try:
            return date.fromisoformat(self.end) < today
        except ValueError:
            return False

    def is_upcoming(self, today: date) -> bool:
        """접수 시작일이 아직 오지 않았는가.

        ⚠️ 이건 '내년 신설 예정 정책' 이 아니다. 두 원천 API(보조금24·중앙부처
        복지서비스)는 **현재 운영 중인 서비스 목록**만 준다. 여기서 잡히는 '예정'은
        "이미 등록된 사업인데 올해 접수가 아직 시작되지 않음" 이다.
        원천에 없는 신설 정책을 예정으로 만들어 내지 않는다. (사용자 확정 사항)
        """
        if self.always or not self.start:
            return False
        try:
            return date.fromisoformat(self.start) > today
        except ValueError:
            return False

    def days_until_open(self, today: date) -> int | None:
        """접수 시작까지 남은 일수. 이미 시작했거나 미상이면 None."""
        if not self.is_upcoming(today):
            return None
        return (date.fromisoformat(self.start) - today).days

    def days_left(self, today: date) -> int | None:
        """마감까지 남은 일수. 상시/미상이면 None."""
        if self.always or not self.end:
            return None
        try:
            return (date.fromisoformat(self.end) - today).days
        except ValueError:
            return None


@dataclass
class Region:
    scope: str = taxonomy.REGION_NATIONAL   # national | sido | sigungu
    sido: str | None = None                 # taxonomy.SIDO 의 키
    sigungu: str | None = None              # 표시용 원문 (예: '성남시')

    @property
    def label(self) -> str:
        return taxonomy.region_label(self.scope, self.sido, self.sigungu)


@dataclass
class ProgramRecord:
    """지원 제도 한 건. 파이프라인 전체의 표준 단위."""

    # ── 식별 ──
    id: str                       # "{source}-{source_id}" · 전역 primary key
    source: str                   # bojo24 | welfare-central | welfare-local | youth | mock
    source_id: str
    slug: str                     # URL 마지막 세그먼트

    # ── 표시 ──
    name: str
    org: str = ""                 # 소관 기관
    category: str = taxonomy.DEFAULT_CATEGORY
    audiences: list[str] = field(default_factory=list)
    # 대표 테마 — 이 제도를 '어느 테마의 오늘 1건' 으로 셀지. 한 제도가 청년·구직자
    # 양쪽에 걸쳐도 발행은 한 번뿐이므로 대표를 하나 정해 둔다. 나머지 테마 허브에는
    # `audiences` 로 계속 노출된다. (taxonomy.pick_primary_audience)
    primary_audience: str = ""
    region: Region = field(default_factory=Region)

    # ── 사실 원본 (LLM 접근 금지) ──
    target_raw: str = ""          # 지원 대상
    benefit_raw: str = ""         # 지원 내용
    criteria_raw: str = ""        # 선정 기준
    how_to_raw: str = ""          # 신청 방법
    documents_raw: list[str] = field(default_factory=list)  # 구비 서류

    contact_raw: str = ""         # 전화문의
    receiver_raw: str = ""        # 접수기관
    law_raw: str = ""             # 근거 법령 (YMYL 신뢰도 요소)

    apply_period: ApplyPeriod = field(default_factory=ApplyPeriod)
    apply_url: str = ""
    official_url: str = ""

    source_category_raw: str = ""  # 원천 분류 원문 (재매핑 검증용 보관)

    # ── 인기도 (발행 우선순위 전용) ──
    # 보조금24 `조회수`, 중앙부처복지서비스 `inqNum`. 두 값은 스케일이 달라
    # 직접 비교하지 않고 queueing 에서 소스별 백분위로 정규화한다.
    view_count: int = 0
    source_registered: str = ""    # 원천 최초 등록일 (복지로 svcfrstRegTs)

    # ── 이력 ──
    content_hash: str = ""
    first_published: str = ""
    last_updated: str = ""
    last_checked: str = ""
    revision: int = 0
    status: str = STATUS_ACTIVE

    # ── 플래그 ──
    is_mock: bool = False         # True면 페이지에 경고 배너 + noindex
    # True면 필수 필드가 상세 조회로만 채워진다. 동기화 단계의 완결성 검사를
    # 건너뛰고, 발행 직전 enrich() 뒤에 다시 검사한다.
    # (이 플래그가 없으면 목록에 지원대상이 없는 소스는 격리되어 enrich 가
    #  영영 호출되지 않는다 — 닭과 달걀 문제)
    deferred_detail: bool = False

    # ── 파생 ──
    def path(self) -> str:
        """_programs 하위 상대 경로."""
        return f"{self.category}/{self.slug}.md"

    def url(self) -> str:
        return f"/support/{self.category}/{self.slug}/"

    def is_complete(self) -> bool:
        return all(getattr(self, f, "").strip() for f in REQUIRED_RAW_FIELDS)

    def missing_fields(self) -> list[str]:
        return [f for f in REQUIRED_RAW_FIELDS if not getattr(self, f, "").strip()]

    # ── 직렬화 ──
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ProgramRecord":
        data = dict(data)
        data["region"] = Region(**(data.get("region") or {}))
        data["apply_period"] = ApplyPeriod(**(data.get("apply_period") or {}))
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


# ─────────────────────────────────────────────────────────────
#  콘텐츠 해시 — 변경 감지 전용
# ─────────────────────────────────────────────────────────────
# 해시 대상: '내용'에 해당하는 필드만. last_checked 같은 운영 메타는 제외해야
# 매일 동기화할 때마다 전부 '변경됨'으로 잡히는 사고를 막는다.
#
# ⚠️ `view_count` 를 여기 넣지 말 것. 조회수는 원천에서 **매일 바뀐다.**
#    해시에 들어가면 매 실행마다 1만 건 전체가 '변경됨' 으로 잡혀 갱신 큐가 터진다.
#    같은 이유로 `source_registered`, `primary_audience`(audiences 에서 파생),
#    `status`(날짜에서 파생) 도 제외한다.
_HASHED_FIELDS = (
    "name", "org", "category", "audiences",
    "target_raw", "benefit_raw", "criteria_raw", "how_to_raw", "documents_raw",
    "contact_raw", "receiver_raw", "law_raw", "apply_url", "official_url",
)


def _normalize_for_hash(value) -> str:
    if isinstance(value, (list, tuple)):
        return "|".join(_normalize_for_hash(v) for v in value)
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def compute_hash(record: ProgramRecord) -> str:
    """레코드 내용 해시. 공백·유니코드 표기 차이는 무시한다."""
    payload = {f: _normalize_for_hash(getattr(record, f)) for f in _HASHED_FIELDS}
    payload["apply_period"] = _normalize_for_hash(
        [record.apply_period.start, record.apply_period.end, record.apply_period.always]
    )
    payload["region"] = _normalize_for_hash(
        [record.region.scope, record.region.sido, record.region.sigungu]
    )
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


# ─────────────────────────────────────────────────────────────
#  slug 생성
# ─────────────────────────────────────────────────────────────
_SLUG_STRIP_RE = re.compile(r"[^가-힣a-zA-Z0-9]+")


def make_slug(name: str, source_id: str = "") -> str:
    """제도명에서 URL slug 생성.

    한글을 로마자로 옮기지 않고 그대로 쓴다. 한글 URL은 브라우저가 퍼센트
    인코딩하지만 검색엔진이 정상 처리하고, 사용자에게는 의미가 그대로 보인다.
    로마자 표기는 규칙이 흔들려 같은 제도가 다른 slug를 갖는 사고가 나기 쉽다.
    """
    base = _SLUG_STRIP_RE.sub("-", unicodedata.normalize("NFC", name or "")).strip("-")
    base = re.sub(r"-{2,}", "-", base)
    if len(base) > 40:
        base = base[:40].rstrip("-")
    if not base:
        base = f"program-{source_id or 'unknown'}"
    return base.lower()


def make_id(source: str, source_id: str) -> str:
    return f"{source}-{source_id}"


# ─────────────────────────────────────────────────────────────
#  상태 판정
# ─────────────────────────────────────────────────────────────
def resolve_status(record: "ProgramRecord", today: date) -> str:
    """신청 기간과 오늘 날짜로 상태를 정한다.

    매 실행마다 **다시 계산한다.** 저장된 값을 이어받지 않는 것이 중요하다.
    매년 반복되는 사업은 작년 회차가 끝나 종료로 잡혔다가, 원천이 올해 기간으로
    갱신되면 그날 자동으로 시행중/예정으로 돌아와야 한다. 상태를 원장에서 물려받으면
    한 번 종료된 제도가 영원히 종료로 남는다.

    `superseded` 만 예외다. 이건 날짜가 아니라 사람이 판단해 붙이는 값이므로 보존한다.
    """
    if record.status == STATUS_SUPERSEDED:
        return STATUS_SUPERSEDED
    period = record.apply_period
    if period.is_upcoming(today):
        return STATUS_UPCOMING
    if period.is_closed(today):
        return STATUS_CLOSED
    return STATUS_ACTIVE
