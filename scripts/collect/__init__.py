"""수집 패키지.

지원금·제도 도감 전환 이후 수집은 `collect.adapters` 가 담당한다.
구 RSS 수집기(korea_policy·curious)는 제거됐다 — 최신순 RSS 선택이
중복의 직접 원인이었다. (REDESIGN.md §1.2)

여기서 하위 모듈을 미리 import 하지 않는다. 목 모드는 표준 라이브러리만으로
돌아가야 하므로, requests·feedparser 가 없는 환경에서도 패키지 import 가
실패하지 않아야 한다.
"""
