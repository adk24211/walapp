"""한국사회보장정보원 중앙부처복지서비스 어댑터 (복지로 기반).

⚠️ 미완성 — 활용신청 승인 후 채워야 한다. `bojo24.py` 와 같은 상태다.

공공데이터포털 데이터셋: `15090532`
  https://www.data.go.kr/data/15090532/openapi.do

중앙부처 우선 방침(REDESIGN.md §11)에 따라 단계 0에서 신청할 API 는 이것과
보조금24(`15113968`) 둘이다. 지자체복지서비스(`15108347`)와 온통청년(`15143273`)은
범위를 넓힐 때 추가한다.

이 소스는 정의상 전부 중앙부처 사업이므로 지역 범위를 `national` 로 고정한다.
그래서 `REGION_SCOPE=national` 상태에서도 수집분이 그대로 발행 후보가 된다.

확정해야 할 것:
  1. `ID_FIELD` — 서비스 고유 ID. 보조금24 와 ID 체계가 다르므로 `source` 접두사
     (`welfare-central-`)로 네임스페이스가 갈린다. 같은 사업이 두 소스에 모두
     있으면 유사도 3계층이 잡아 `_data/review_needed.json` 으로 보낸다.
  2. `FIELD_MAP` — 목록조회와 상세조회의 필드명이 다를 수 있다. 상세조회까지
     호출해야 지원대상·선정기준이 채워지는지 활용가이드로 확인할 것.
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

LIST_ENDPOINT = "https://api.odcloud.kr/api/gov24/v3/serviceList"  # ⚠️ 확정 필요
PER_PAGE = 100
TIMEOUT = 15

# ─────────────────────────────────────────────────────────────
#  ⚠️ 확정 필요 — 아래는 전부 추정값이다
# ─────────────────────────────────────────────────────────────
ID_FIELD = "서비스ID"

FIELD_MAP = {
    "서비스명":       "name",
    "소관부처명":     "org",
    "지원대상":       "target_raw",
    "지원내용":       "benefit_raw",
    "선정기준":       "criteria_raw",
    "신청방법":       "how_to_raw",
    "구비서류":       "documents_raw",
    "신청기한":       "apply_period_raw",
    "서비스목적요약": "summary_raw",
    "상세조회URL":    "official_url",
    "온라인신청URL":  "apply_url",
    "서비스분야":     "source_category_raw",
}

ALWAYS_TOKENS = ("상시", "연중", "수시", "제한없음", "제한 없음")


class Adapter(BaseAdapter):
    source = "welfare-central"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("DATA_GO_KR_API_KEY", "")

    def fetch(self, limit: int | None = None) -> list:
        if not self.api_key:
            log.error("DATA_GO_KR_API_KEY 가 없습니다.")
            return []

        records, page = [], 1
        while True:
            rows = self._request(page)
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

    def _request(self, page: int) -> list[dict]:
        query = urllib.parse.urlencode({
            "page": page, "perPage": PER_PAGE, "serviceKey": self.api_key,
        })
        try:
            with urllib.request.urlopen(f"{LIST_ENDPOINT}?{query}", timeout=TIMEOUT) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            log.error("중앙부처복지서비스 요청 실패 (page=%s): %s", page, e)
            return []
        return payload.get("data") or []

    def _to_record(self, row: dict):
        source_id = str(row.get(ID_FIELD) or "").strip()
        name = str(row.get("서비스명") or "").strip()
        if not source_id or not name:
            return None

        mapped = {dest: row.get(src, "") for src, dest in FIELD_MAP.items()}
        period_raw = str(mapped.get("apply_period_raw") or "")
        always = any(token in period_raw for token in ALWAYS_TOKENS)

        parts = [p for p in period_raw.replace("〜", "~").split("~") if p.strip()]
        start = normalize_date(parts[0]) if len(parts) >= 2 else ""
        end = normalize_date(parts[1]) if len(parts) >= 2 else normalize_date(period_raw)

        return self.build(
            source_id,
            name,
            org=str(mapped.get("org") or ""),
            target_raw=str(mapped.get("target_raw") or ""),
            benefit_raw=str(mapped.get("benefit_raw") or ""),
            criteria_raw=str(mapped.get("criteria_raw") or ""),
            how_to_raw=str(mapped.get("how_to_raw") or ""),
            documents_raw=split_documents(mapped.get("documents_raw", "")),
            apply_start=start,
            apply_end=end,
            always=always,
            apply_url=str(mapped.get("apply_url") or ""),
            official_url=str(mapped.get("official_url") or ""),
            # 중앙부처 사업만 담긴 소스라 지역 범위를 고정한다.
            region_scope=taxonomy.REGION_NATIONAL,
            source_category_raw=str(mapped.get("source_category_raw") or ""),
        )
