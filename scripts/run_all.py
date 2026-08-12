"""지원금 도감 파이프라인 진입점.

    ① 동기화   원천 API 목록 → 원장 대조 → 신규/변경/동일/격리 분류
    ② 큐 산출   신규 후보에 우선순위 점수 부여
    ③ 발행      큐 상위 N건을 해설 생성 → 검증 → 페이지 작성
    ④ 갱신      내용이 바뀐 제도 상위 M건을 다시 렌더
    ⑤ 인덱스    분류 데이터를 Jekyll 로 내보냄

구 파이프라인(매일 4개 강제 발행)과의 차이:
  · 소재를 RSS 최신순이 아니라 큐에서 꺼낸다
  · 큐가 비면 아무것도 발행하지 않는다 — 억지 생성이 중복의 직접 원인이었다
  · 같은 제도의 재등장은 새 글이 아니라 갱신으로 흡수된다

환경변수:
    GROQ_API_KEY         해설 생성용. 없으면 오프라인 폴백으로 동작한다.
    DATA_GO_KR_API_KEY   공공데이터포털 키. 없으면 목 데이터로 동작한다.
    MOCK_DATA            "1" 강제 목 모드 / "0" 강제 실 API 모드
    POST_DATE            기준 날짜 override (YYYY-MM-DD)
    PUBLISH_LIMIT        하루 신규 발행 상한 (기본 5)
    REFRESH_LIMIT        하루 갱신 상한 (기본 10)
    REGION_SCOPE         발행 범위 (기본 "national" — 중앙부처 우선)
                         지자체까지 넓히려면 "national,sido,sigungu"
    DRY_RUN              "1" 이면 파일을 쓰지 않는다
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("run_all")

DEFAULT_PUBLISH_LIMIT = 5
DEFAULT_REFRESH_LIMIT = 10


def _load_dotenv() -> None:
    """python-dotenv 가 없어도 동작하도록 최소 구현."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _groq_client():
    """Groq 클라이언트. 키가 없거나 패키지가 없으면 None (오프라인 폴백)."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        log.warning("GROQ_API_KEY 없음 → 오프라인 해설 생성으로 진행합니다.")
        return None
    try:
        from groq import Groq
    except ImportError:
        log.warning("groq 패키지 없음 → 오프라인 해설 생성으로 진행합니다.")
        return None
    return Groq(api_key=api_key)


def _export_taxonomy() -> None:
    """Liquid 템플릿이 쓰는 `_data/taxonomy.json` 갱신."""
    import taxonomy

    path = ROOT / "_data" / "taxonomy.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(taxonomy.export_for_jekyll(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    log.info("분류 데이터 내보내기: %s", path.name)


def main() -> int:
    _load_dotenv()

    import publish
    import queueing
    import registry
    import sync
    from collect import adapters

    date_override = os.environ.get("POST_DATE")
    today: date = (
        datetime.strptime(date_override, "%Y-%m-%d").date()
        if date_override
        else datetime.now(ZoneInfo("Asia/Seoul")).date()
    )
    dry_run = os.environ.get("DRY_RUN") == "1"
    publish_limit = int(os.environ.get("PUBLISH_LIMIT", DEFAULT_PUBLISH_LIMIT))
    refresh_limit = int(os.environ.get("REFRESH_LIMIT", DEFAULT_REFRESH_LIMIT))
    scopes = tuple(
        s.strip() for s in
        os.environ.get("REGION_SCOPE", ",".join(sync.DEFAULT_SCOPES)).split(",")
        if s.strip()
    )
    mock = adapters.use_mock()

    log.info("━━━ 지원금 도감 파이프라인 ━━━")
    log.info("날짜 %s · 데이터 %s · DRY_RUN %s · 발행상한 %d · 갱신상한 %d",
             today, "목(mock)" if mock else "실 API", dry_run, publish_limit, refresh_limit)
    log.info("발행 범위: %s", " + ".join(scopes))
    if mock:
        log.warning("목 데이터 모드입니다. 생성된 페이지는 noindex 처리되며 커밋되지 않습니다.")

    reg = registry.Registry()
    log.info("원장 로드: 기발행 %d건", len(reg))

    # ── ① 동기화 ──
    result = sync.run(reg, today, mock=mock, scopes=scopes)
    if result.out_of_scope:
        log.info("범위 밖으로 건너뛴 제도 %d건 — REGION_SCOPE 를 넓히면 그날 신규로 잡힙니다.",
                 result.out_of_scope)
    if result.total == 0:
        log.error("수집 결과가 비었습니다. 중단합니다.")
        return 1

    registry.save_incomplete(result.incomplete)
    registry.save_review_needed(result.review_needed)

    # ── ② 큐 산출 ──
    queue_payload = queueing.build(result.new, today)
    if not dry_run:
        registry.save_queue(queue_payload)

    by_id = {r.id: r for r in result.new}
    to_publish = queueing.take(queue_payload, by_id, publish_limit)
    to_refresh = result.changed[:refresh_limit]

    if not to_publish and not to_refresh:
        log.info("발행할 것도 갱신할 것도 없습니다. 오늘은 아무것도 쓰지 않습니다.")
        _export_taxonomy()
        if not dry_run:
            reg.save()
        return 0

    remaining = len(result.new) - len(to_publish)
    if remaining > 0:
        log.info("큐에 %d건이 남았습니다 (상한 %d건 적용).", remaining, publish_limit)
    if len(result.changed) > refresh_limit:
        log.info("갱신 대기 %d건이 남았습니다 (상한 %d건 적용).",
                 len(result.changed) - refresh_limit, refresh_limit)

    # ── ③④ 발행·갱신 ──
    client = _groq_client()
    write_result = publish.run(to_publish, to_refresh, reg, today, client, dry_run)

    # ── ⑤ 인덱스 ──
    _export_taxonomy()
    if not dry_run:
        reg.save()

    log.info("━━━ 완료 — %s ━━━", write_result.summary())
    for path in write_result.paths:
        log.info("  → %s", path.relative_to(ROOT))
    if write_result.rejected:
        log.warning("반려 %d건:", len(write_result.rejected))
        for item in write_result.rejected:
            log.warning("  ✗ %s — %s", item["name"], item["reason"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
