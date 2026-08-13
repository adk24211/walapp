"""한국사회보장정보원 중앙부처복지서비스 어댑터 (복지로 기반).

공공데이터포털 데이터셋: `15090532` (자동승인, 활용기간 2년)
End Point: `https://apis.data.go.kr/B554287/NationalWelfareInformationsV001`

보조금24와 **구조가 완전히 다르다.** 그대로 베끼면 동작하지 않는다.

| | 보조금24 (15113968) | 여기 (15090532) |
|---|---|---|
| 응답 형식 | JSON | **XML** |
| 페이지 파라미터 | `page` / `perPage` | `pageNo` / `numOfRows` |
| 상세 조회 | 조건 없이 전체 페이지네이션 가능 | **`servId` 로 한 건씩만** |
| 일일 트래픽 | 표기 없음 | **오퍼레이션당 100회** |

### 트래픽 100회가 설계를 결정한다

목록조회는 `numOfRows` 최대 500이라 100회로 최대 5만 건까지 받을 수 있다. 문제는
상세조회다. `servId` 하나당 1회를 쓰므로 **하루에 100건밖에 못 받는다.**

그래서 상세를 수집 단계에서 전부 받지 않는다. `fetch()` 는 목록만 받고, 그날 실제로
발행·갱신할 레코드에 대해서만 `enrich()` 로 상세를 붙인다. 발행 상한이 하루 5건,
갱신 10건이므로 15회면 충분하고 100회 한도에 한참 못 미친다.

### 목록 응답 필드 — 실제 호출로 확정 (전체 461건)

    servId              WLF00000026             ← ID_FIELD
    servNm              장애인자립자금대여
    jurMnofNm           보건복지부               ← 소관부처
    jurOrgNm            장애인자립기반과         ← 소관부서
    servDgst            (한 줄 요약)
    servDtlLink         https://www.bokjiro.go.kr/...   ← 상세 페이지 URL
    srvPvsnNm           현금대여(융자)           ← 제공유형
    sprtCycNm           1회성                    ← 지원주기
    rprsCtadr           129                      ← 대표문의
    onapPsbltYn         Y                        ← 온라인신청 가능여부
    lifeArray           청년,중장년,노년          ← 생애주기
    trgterIndvdlArray   장애인,저소득             ← 가구유형
    intrsThemaArray     생활지원,일자리,서민금융  ← 관심주제

**목록에는 지원대상·지원내용·선정기준·신청방법이 없다.** 요약(`servDgst`)뿐이라
`deferred_detail=True` 로 두고 상세에서 채운다.

원천 분류 3종(`intrsThemaArray`·`lifeArray`·`trgterIndvdlArray`)은 본문 키워드 추정보다
정확하므로 `taxonomy.map_bokjiro()` 로 직접 매핑한다. 표에 없는 값이 오면 키워드 추정으로
넘어간다.
"""
from __future__ import annotations

import logging
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter

import taxonomy
from .base import BaseAdapter, normalize_date, split_documents

log = logging.getLogger(__name__)

END_POINT = os.environ.get(
    "WELFARE_CENTRAL_BASE_URL",
    "https://apis.data.go.kr/B554287/NationalWelfareInformationsV001",
).rstrip("/")
LIST_ENDPOINT = f"{END_POINT}/NationalWelfarelistV001"
DETAIL_ENDPOINT = f"{END_POINT}/NationalWelfaredetailedV001"

NUM_OF_ROWS = 500        # 포털 명시 최대치
MAX_PAGE_NO = 1000       # 포털 명시 최대치
TIMEOUT = 20

# 일일 트래픽 (개발계정 기준, 포털 표기값). 오퍼레이션별로 따로 센다.
DAILY_QUOTA = int(os.environ.get("WELFARE_CENTRAL_QUOTA", "100"))
# 목록 수집에 쓸 최대 호출 수. 나머지는 상세 조회 몫으로 남겨 둔다.
LIST_CALL_BUDGET = int(os.environ.get("WELFARE_CENTRAL_LIST_CALLS", "20"))

ID_FIELD = "servId"      # 실제 응답으로 확정 (예: WLF00000026)

