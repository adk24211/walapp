"""보조금24 어댑터 — 행정안전부 대한민국 공공서비스(혜택) 정보.

공공데이터포털 데이터셋: `15113968` (자동승인)
Base URL: `https://api.odcloud.kr/api`
활용가이드: https://infuser.odcloud.kr/api/stages/44436/api-docs

필드명은 활용가이드로 **확정**했다. 더 이상 추정값이 아니다.

세 오퍼레이션을 쓴다:

    GET /gov24/v3/serviceList        목록 — 지원대상·지원내용·선정기준·신청방법·신청기한
    GET /gov24/v3/serviceDetail      상세 — 구비서류·온라인신청URL·문의처·법령
    GET /gov24/v3/supportConditions  지원조건 — JA* 코드 (원문 보관만, §지원조건 참고)

serviceDetail 은 `cond[서비스ID::EQ]` 로 한 건씩 조회할 수도 있지만, 조건 없이
페이지네이션하면 전체가 나온다. 제도 수천 건을 한 건씩 호출하면 트래픽을 다 쓰므로
**목록과 상세를 각각 통째로 받아 서비스ID 로 합친다.**
"""
from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request

import taxonomy
from .base import BaseAdapter, normalize_date, split_documents

log = logging.getLogger(__name__)

# BOJO24_BASE_URL 로 갈아끼울 수 있게 둔다. 로컬 복제 서버로 파이프라인 전체를
# 돌려 보거나, 향후 엔드포인트가 바뀔 때 코드 수정 없이 대응하기 위한 것이다.
BASE_URL = os.environ.get("BOJO24_BASE_URL", "https://api.odcloud.kr/api/gov24/v3").rstrip("/")
LIST_ENDPOINT = f"{BASE_URL}/serviceList"
DETAIL_ENDPOINT = f"{BASE_URL}/serviceDetail"
CONDITIONS_ENDPOINT = f"{BASE_URL}/supportConditions"

PER_PAGE = 100
TIMEOUT = 20
MAX_PAGES = 200          # 폭주 방지 (PER_PAGE 100 기준 2만 건)

# ─────────────────────────────────────────────────────────────
#  확정된 응답 필드 (활용가이드 기준)
# ─────────────────────────────────────────────────────────────
ID_FIELD = "서비스ID"

# serviceList 응답 필드
#   서비스ID, 지원유형, 서비스명, 서비스목적요약, 지원대상, 선정기준, 지원내용,
#   신청방법, 신청기한, 상세조회URL, 소관기관코드, 소관기관명, 부서명, 조회수,
#   소관기관유형, 사용자구분, 서비스분야, 접수기관, 전화문의, 등록일시, 수정일시
LIST_FIELD_MAP = {
    "서비스명":      "name",
    "소관기관명":    "org",
    "지원대상":      "target_raw",
    "지원내용":      "benefit_raw",
    "선정기준":      "criteria_raw",
    "신청방법":      "how_to_raw",
    "신청기한":      "apply_period_raw",
    "상세조회URL":   "official_url",
    "서비스분야":    "source_category_raw",
    "전화문의":      "contact_raw",
    "접수기관":      "receiver_raw",
}

# serviceDetail 응답 필드 (목록에 없는 것만 취한다)
#   서비스ID, 지원유형, 서비스명, 서비스목적, 신청기한, 지원대상, 선정기준, 지원내용,
#   신청방법, 구비서류, 접수기관명, 문의처, 온라인신청사이트URL, 수정일시, 소관기관명,
#   행정규칙, 자치법규, 법령, 공무원확인구비서류, 본인확인필요구비서류
DETAIL_FIELD_MAP = {
    "구비서류":            "documents_raw",
    "온라인신청사이트URL":  "apply_url",
    "공무원확인구비서류":    "documents_official_raw",
    "본인확인필요구비서류":  "documents_self_raw",
}

# 신청기한 원문 중 '상시'로 볼 표현
ALWAYS_TOKENS = ("상시", "연중", "수시", "제한없음", "제한 없음", "자격 취득", "해당시")

