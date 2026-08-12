"""보조금24(행정안전부 대한민국 공공서비스 정보) 어댑터.

⚠️ 미완성 — 활용신청 승인 후 채워야 한다. (REDESIGN.md §3.2 / 로드맵 단계 0)

공공데이터포털 데이터셋: `15113968`
  https://www.data.go.kr/data/15113968/openapi.do

지금 상태로는 `FIELD_MAP` 의 원천 필드명이 **추정값**이다.
활용신청이 승인되면 발급되는 활용가이드 문서를 열고 아래 두 가지를 확정할 것:

  1. `FIELD_MAP` 의 좌변(원천 응답 필드명)을 실제 값으로 교체
  2. `ID_FIELD` — 서비스 고유 ID 필드명. **이것이 전체 설계의 primary key** 이므로
     가장 먼저, 가장 정확하게 확인해야 한다. 이 값이 흔들리면 같은 제도가
     매일 새 페이지로 발행된다.

확정 전까지는 `MOCK_DATA=1`(또는 API 키 미설정) 상태로 목 어댑터가 동작한다.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request

import taxonomy
from .base import BaseAdapter, split_documents

log = logging.getLogger(__name__)

BASE_URL = "https://api.odcloud.kr/api/gov24/v3"
LIST_ENDPOINT = f"{BASE_URL}/serviceList"
DETAIL_ENDPOINT = f"{BASE_URL}/serviceDetail"

PER_PAGE = 100
TIMEOUT = 15

# ─────────────────────────────────────────────────────────────
#  ⚠️ 확정 필요 — 아래는 전부 추정값이다
# ─────────────────────────────────────────────────────────────
ID_FIELD = "서비스ID"

FIELD_MAP = {
    # 원천 응답 필드명        →  ProgramRecord 필드
    "서비스명":               "name",
    "소관기관명":             "org",
    "지원대상":               "target_raw",
    "지원내용":               "benefit_raw",
    "선정기준":               "criteria_raw",
    "신청방법":               "how_to_raw",
    "구비서류":               "documents_raw",
    "신청기한":               "apply_period_raw",
    "상세조회URL":            "official_url",
    "온라인신청사이트URL":     "apply_url",
    "서비스분야":             "source_category_raw",
    "부서명":                 "department_raw",
}

# 신청기한 원문 중 '상시' 로 간주할 표현
ALWAYS_TOKENS = ("상시", "연중", "수시", "제한없음", "제한 없음")


class Adapter(BaseAdapter):
    source = "bojo24"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("DATA_GO_KR_API_KEY", "")

    # ── 공개 API ──
    def fetch(self, limit: int | None = None) -> list:
        if not self.api_key:
            log.error("DATA_GO_KR_API_KEY 가 없습니다. 목 어댑터를 쓰거나 키를 설정하세요.")
            return []

        records, page = [], 1
        while True:
            rows = self._request(LIST_ENDPOINT, page)
            if not rows:
                break
            for row in rows:
                record = self._to_record(row)
                if record:
                    records.append(record)
                if limit and len(records) >= limit:
                    return records
            if len(rows) < PER_PAGE:
                break
            page += 1
        return records

    # ── 내부 ──
    def _request(self, endpoint: str, page: int) -> list[dict]:
        query = urllib.parse.urlencode({
            "page": page,
            "perPage": PER_PAGE,
            "serviceKey": self.api_key,
        })
        try:
            with urllib.request.urlopen(f"{endpoint}?{query}", timeout=TIMEOUT) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            log.error("보조금24 요청 실패 (page=%s): %s", page, e)
            return []
        return payload.get("data") or []

    def _to_record(self, row: dict):
        source_id = str(row.get(ID_FIELD) or "").strip()
        name = str(row.get("서비스명") or "").strip()
        if not source_id or not name:
            return None

        mapped: dict = {}
        for src_field, dest in FIELD_MAP.items():
            mapped[dest] = row.get(src_field, "")

        period_raw = str(mapped.get("apply_period_raw") or "")
        always = any(token in period_raw for token in ALWAYS_TOKENS)
        start, end = _parse_period(period_raw)

        scope, sido, sigungu = _parse_region(str(mapped.get("org") or ""))

        return self.build(
            source_id,
            name,
            org=mapped.get("org", ""),
            target_raw=mapped.get("target_raw", ""),
            benefit_raw=mapped.get("benefit_raw", ""),
            criteria_raw=mapped.get("criteria_raw", ""),
            how_to_raw=mapped.get("how_to_raw", ""),
            documents_raw=split_documents(mapped.get("documents_raw", "")),
            apply_start=start,
            apply_end=end,
            always=always,
            apply_url=str(mapped.get("apply_url") or ""),
            official_url=str(mapped.get("official_url") or ""),
            region_scope=scope,
            sido=sido,
            sigungu=sigungu,
            source_category_raw=str(mapped.get("source_category_raw") or ""),
        )


def _parse_period(text: str) -> tuple[str, str]:
    """'2026-03-02 ~ 2027-02-26' 형태에서 시작·종료를 뽑는다."""
    from .base import normalize_date

    if not text:
        return "", ""
    parts = [p for p in text.replace("〜", "~").split("~") if p.strip()]
    if len(parts) >= 2:
        return normalize_date(parts[0]), normalize_date(parts[1])
    return "", normalize_date(text)


def _parse_region(org: str) -> tuple[str, str | None, str | None]:
    """소관기관명에서 지역 범위를 추정.

    중앙부처면 전국, '경기도 성남시' 처럼 시군구까지 나오면 sigungu 로 잡는다.
    """
    if not org:
        return taxonomy.REGION_NATIONAL, None, None

    key = taxonomy.sido_key(org)
    if not key:
        return taxonomy.REGION_NATIONAL, None, None

    tokens = org.split()
    for token in tokens[1:]:
        if token.endswith(("시", "군", "구")) and len(token) >= 2:
            return "sigungu", key, token
    return "sido", key, None
