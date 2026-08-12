"""원천 API → 표준 스키마 어댑터.

어댑터 계층이 존재하는 이유:
공공데이터포털 API의 실제 응답 필드명은 활용신청 승인 후 발급되는 활용가이드로만
확정할 수 있다(REDESIGN.md §3.2). 어댑터가 그 차이를 전부 흡수하므로,
필드명이 무엇으로 밝혀지든 이 디렉터리 안에서만 고치면 된다.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

# 어댑터 이름 → 모듈 경로
REAL_ADAPTERS = {
    "bojo24": "collect.adapters.bojo24",
}
MOCK_ADAPTERS = {
    "mock": "collect.adapters.mock",
}


def use_mock() -> bool:
    """목 데이터 모드 여부. 실 API 키가 없으면 자동으로 목 모드가 된다."""
    if os.environ.get("MOCK_DATA") == "1":
        return True
    if os.environ.get("MOCK_DATA") == "0":
        return False
    return not os.environ.get("DATA_GO_KR_API_KEY")


def load_adapters(mock: bool | None = None) -> list:
    """활성 어댑터 인스턴스 목록."""
    from importlib import import_module

    mock = use_mock() if mock is None else mock
    table = MOCK_ADAPTERS if mock else REAL_ADAPTERS

    adapters = []
    for name, module_path in table.items():
        try:
            adapters.append(import_module(module_path).Adapter())
        except Exception as e:
            log.error("어댑터 로드 실패 [%s]: %s", name, e)
    return adapters