# ─────────────────────────────────────────────────────────────
#  지원조건(supportConditions) — JA* 코드
# ─────────────────────────────────────────────────────────────
# 응답이 `JA0101`, `JA0201` 같은 코드 컬럼으로만 오고, 활용가이드에 코드표가
# 붙어 있지 않다. 뜻을 추측해서 대상 분류에 쓰면 틀린 자격 요건을 페이지에
# 싣게 되므로 **의미를 부여하지 않고 원문 그대로만 보관**한다.
#
# 코드표를 확인한 뒤에 아래를 채우고 `_apply_conditions()` 를 살리면 된다.
#   예) JA0110/JA0111 은 정수형이라 연령 하한/상한으로 보이지만, 확인 전에는 쓰지 않는다.
#
# 확인 방법: 지원조건을 받아 온 뒤 같은 서비스ID 의 '지원대상' 원문과 대조한다.
#   python3 scripts/inspect_api.py --probe \
#     "https://api.odcloud.kr/api/gov24/v3/supportConditions" --key "키" --rows 20
CONDITION_CODE_LABELS: dict[str, str] = {}


class Adapter(BaseAdapter):
    source = "bojo24"

    def __init__(self, api_key: str | None = None, since: str | None = None):
        self.api_key = api_key or os.environ.get("DATA_GO_KR_API_KEY", "")
        # 증분 동기화 — 이 날짜 이후 수정된 제도만 받는다 (YYYY-MM-DD)
        self.since = since or os.environ.get("SYNC_SINCE", "")

    # ── 공개 API ──
    def fetch(self, limit: int | None = None) -> list:
        if not self.api_key:
            log.error("DATA_GO_KR_API_KEY 가 없습니다. 목 어댑터를 쓰거나 키를 설정하세요.")
            return []

        conditions = {}
        if self.since:
            # 수정일시는 14자리 YYYYMMDDHHMMSS 다 (예: 20260129201825).
            # SYNC_SINCE 를 YYYY-MM-DD 로 받아 그대로 비교하면 문자열 비교가 어긋난다.
            since = self.since.replace("-", "").replace("/", "")[:8]
            if len(since) == 8:
                conditions["cond[수정일시::GTE]"] = since + "000000"
                log.info("증분 동기화: %s 이후 수정분만", self.since)
            else:
                log.warning("SYNC_SINCE 형식이 YYYY-MM-DD 가 아닙니다(%s) — 전체 동기화합니다.",
                            self.since)

        rows = self._fetch_all(LIST_ENDPOINT, "목록", conditions, limit)
        if not rows:
            return []

        # 상세는 서비스ID 로 합친다. 실패해도 목록만으로 발행할 수 있다.
        details = self._fetch_details(rows, limit)

        records = []
        for row in rows:
            record = self._to_record(row, details.get(str(row.get(ID_FIELD) or "").strip()))
            if record:
                records.append(record)
        log.info("보조금24 수집 완료: %d건", len(records))
        return records

    # ── 내부 ──
    def _fetch_all(
        self,
        endpoint: str,
        label: str,
        conditions: dict | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """페이지네이션을 끝까지 돌며 data 배열을 모은다."""
        collected: list[dict] = []
        for page in range(1, MAX_PAGES + 1):
            payload = self._request(endpoint, page, conditions)
            if payload is None:
                break
            rows = payload.get("data") or []
            collected.extend(rows)

            if page == 1:
                log.info("%s: 전체 %s건", label, payload.get("totalCount", "?"))
            if limit and len(collected) >= limit:
                return collected[:limit]
            if len(rows) < PER_PAGE:
                break
        else:
            log.warning("%s: 최대 페이지(%d)에 도달해 중단했습니다.", label, MAX_PAGES)
        return collected

    def _fetch_details(self, rows: list[dict], limit: int | None) -> dict[str, dict]:
        """상세를 통째로 받아 서비스ID → 상세 dict 로."""
        try:
            detail_rows = self._fetch_all(DETAIL_ENDPOINT, "상세", None, limit)
        except Exception as e:
            log.warning("상세 조회 실패, 목록만으로 진행합니다: %s", e)
            return {}

        details = {}
        for row in detail_rows:
            key = str(row.get(ID_FIELD) or "").strip()
            if key:
                details[key] = row
        log.info("상세 매칭: 목록 %d건 중 %d건", len(rows), sum(
            1 for r in rows if str(r.get(ID_FIELD) or "").strip() in details
        ))
        return details

    def _request(self, endpoint: str, page: int, conditions: dict | None = None) -> dict | None:
        params = {"page": page, "perPage": PER_PAGE, "serviceKey": self.api_key}
        if conditions:
            params.update(conditions)
        url = f"{endpoint}?{urllib.parse.urlencode(params)}"
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 401:
                log.error("인증 실패(401). Encoding/Decoding 키를 바꿔 시도해 보세요.")
            else:
                log.error("요청 실패 (%s page=%s): HTTP %s", endpoint, page, e.code)
            return None
        except Exception as e:
            log.error("요청 실패 (%s page=%s): %s", endpoint, page, e)
            return None

    def _to_record(self, row: dict, detail: dict | None):
        source_id = str(row.get(ID_FIELD) or "").strip()
        name = str(row.get("서비스명") or "").strip()
        if not source_id or not name:
            return None

        mapped = {dest: row.get(src, "") for src, dest in LIST_FIELD_MAP.items()}
        if detail:
            for src, dest in DETAIL_FIELD_MAP.items():
                mapped.setdefault(dest, "")
                if detail.get(src):
                    mapped[dest] = detail[src]

        # 구비서류: 본 서류가 비면 본인확인/공무원확인 서류로 대체
        documents = split_documents(mapped.get("documents_raw", ""))
        if not documents:
            documents = split_documents(mapped.get("documents_self_raw", ""))
        if not documents:
            documents = split_documents(mapped.get("documents_official_raw", ""))

        period_raw = str(mapped.get("apply_period_raw") or "")
        always = any(token in period_raw for token in ALWAYS_TOKENS)
        start, end = parse_period(period_raw)

        scope, sido, sigungu = parse_region(
            str(row.get("소관기관유형") or ""), str(mapped.get("org") or "")
        )

        return self.build(
            source_id,
            name,
            org=str(mapped.get("org") or ""),
            target_raw=str(mapped.get("target_raw") or ""),
            benefit_raw=str(mapped.get("benefit_raw") or ""),
            criteria_raw=str(mapped.get("criteria_raw") or ""),
            how_to_raw=str(mapped.get("how_to_raw") or ""),
            documents_raw=documents,
            apply_start=start,
            apply_end=end,
            always=always,
            apply_url=str(mapped.get("apply_url") or ""),
            official_url=str(mapped.get("official_url") or ""),
            region_scope=scope,
            sido=sido,
            sigungu=sigungu,
            # 서비스분야(예: '보건의료', '주거·자치') + 지원유형(예: '현금', '이용권')을
            # 함께 넘겨 자체 분류 정확도를 높인다.
            contact_raw=str(mapped.get("contact_raw") or ""),
            receiver_raw=str(mapped.get("receiver_raw") or ""),
            source_category_raw=" ".join(filter(None, [
                str(mapped.get("source_category_raw") or ""),
                str(row.get("지원유형") or ""),
                str(row.get("사용자구분") or ""),
            ])),
        )


# ─────────────────────────────────────────────────────────────
#  파싱 헬퍼 (테스트하기 쉽도록 모듈 함수로 뺀다)
# ─────────────────────────────────────────────────────────────
def parse_period(text: str) -> tuple[str, str]:
    """신청기한 원문에서 시작·종료를 뽑는다.

    실제 값이 '2026-03-02 ~ 2027-02-26' 처럼 깔끔한 경우도 있지만
    '접수기관별 상이', '예산 소진 시까지' 같은 자유 서술도 섞여 온다.
    날짜를 못 찾으면 빈 문자열을 돌려주고, 상시 여부는 호출부가 따로 판정한다.
    """
    if not text:
        return "", ""
    normalized = text.replace("〜", "~").replace("～", "~").replace("∼", "~")
    parts = [p for p in normalized.split("~") if p.strip()]
    if len(parts) >= 2:
        return normalize_date(parts[0]), normalize_date(parts[1])
    # 구분자가 없으면 단일 날짜를 마감일로 본다
    return "", normalize_date(normalized)


# 소관기관유형 값에 따른 지역 범위 판정.
# 알 수 없는 값이 와도 소관기관명 파싱으로 넘어가므로 안전하다.
CENTRAL_TYPE_TOKENS = ("중앙", "국가")
LOCAL_TYPE_TOKENS = ("지자체", "지방", "시도", "시군구", "교육청")


def parse_region(org_type: str, org_name: str) -> tuple[str, str | None, str | None]:
    """소관기관유형 + 소관기관명에서 지역 범위를 판정.

    유형이 '중앙행정기관' 이면 전국으로 확정한다. 그 외에는 기관명에서 시도를
    찾아보고, 못 찾으면 전국으로 둔다(중앙 산하 공공기관이 여기 해당한다).
    """
    if any(token in org_type for token in CENTRAL_TYPE_TOKENS):
        return taxonomy.REGION_NATIONAL, None, None

    key = taxonomy.sido_key(org_name)
    if not key:
        return taxonomy.REGION_NATIONAL, None, None

    for token in org_name.split()[1:]:
        if token.endswith(("시", "군", "구")) and len(token) >= 2:
            return "sigungu", key, token
    return "sido", key, None