# 목록 응답 — 실제 호출로 확정된 필드명.
#   servId servNm jurMnofNm jurOrgNm servDgst servDtlLink srvPvsnNm sprtCycNm
#   rprsCtadr onapPsbltYn lifeArray trgterIndvdlArray intrsThemaArray
#   inqNum svcfrstRegTs
# 목록에는 지원대상·지원내용·선정기준·신청방법이 없다. 요약(servDgst)뿐이다.
LIST_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "name":         ("servNm",),
    "org":          ("jurMnofNm",),          # 소관부처
    "dept":         ("jurOrgNm",),           # 소관부서
    "summary":      ("servDgst",),           # 한 줄 요약
    "official_url": ("servDtlLink",),        # 복지로 상세 페이지
    "provide_type": ("srvPvsnNm",),          # 제공유형 (현금대여(융자) 등)
    "cycle":        ("sprtCycNm",),          # 지원주기 (1회성/월 등)
    "contact":      ("rprsCtadr",),          # 대표문의
    "online_yn":    ("onapPsbltYn",),        # 온라인신청 가능여부
    "life":         ("lifeArray",),          # 생애주기 (청년,중장년,노년)
    "target_group": ("trgterIndvdlArray",),  # 가구유형 (장애인,저소득)
    "theme":        ("intrsThemaArray",),    # 관심주제 (생활지원,일자리,서민금융)
    "views":        ("inqNum",),             # 조회수 — 발행 우선순위 산정에 쓴다
    "registered":   ("svcfrstRegTs",),       # 서비스 최초등록일시
}

# 상세 응답 최상위 필드 — 실제 원문으로 확정.
#   servId servNm jurMnofNm tgtrDtlCn slctCritCn alwServCn crtrYr rprsCtadr
#   wlfareInfoOutlCn sprtCycNm srvPvsnNm lifeArray trgterIndvdlArray intrsThemaArray
# ⚠️ crtrYr 은 기준연도(2026)다. 서류 후보에 넣으면 '2026' 이 구비서류로 렌더된다.
DETAIL_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "target_raw":   ("tgtrDtlCn",),
    "criteria_raw": ("slctCritCn",),
    "benefit_raw":  ("alwServCn",),
    "how_to_raw":   (),                # applmetList 섹션에서만 온다
    "documents":    (),                # basfrmList 섹션에서만 온다
    "contact_raw":  ("rprsCtadr",),    # inqplCtadrList 섹션이 우선
    "law_raw":      (),                # baslawList 섹션에서만 온다
    "apply_url":    (),                # 상세에 온라인신청 URL 은 없다
    "period_raw":   (),                # 상세에 신청기한 필드는 없다
}


def _pick(row: dict, aliases: tuple[str, ...]) -> str:
    for name in aliases:
        value = row.get(name)
        if value and str(value).strip():
            return str(value).strip()
    return ""


