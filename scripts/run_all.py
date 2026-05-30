"""
왈랩 자동화 파이프라인 진입점

실행 방법:
    python scripts/run_all.py

환경변수 (.env 또는 GitHub Secrets):
    GEMINI_API_KEY     — Gemini API 키 (필수)
    POST_DATE          — 포스팅 날짜 override (선택, YYYY-MM-DD 형식)
    SKIP_COLLECT       — "1" 이면 수집 스킵, 캐시 사용 (개발용)
    DRY_RUN            — "1" 이면 파일 저장 없이 출력만 (개발용)
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

# 프로젝트 루트를 sys.path에 추가
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

load_dotenv(ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("run_all")

POSTS_DIR  = ROOT / "_posts"
CACHE_DIR  = ROOT / ".cache"
CACHE_FILE = CACHE_DIR / "last_collect.json"

CATEGORY_ORDER = ["policy", "dev-jobs", "tech-news"]
# 카테고리별 포스팅 시간 (KST)
POST_HOURS = {
    "policy":    "07:00:00",
    "dev-jobs":  "07:01:00",
    "tech-news": "07:02:00",
}


def load_cache() -> dict:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    return {}


def save_cache(data: dict) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    CACHE_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def collect_all(skip: bool = False) -> dict:
    """전체 수집 실행"""
    if skip and CACHE_FILE.exists():
        log.info("캐시에서 수집 데이터 로드")
        return load_cache()

    from collect.gov_policy import collect as collect_policy
    from collect.dev_jobs import collect as collect_jobs
    from collect.tech_news import collect as collect_tech

    log.info("━━━ 데이터 수집 시작 ━━━")
    collected: dict = {}

    # 정책
    try:
        policy_items = collect_policy()
        collected["policy"] = {
            "items": [vars(i) for i in policy_items],
            "extra": {},
        }
        log.info("정책: %d건", len(policy_items))
    except Exception as e:
        log.error("정책 수집 실패: %s", e)
        collected["policy"] = {"items": [], "extra": {}}

    time.sleep(1)

    # 채용
    try:
        jobs_items, stack_counts = collect_jobs()
        collected["dev-jobs"] = {
            "items": [vars(i) for i in jobs_items],
            "extra": {"stack_counts": stack_counts},
        }
        log.info("채용: %d건", len(jobs_items))
    except Exception as e:
        log.error("채용 수집 실패: %s", e)
        collected["dev-jobs"] = {"items": [], "extra": {}}

    time.sleep(1)

    # 테크 뉴스
    try:
        tech_items = collect_tech()
        collected["tech-news"] = {
            "items": [vars(i) for i in tech_items],
            "extra": {},
        }
        log.info("테크: %d건", len(tech_items))
    except Exception as e:
        log.error("테크 수집 실패: %s", e)
        collected["tech-news"] = {"items": [], "extra": {}}

    save_cache(collected)
    log.info("수집 완료 — 캐시 저장")
    return collected


def generate_posts(
    collected: dict,
    client: Groq,
    post_date: datetime,
    dry_run: bool = False,
) -> list[Path]:
    """포스팅 생성 및 저장"""
    from collect.base import RawItem
    from generate_post import generate, to_jekyll_markdown, make_filename

    log.info("━━━ 포스팅 생성 시작 ━━━")
    saved: list[Path] = []

    for idx, category in enumerate(CATEGORY_ORDER):
        data = collected.get(category, {})
        raw_items = data.get("items", [])
        extra = data.get("extra", {})

        if not raw_items:
            log.warning("%s: 수집 데이터 없음, 스킵", category)
            continue

        # dict → RawItem 복원
        items = [RawItem(**i) for i in raw_items]

        try:
            post_data = generate(category, items, client, extra)
        except Exception as e:
            log.error("%s 포스팅 생성 실패: %s", category, e)
            continue

        # 날짜에 카테고리별 시간 반영
        h, m, s = POST_HOURS[category].split(":")
        dated = post_date.replace(hour=int(h), minute=int(m), second=int(s))

        md_content = to_jekyll_markdown(post_data, category, dated)
        filename = make_filename(category, dated, post_data["title"])
        filepath = POSTS_DIR / filename

        if dry_run:
            log.info("[DRY RUN] %s 생성 예정:\n%s", filename, md_content[:300])
        else:
            POSTS_DIR.mkdir(exist_ok=True)
            filepath.write_text(md_content, encoding="utf-8")
            log.info("저장 완료: %s", filepath.name)
            saved.append(filepath)

        # API 레이트 리밋 방지
        if idx < len(CATEGORY_ORDER) - 1:
            time.sleep(2)

    return saved


def main() -> None:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        log.error("GROQ_API_KEY 환경변수가 없어요.")
        sys.exit(1)

    # 날짜 설정
    date_override = os.environ.get("POST_DATE")
    if date_override:
        post_date = datetime.strptime(date_override, "%Y-%m-%d")
    else:
        post_date = datetime.now()

    skip_collect = os.environ.get("SKIP_COLLECT") == "1"
    dry_run      = os.environ.get("DRY_RUN") == "1"

    log.info("━━━ 왈랩 파이프라인 시작 ━━━")
    log.info("날짜: %s | DRY_RUN: %s | SKIP_COLLECT: %s",
             post_date.strftime("%Y-%m-%d"), dry_run, skip_collect)

    # 수집
    collected = collect_all(skip=skip_collect)

    # 생성
    client = Groq(api_key=api_key)
    saved  = generate_posts(collected, client, post_date, dry_run=dry_run)

    if saved:
        log.info("━━━ 완료: 총 %d개 포스트 저장 ━━━", len(saved))
        for p in saved:
            log.info("  → %s", p.name)
    else:
        log.info("━━━ 완료 (저장된 파일 없음) ━━━")


if __name__ == "__main__":
    main()
