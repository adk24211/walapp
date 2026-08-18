"""어댑터 공통 유틸 + 인터페이스.

의도적으로 표준 라이브러리만 쓴다. 목 모드에서는 네트워크 의존성이 전혀 없어야
API 키 없이도 파이프라인 전체를 돌려 검증할 수 있다.
"""
from __future__ import annotations

import re
from datetime import date

import schema
import taxonomy
from schema import ApplyPeriod, ProgramRecord, Region


class BaseAdapter:
    """어댑터 인터페이스.

    구현체는 `source` 와 `fetch()` 만 채우면 된다.
    `fetch()` 는 표준 `ProgramRecord` 리스트를 돌려준다.
    """

    source: str = "unknown"

    def fetch(self, limit: int | None = None) -> list[ProgramRecord]:
        raise NotImplementedError

    def enrich(self, record: ProgramRecord) -> None:
        """발행·갱신 직전에 레코드를 보강한다. 기본은 아무것도 하지 않는다.

        상세 조회에 일일 트래픽 제한이 걸린 소스(중앙부처복지서비스는 100회)를 위해
        존재한다. 수집 단계에서 전부 받지 않고, 그날 실제로 쓸 것만 받는다.

        ⚠️ 구현할 때 `content_hash` 를 다시 계산하지 말 것. 동기화는 목록 응답만으로
        해시를 만들므로, 보강분을 해시에 넣으면 다음 날 전부 '변경됨'으로 잡힌다.
        """
        return None

    # ── 구현체가 쓰는 공통 헬퍼 ──
    def build(
        self,
        source_id: str,
        name: str,
        *,
        org: str = "",
        target_raw: str = "",
        benefit_raw: str = "",
        criteria_raw: str = "",
        how_to_raw: str = "",
        documents_raw: list[str] | None = None,
        apply_start: str = "",
        apply_end: str = "",
        always: bool = False,
        apply_period_raw: str = "",
        apply_url: str = "",
        official_url: str = "",
        contact_raw: str = "",
        receiver_raw: str = "",
        law_raw: str = "",
        region_scope: str = taxonomy.REGION_NATIONAL,
        sido: str | None = None,
        sigungu: str | None = None,
        category: str | None = None,
        audiences: list[str] | None = None,
        source_category_raw: str = "",
        view_count: int = 0,
        source_registered: str = "",
        is_mock: bool = False,
        deferred_detail: bool = False,
    ) -> ProgramRecord:
        """원천 값 → 표준 레코드. 분류가 비면 키워드로 추정한다."""
        name = clean_text(name)
        blob = " ".join([name, target_raw, benefit_raw, criteria_raw,
                         source_category_raw, org])

        # 대상 목록이 인자로 넘어왔으면 원천이 직접 분류한 값이다(복지로의
        # lifeArray·trgterIndvdlArray). 키워드 추정보다 신뢰도가 높으므로
        # 대표 테마를 고를 때 표기 순서를 그대로 존중한다.
        audiences_from_source = audiences is not None and len(audiences) > 0

        record = ProgramRecord(
            id=schema.make_id(self.source, source_id),
            source=self.source,
            source_id=str(source_id),
            slug=schema.make_slug(name, source_id),
            name=name,
            org=clean_text(org),
            category=category or taxonomy.classify_category(blob),
            audiences=audiences if audiences is not None else taxonomy.classify_audiences(blob),
            region=Region(scope=region_scope, sido=sido, sigungu=sigungu),
            target_raw=clean_text(target_raw),
            benefit_raw=clean_text(benefit_raw),
            criteria_raw=clean_text(criteria_raw),
            how_to_raw=clean_text(how_to_raw),
            documents_raw=[clean_text(d) for d in (documents_raw or []) if clean_text(d)],
            apply_period=ApplyPeriod(
                start=normalize_date(apply_start),
                end=normalize_date(apply_end),
                always=always,
                # 파싱에 실패한 표기를 나중에 세어 보려고 원문을 함께 남긴다.
                # 해시에는 들어가지 않는다 (schema.compute_hash).
                raw=clean_text(apply_period_raw),
            ),
            apply_url=apply_url.strip(),
            official_url=official_url.strip(),
            contact_raw=clean_text(contact_raw),
            receiver_raw=clean_text(receiver_raw),
            law_raw=clean_text(law_raw),
            source_category_raw=clean_text(source_category_raw),
            view_count=_to_int(view_count),
            source_registered=normalize_date(source_registered),
            is_mock=is_mock,
            deferred_detail=deferred_detail,
        )
        record.primary_audience = taxonomy.pick_primary_audience(
            record.audiences, blob, from_source=audiences_from_source
        )
        # ⚠️ 해시는 여기서 딱 한 번 계산한다. view_count 는 해시 대상이 아니므로
        #    조회수가 매일 올라가도 '변경됨' 으로 잡히지 않는다. (schema._HASHED_FIELDS)
        record.content_hash = schema.compute_hash(record)
        return record


