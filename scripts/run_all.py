"""지원금 도감 파이프라인 진입점.

    ① 동기화   원천 API 목록 → 원장 대조 → 신규/변경/동일/격리 분류
    ② 큐 산출   신규 후보에 우선순위 점수 부여 (원천 조회수 기준)
    ③ 발행      오늘 조의 테마마다 1건 + 시행 예정 1건
    ④ 갱신      내용이 바뀐 제도 상위 M건 · 상태만 바뀐 제도 전량
    ⑤ 인덱스    분류 데이터를 Jekyll 로 내보냄

구 파이프라인(매일 4개 강제 발행)과의 차이:
  · 소재를 RSS 최신순이 아니라 큐에서 꺼낸다
  · 순서를 정하는 건 추정이 아니라 원천이 주는 실제 조회수다
  · 큐가 비면 아무것도 발행하지 않는다 — 억지 생성이 중복의 직접 원인이었다
  · 같은 제도의 재등장은 새 글이 아니라 갱신으로 흡수된다

환경변수:
    GROQ_API_KEY         해설 생성용. 없으면 오프라인 폴백으로 동작한다.
    DATA_GO_KR_API_KEY   공공데이터포털 키. 없으면 목 데이터로 동작한다.
    MOCK_DATA            "1" 강제 목 모드 / "0" 강제 실 API 모드
    POST_DATE            기준 날짜 override (YYYY-MM-DD)
    PUBLISH_MODE         "theme" 테마 조 방식 (기본) / "top" 상위 N건 일괄
    PER_THEME_LIMIT      theme 방식에서 테마당 발행 건수 (기본 1)
    UPCOMING_LIMIT       시행 예정 발행 건수 (기본 1, 후보 없으면 0건)
    PUBLISH_LIMIT        top 방식 발행 상한 (기본 5) — 초기 백필용
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
import generate_program
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

# 테마 조 방식: 그날 조의 테마마다 1건 + 시행 예정 1건 = 하루 최대 5건.
# (테마 8개를 4개씩 격일로 돌리므로 시행중 발행은 하루 4건이다.)
DEFAULT_PUBLISH_MODE = "theme"
# 테마 11개 · 큰 조 6개 기준으로 5×6+1 = 31건. 하루 토큰 천장(약 32건) 아래다.
# ⚠️ taxonomy.AUDIENCE_GROUPS 와 함께 봐야 한다 — 한쪽만 바꾸면 한도에 부딪힌다.
DEFAULT_PER_THEME_LIMIT = 5
DEFAULT_UPCOMING_LIMIT = 1
# PUBLISH_MODE=top 일 때만 쓰는 상한. 초기 백필용 탈출구다.
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


def _log_period_stats(stats) -> None:
    """신청기한 표기 분포를 로그에 남긴다.

    JSON(_data/period_formats.json)은 커밋하지 않는 진단물이라(.gitignore),
    실행 로그가 유일한 추적 수단이다. 못 읽은 표기 상위 10종이 곧 다음
    파서 작업 목록이다.
    """
    if not stats.total:
        return
    log.info("신청기한 표기 — 전량 %d건 · 상시 %d · 구간 %d · 시작만 %d "
             "· 마감만 %d · 원문없음 %d · 못읽음 %d",
             stats.total, stats.always, stats.both, stats.start_only,
             stats.end_only, stats.no_raw, sum(stats.unparsed.values()))
    for raw, count in stats.unparsed.most_common(10):
        log.info("  못읽음 %5d회 · %s", count, raw)


def main() -> int:
    _load_dotenv()

    import publish
    import queueing
    import registry
    import sync
    import taxonomy
    from collect import adapters

    date_override = os.environ.get("POST_DATE")
    today: date = (
        datetime.strptime(date_override, "%Y-%m-%d").date()
        if date_override
        else datetime.now(ZoneInfo("Asia/Seoul")).date()
    )
    dry_run = os.environ.get("DRY_RUN") == "1"
    publish_mode = os.environ.get("PUBLISH_MODE", DEFAULT_PUBLISH_MODE).strip().lower()
    publish_limit = int(os.environ.get("PUBLISH_LIMIT", DEFAULT_PUBLISH_LIMIT))
    per_theme = int(os.environ.get("PER_THEME_LIMIT", DEFAULT_PER_THEME_LIMIT))
    upcoming_limit = int(os.environ.get("UPCOMING_LIMIT", DEFAULT_UPCOMING_LIMIT))
    refresh_limit = int(os.environ.get("REFRESH_LIMIT", DEFAULT_REFRESH_LIMIT))
    scopes = tuple(
        s.strip() for s in
        os.environ.get("REGION_SCOPE", ",".join(sync.DEFAULT_SCOPES)).split(",")
        if s.strip()
    )
    mock = adapters.use_mock()

    log.info("━━━ 지원금 도감 파이프라인 ━━━")
    log.info("날짜 %s · 데이터 %s · DRY_RUN %s · 갱신상한 %d",
             today, "목(mock)" if mock else "실 API", dry_run, refresh_limit)
    if publish_mode == "top":
        log.info("발행 방식: top · 상한 %d건", publish_limit)
    else:
        log.info("발행 방식: theme · 테마당 %d건 + 예정 %d건", per_theme, upcoming_limit)
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
    registry.save_period_report(result.period_stats.to_dict())
    _log_period_stats(result.period_stats)

    # ── 커버리지 기록 ──
    # 소개 화면이 "원천 몇 건 중 몇 건을 다루는가" 를 밝히는데, 그 숫자를 HTML 에
    # 적어 두면 다음 동기화부터 틀린 말이 된다. 방금 실제로 센 값을 남겨 화면이
    # 읽게 한다.
    #
    # 범위 밖(out_of_scope)이 왜 중요한가: 원천 10,961건 중 8,597건이 지자체
    # 제도라 발행 범위(REGION_SCOPE=national) 밖이다. 이걸 밝히지 않고 "1만 건 중
    # 405건" 만 적으면 4% 를 다루는 사이트로 읽히는데, 실제로는 다루기로 한
    # 범위 안에서 405/2,364 다. 어느 쪽도 숨길 이유가 없으니 둘 다 적는다.
    #
    # dry_run 에서도 쓴다 — 파일 하나이고, 이 값은 발행 여부와 무관하게 '원천을
    # 훑은 결과' 이기 때문이다. 커밋 단계가 _data/ 를 함께 담는다.
    registry.save_coverage({
        "synced_at": today.isoformat(),
        "scopes": list(scopes),
        # 이번 실행이 원천에서 훑은 전량
        "source_total": result.total,
        # 발행 범위 밖이라 건너뛴 것 (아직 발행 전인 것만 센다 — sync.run 주석 참고)
        "out_of_scope": result.out_of_scope,
        # 원문에 필수 항목이 없어 못 쓰는 것
        "incomplete": len(result.incomplete),
        # 기존 제도와 이름이 너무 비슷해 사람 확인을 기다리는 것
        "review_needed": len(result.review_needed),
    })
    # ⚠️ 발행 건수를 여기 담지 않는 이유. 이 지점은 발행 **전**이라 len(reg) 는
    #    오늘 새로 낸 것을 아직 모른다(오늘은 20건 차이가 났다). 화면은
    #    site.programs 로 세면 언제나 정확하므로, 한 화면에 서로 다른 시점의
    #    숫자가 섞이지 않도록 여기서는 아예 남기지 않는다.
    #    '아직 못 낸 것' 도 화면에서 (범위 안 − 발행 − 검토대기)로 뺀다.

    # ── ② 큐 산출 ──
    queue_payload = queueing.build(result.new, today)
    if not dry_run:
        registry.save_queue(queue_payload)

    by_id = {r.id: r for r in result.new}

    # ── 발행 대상 선정 ──
    # 기본은 '테마 조' 방식이다. 테마 8개를 4개씩 두 조로 나눠 하루씩 번갈아,
    # 그날 조의 테마마다 1건씩(총 4건) + 시행 예정 1건.
    # 조 선택은 날짜에서 바로 계산하므로 상태 파일이 필요 없다.
    if publish_mode == "top":
        to_publish = queueing.take(queue_payload, by_id, publish_limit)
        log.info("발행 방식: 상위 %d건 일괄 (테마 배분 없음)", publish_limit)
    else:
        themes = taxonomy.audience_group(today.toordinal())
        labels = " · ".join(taxonomy.AUDIENCES[t]["label"] for t in themes)
        log.info("오늘의 테마 조 (%d/%d): %s",
                 today.toordinal() % len(taxonomy.AUDIENCE_GROUPS) + 1,
                 len(taxonomy.AUDIENCE_GROUPS), labels)
        to_publish = queueing.take_by_theme(queue_payload, by_id, themes, per_theme)
        upcoming = queueing.take_upcoming(queue_payload, by_id, upcoming_limit)
        if upcoming:
            log.info("시행 예정 %d건 추가 발행", len(upcoming))
        else:
            log.info("시행 예정 후보 없음 — 오늘은 예정 발행을 건너뜁니다.")
        to_publish += upcoming

    to_refresh = result.changed[:refresh_limit]

    if not to_publish and not to_refresh and not result.restatused:
        log.info("발행할 것도 갱신할 것도 없습니다. 오늘은 아무것도 쓰지 않습니다.")
        _export_taxonomy()
        if not dry_run:
            reg.save()
        return 0

    remaining = len(result.new) - len(to_publish)
    if remaining > 0:
        log.info("큐에 %d건이 남았습니다 (오늘 %d건 발행).", remaining, len(to_publish))
    if len(result.changed) > refresh_limit:
        log.info("갱신 대기 %d건이 남았습니다 (상한 %d건 적용).",
                 len(result.changed) - refresh_limit, refresh_limit)

    # ── ③④ 발행·갱신 ──
    # 상태 변경분은 상한을 두지 않는다. 마감된 제도가 '시행중' 으로 남아 있는 것은
    # 그 자체로 잘못된 정보이므로 밀리면 안 된다. LLM 을 쓰지 않아 비용도 들지 않는다.
    if result.restatused:
        log.info("상태 변경 %d건 — 저장된 해설로 다시 찍습니다 (LLM 미사용).",
                 len(result.restatused))

    client = _groq_client()
    try:
        write_result = publish.run(to_publish, to_refresh, reg, today, client, dry_run,
                                   restatused_records=result.restatused)
    except generate_program.ModelUnavailable as e:
        # 제도 하나의 문제가 아니라 설정이 깨진 것이다. 조용히 넘어가면 오늘
        # 후보 전부가 반려로만 남고, 아무도 모르는 채 며칠이 지난다.
        # 실제로 그렇게 하루를 날렸다 — 그래서 여기서 실행을 세운다.
        log.error("━━━ 발행을 진행할 수 없습니다 ━━━")
        for line in str(e).splitlines():
            log.error("  %s", line)
        log.error("  이번 실행에서 발행·갱신된 제도는 없습니다.")
        return 2

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