class Adapter(BaseAdapter):
    source = "welfare-central"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("DATA_GO_KR_API_KEY", "")
        self._list_calls = 0
        self._detail_calls = 0

    # ── 목록 ──
    def fetch(self, limit: int | None = None) -> list:
        if not self.api_key:
            log.error("DATA_GO_KR_API_KEY 가 없습니다.")
            return []

        rows: list[dict] = []
        for page in range(1, min(LIST_CALL_BUDGET, MAX_PAGE_NO) + 1):
            page_rows, total = self._request_list(page)
            if page_rows is None:
                break
            rows.extend(page_rows)
            if page == 1 and total:
                log.info("중앙부처복지서비스: 전체 %s건 (목록 호출 예산 %d회)", total, LIST_CALL_BUDGET)
            if limit and len(rows) >= limit:
                rows = rows[:limit]
                break
            if len(page_rows) < NUM_OF_ROWS:
                break
        else:
            log.warning("목록 호출 예산(%d회)을 다 썼습니다. 남은 페이지는 다음 실행에서 받습니다.",
                        LIST_CALL_BUDGET)

        records = [r for r in (self._to_record(row) for row in rows) if r]
        log.info("중앙부처복지서비스 수집: %d건 (호출 %d회)", len(records), self._list_calls)
        return records

    # ── 상세 (발행 직전에만 호출) ──
    def enrich(self, record) -> None:
        """발행·갱신 대상에만 상세를 붙인다. 트래픽 100회 제약 때문이다.

        ⚠️ 여기서 `content_hash` 를 다시 계산하면 안 된다.
        동기화는 목록 응답만으로 해시를 만든다. 상세를 반영해 해시를 바꾸면
        다음 날 목록 기준 해시와 어긋나 **모든 제도가 매일 '변경됨'으로 잡힌다.**
        """
        if not self.api_key or record.source != self.source:
            return
        if self._detail_calls >= DAILY_QUOTA:
            log.warning("상세조회 일일 한도(%d회) 도달 — %s 는 목록 정보만으로 발행합니다.",
                        DAILY_QUOTA, record.id)
            return

        row = self._request_detail(record.source_id)
        if not row:
            return

        from .base import clean_text

        # 상세가 값을 주면 목록 값을 **덮어쓴다**. 목록의 `servDgst` 는 한 줄 요약이라
        # 지원 금액이 들어 있지 않다. 빈 칸만 채우는 방식으로 두면 요약이 자리를 차지해
        # 정작 중요한 '매월 최대 OO만 원' 이 페이지에 못 들어간다.
        # 상세 조회가 실패하면 목록 요약이 그대로 남아 최소한의 발행은 가능하다.
        # 섹션형 응답은 `parse_detail()` 이 이미 우리 필드명(target_raw 등)으로 담아 준다.
        # 명명 필드형이면 원천 태그명으로 들어온다. 둘 다 받도록 정규 키를 앞에 둔다.
        def take(key: str, current: str) -> str:
            value = clean_text(_pick(row, (key,) + DETAIL_FIELD_ALIASES[key]))
            return value or current

        record.target_raw = take("target_raw", record.target_raw)
        record.benefit_raw = take("benefit_raw", record.benefit_raw)
        record.criteria_raw = take("criteria_raw", record.criteria_raw)
        record.how_to_raw = take("how_to_raw", record.how_to_raw)

        record.contact_raw = take("contact_raw", record.contact_raw)
        record.law_raw = take("law_raw", record.law_raw)

        documents = split_documents(_pick(row, ("documents",) + DETAIL_FIELD_ALIASES["documents"]))
        if documents:
            record.documents_raw = documents

    # ── HTTP ──
    def _request_list(self, page: int) -> tuple[list[dict] | None, str]:
        params = {
            "serviceKey": self.api_key,
            "callTp": "L",
            "pageNo": page,
            "numOfRows": NUM_OF_ROWS,
            "srchKeyCode": "003",   # 제목+내용
        }
        text = self._get(LIST_ENDPOINT, params)
        self._list_calls += 1
        if text is None:
            return None, ""
        return parse_rows(text, ID_FIELD), total_count(text)

    def _request_detail(self, serv_id: str) -> dict | None:
        params = {"serviceKey": self.api_key, "callTp": "D", "servId": serv_id}
        text = self._get(DETAIL_ENDPOINT, params)
        self._detail_calls += 1
        if text is None:
            return None
        return parse_detail(text)

    def _get(self, endpoint: str, params: dict) -> str | None:
        url = f"{endpoint}?{urllib.parse.urlencode(params)}"
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
                raw = resp.read()
        except Exception as e:
            log.error("요청 실패 (%s): %s", endpoint.rsplit("/", 1)[-1], e)
            return None
        for encoding in ("utf-8", "euc-kr", "cp949"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")

    # ── 변환 ──
    def _to_record(self, row: dict):
        source_id = str(row.get(ID_FIELD) or "").strip()
        name = _pick(row, LIST_FIELD_ALIASES["name"])
        if not source_id or not name:
            return None

        theme = _pick(row, LIST_FIELD_ALIASES["theme"])
        life = _pick(row, LIST_FIELD_ALIASES["life"])
        target_group = _pick(row, LIST_FIELD_ALIASES["target_group"])

        # 원천이 직접 분류한 값을 우선한다. 본문 키워드 추정보다 정확하다.
        # 표에 없는 값이면 category=None 이 되고, build() 가 키워드 추정으로 넘어간다.
        category, audiences = taxonomy.map_bokjiro(theme, life, target_group)

        # 이 소스는 정의상 전부 중앙부처 사업이므로 지역 범위를 고정한다.
        # 덕분에 REGION_SCOPE=national 에서도 수집분이 그대로 발행 후보가 된다.
        return self.build(
            source_id,
            name,
            org=_pick(row, LIST_FIELD_ALIASES["org"]),
            # 목록에는 요약뿐이다. 지원대상·지원내용·선정기준·신청방법은 enrich() 가 채운다.
            benefit_raw=_pick(row, LIST_FIELD_ALIASES["summary"]),
            official_url=_pick(row, LIST_FIELD_ALIASES["official_url"]),
            always=True,   # 복지 사업은 대부분 상시. 상세에서 기한이 나오면 덮어쓴다.
            # 지원대상·선정기준이 상세조회에만 있다. 동기화 단계의 완결성 검사를
            # 유예하고 발행 직전 enrich() 뒤에 다시 검사한다.
            deferred_detail=True,
            region_scope=taxonomy.REGION_NATIONAL,
            category=category,
            audiences=audiences or None,   # 빈 리스트면 build() 가 키워드 추정
            # 복지로가 집계한 조회수. 보조금24의 '조회수' 와는 스케일이 다르므로
            # queueing 에서 소스별 백분위로 정규화한 뒤에야 비교한다.
            view_count=_pick(row, LIST_FIELD_ALIASES["views"]),
            source_registered=_pick(row, LIST_FIELD_ALIASES["registered"]),
            source_category_raw=" ".join(filter(None, [
                theme, life, target_group,
                _pick(row, LIST_FIELD_ALIASES["provide_type"]),
            ])),
        )


# ─────────────────────────────────────────────────────────────
#  XML 파싱 (모듈 함수 — 테스트하기 쉽게)
# ─────────────────────────────────────────────────────────────
def parse_rows(text: str, id_field: str) -> list[dict]:
    """XML 응답에서 레코드 요소를 뽑는다.

    래퍼 태그명(wantedList / servList 등)을 하드코딩하지 않는다. 활용가이드로
    확정되지 않은 이름에 의존하면 응답 구조가 조금만 달라도 전부 실패한다.
    대신 **id_field 를 자식으로 가진 요소**를 레코드로 본다. 그것이 없으면
    '손자 없는 요소 중 가장 많이 반복되는 태그'로 넘어간다.
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        log.error("XML 파싱 실패: %s · 응답 앞부분: %s", e, text[:200].replace("\n", " "))
        return []

    by_id = [el for el in root.iter() if el.find(id_field) is not None]
    if by_id:
        return [{child.tag: (child.text or "").strip() for child in el} for el in by_id]

    leaves = [el for el in root.iter() if len(el) >= 2 and all(len(c) == 0 for c in el)]
    if not leaves:
        return []
    common = Counter(el.tag for el in leaves).most_common(1)[0][0]
    return [
        {child.tag: (child.text or "").strip() for child in el}
        for el in leaves if el.tag == common
    ]


def total_count(text: str) -> str:
    import re

    match = re.search(r"<totalCount>\s*(\d+)\s*</totalCount>", text)
    return match.group(1) if match else ""


# 상세 응답은 하이브리드다 — 실제 원문으로 확정:
#   최상위 명명 필드   servId servNm jurMnofNm tgtrDtlCn slctCritCn alwServCn
#                     crtrYr rprsCtadr wlfareInfoOutlCn sprtCycNm srvPvsnNm …
#   반복 섹션 4종      각각 (servSeCode, servSeDetailNm, servSeDetailLink)
#
# 섹션 태그명 → 우리 필드. 확정됐으므로 휴리스틱 대신 명시적으로 매핑한다.
DETAIL_SECTION_LISTS: dict[str, str] = {
    "applmetList":    "how_to_raw",   # 신청·조사·결정·지급·사후관리 단계
    "inqplCtadrList": "contact_raw",  # 문의처 (기관명 + 연락처)
    "basfrmList":     "documents",    # 서식·안내 자료 (이름 + 다운로드 URL)
    "baslawList":     "law_raw",      # 근거 법령 (이름만, Link 없음)
}

# 섹션 이름 꼬리표 정리 — '신청기관연락처목록' → '신청기관'
_SECTION_NAME_TAIL = ("연락처목록", "기관목록", "목록")


def parse_detail(text: str) -> dict | None:
    """상세 응답을 하나의 평평한 dict 로.

    최상위 명명 필드를 그대로 담고, 반복 섹션은 태그별로 묶어 우리 필드에 넣는다.
    섹션은 `servSeDetailNm`(이름)과 `servSeDetailLink`(내용)의 쌍이며, 태그마다
    의미가 다르다 — 신청 절차는 단계 설명이고, 서식은 파일명+URL 이다.
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        log.error("상세 XML 파싱 실패: %s · 응답 앞부분: %s", e, text[:200].replace("\n", " "))
        return None

    # ── 최상위 명명 필드 ──
    merged: dict[str, str] = {
        child.tag: (child.text or "").strip()
        for child in root if len(child) == 0 and (child.text or "").strip()
    }

    # ── 반복 섹션 ──
    buckets: dict[str, list[str]] = {}
    for el in root:
        dest = DETAIL_SECTION_LISTS.get(el.tag)
        if not dest or len(el) == 0:
            continue
        fields = {c.tag: (c.text or "").strip() for c in el}
        name = fields.get("servSeDetailNm", "").strip()
        body = fields.get("servSeDetailLink", "").strip()
        line = _section_line(dest, name, body)
        if line:
            buckets.setdefault(dest, []).append(line)

    for dest, lines in buckets.items():
        # 같은 값이 반복되는 경우가 있어 순서를 지키며 중복만 제거한다
        merged[dest] = "\n".join(dict.fromkeys(lines))

    return merged or None


def _section_line(dest: str, name: str, body: str) -> str:
    """섹션 한 줄을 사람이 읽을 형태로. 원문 문구 자체는 손대지 않는다."""
    name = name.strip()
    for tail in _SECTION_NAME_TAIL:
        if name.endswith(tail) and len(name) > len(tail):
            name = name[: -len(tail)].strip()
            break

    if dest == "documents":
        # 서식은 이름이 곧 파일명이다. URL 은 페이지에 노출하지 않는다
        # (다운로드 링크가 만료되는 경우가 있어 공식 창구로 유도하는 편이 안전하다).
        return name or body
    if not name:
        return body
    if not body or body == name:
        return name
    return f"{name} — {body}"