# ─────────────────────────────────────────────────────────────
#  정규화 헬퍼
# ─────────────────────────────────────────────────────────────
_WS_RE = re.compile(r"[ \t ]+")
_TAG_RE = re.compile(r"<[^>]+>")
# CJK 한자 + 일본어 가나 (기존 generate_post.py 와 동일한 정책)
_FOREIGN_RE = re.compile(r"[㐀-䶿一-鿿぀-ゟ゠-ヺー-ヿ]")


def clean_text(value) -> str:
    """HTML 태그·과잉 공백·한자/가나 제거. **줄바꿈은 보존한다.**

    보조금24의 지원내용·선정기준은 '○' 와 '-' 불릿을 줄바꿈으로 구분한 장문이다.
    줄바꿈을 공백으로 뭉개면 읽을 수 없는 한 덩어리가 되므로 구조를 남긴다.
    """
    if value is None:
        return ""
    text = _TAG_RE.sub(" ", str(value))
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    text = _FOREIGN_RE.sub("", text)
    # '||' 는 보조금24의 다중값 구분자다 (예: "기타 온라인신청||방문신청").
    # 그대로 두면 페이지에 파이프 두 개가 그대로 찍힌다.
    text = text.replace("||", "\n")
    # 복지로 원문은 줄바꿈을 &#13;(CR) 로 넣는다. XML 파서가 \r 로 디코드하므로
    # 여기서 정규화하지 않으면 줄 구조가 통째로 사라진다.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WS_RE.sub(" ", text)                   # 가로 공백만 압축
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)   # 줄 끝 공백 정리
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_DATE_PATTERNS = (
    re.compile(r"(\d{4})[-./년\s]+(\d{1,2})[-./월\s]+(\d{1,2})"),
    # 앞뒤 숫자 배제 — '0212345678' 같은 번호에서 8자리를 잘라 날짜로 읽지 않는다.
    re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)"),
)


def _to_int(value) -> int:
    """조회수 원문 → 정수. '1,234' 같은 표기와 빈 값을 모두 받는다."""
    if value is None or value == "":
        return 0
    if isinstance(value, int):
        return max(value, 0)
    digits = re.sub(r"[^\d]", "", str(value))
    return int(digits) if digits else 0


def find_dates(value) -> list[tuple[int, int, str]]:
    """텍스트 안의 **모든** 날짜를 (시작위치, 끝위치, YYYY-MM-DD) 로 돌려준다.

    normalize_date 는 첫 하나만 보면 되지만, 기간 파싱은 몇 개가 들어 있는지를
    알아야 한다. '3월 2일부터 2월 26일까지' 에서 앞 날짜만 집어 마감일로
    읽어 버리는 사고가 여기서 갈린다. (bojo24.parse_period)

    12월 32일처럼 날짜가 아닌 숫자 뭉치는 건너뛰고 다음 후보를 본다.
    """
    if not value:
        return []
    text = str(value)
    found: list[tuple[int, int, str]] = []
    for pattern in _DATE_PATTERNS:
        for m in pattern.finditer(text):
            # 앞 패턴이 이미 잡은 자리면 중복이다 (같은 날짜가 두 번 세어진다)
            if any(m.start() < end and start < m.end() for start, end, _ in found):
                continue
            year, month, day = (int(g) for g in m.groups())
            try:
                found.append((m.start(), m.end(), date(year, month, day).isoformat()))
            except ValueError:
                continue
    found.sort(key=lambda item: item[0])
    return found


def normalize_date(value) -> str:
    """다양한 날짜 표기를 YYYY-MM-DD 로. 실패하면 빈 문자열."""
    dates = find_dates(value)
    return dates[0][2] if dates else ""


def split_documents(value) -> list[str]:
    """구비서류 원문을 항목 리스트로. 줄바꿈·쉼표·중점·번호 매김을 구분자로 본다."""
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [clean_text(v) for v in value if clean_text(v)]
    text = clean_text(value)
    parts = re.split(r"[\n·•,、]|\s\d+[.)]\s", text)
    return [p.strip(" -–—") for p in parts if len(p.strip(" -–—")) > 1]
