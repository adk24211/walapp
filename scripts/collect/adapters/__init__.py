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
#
# 보조금24(15113968) 하나로 시작한다. 이 API 가 중앙부처·지자체·공공기관·교육청
# 수혜서비스를 모두 담고 `소관기관유형` 으로 구분해 주기 때문에, 중앙부처 우선
# 단계에서는 이것만으로 충분하다. (REGION_SCOPE 가 범위를 거른다)
#
# 복지로 기반 중앙부처복지서비스(15090532)는 보조금24와 겹치는 사업이 많아
# 유사도 검토 대기열을 키운다. 필요할 때만 ENABLE_WELFARE_CENTRAL=1 로 켠다.
REAL_ADAPTERS = {
    "bojo24": "collect.adapters.bojo24",
}

# 선택 어댑터 — 환경변수로 켠다.
OPTIONAL_ADAPTERS = {
    "welfare-central": ("collect.adapters.welfare_central", "ENABLE_WELFARE_CENTRAL"),
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


# source 이름 → 이번 실행의 어댑터 인스턴스.
# publish 단계가 enrich() 를 부르려면 어댑터에 다시 닿아야 한다.
_ACTIVE: dict[str, object] = {}


def get(source: str):
    """활성 어댑터 조회. 없으면 None."""
    return _ACTIVE.get(source)


def load_adapters(mock: bool | None = None) -> list:
    """활성 어댑터 인스턴스 목록."""
    from importlib import import_module

    mock = use_mock() if mock is None else mock
    table = dict(MOCK_ADAPTERS if mock else REAL_ADAPTERS)

    if not mock:
        for name, (module_path, flag) in OPTIONAL_ADAPTERS.items():
            if os.environ.get(flag) == "1":
                table[name] = module_path

    adapters = []
    _ACTIVE.clear()
    for name, module_path in table.items():
        try:
            instance = import_module(module_path).Adapter()
        except Exception as e:
            log.error("어댑터 로드 실패 [%s]: %s", name, e)
            continue
        adapters.append(instance)
        _ACTIVE[getattr(instance, "source", name)] = instance
    return adapters
