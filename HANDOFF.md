# Walapp — Claude Code 인수인계 문서

> 이 문서는 claude.ai에서 진행한 작업을 Claude Code에서 이어받아 계속하기 위한 인수인계 파일입니다.

---

## 프로젝트 개요

**Walapp** — 국내·해외 핫뉴스, 흥미로운 발견, 정부·청년 정책을 매일 자동으로 수집·요약해서 발행하는 Jekyll 기반 정적 사이트.

- 배포: GitHub Pages (gh-pages 브랜치, peaceiris/actions-gh-pages)
- 자동화: GitHub Actions "Daily Post Generator" (매일 KST 07:00 + 수동 실행)
- AI 생성: Groq API (llama-3.3-70b-versatile, 폴백 llama-3.1-8b-instant) — 무료
- 카테고리: domestic(국내) / world(해외) / curious(흥미로운 발견) / policy(정책)
- 스타일: 카드형 뉴스레터 UI + 히어로 카드, 라이트/다크 모드, Pretendard(로고 Ubuntu)
- 부가: 검색(/search/), 아카이브(/archive/), 카테고리 페이지(/category/*),
  포스트 TOC·공유·이전다음·관련글, 법적 페이지(면책/개인정보/약관/소개), SEO(GA4·Search Console)

---

## 현재 완료된 작업

### A) Jekyll 사이트 템플릿 ✅
- `_layouts/default.html` — 공통 레이아웃 (Tabler 아이콘, 다크모드 깜빡임 방지)
- `_layouts/post.html` — 포스트 상세 레이아웃
- `_includes/header.html` — 미니멀 헤더 + 다크모드 토글
- `_includes/footer.html` — 사이트 푸터
- `_includes/category-label.html` — 카테고리명 한글 변환
- `_includes/reading-time.html` — 읽기 시간 자동 계산
- `assets/css/main.css` — 전체 스타일 (CSS 변수 기반, 반응형)
- `assets/js/main.js` — 다크모드(localStorage 유지) + 탭 필터
- `index.html` — 카테고리별 섹션 + 카드 리스트

**디자인 특징:**
- 폰트: Instrument Serif (제목) + DM Sans (본문)
- 카드 좌측 4px 컬러 액센트 바로 카테고리 구분
- CSS 변수 `data-theme="dark"` 방식 다크모드
- 카테고리 컬러: policy(#378ADD 파란계열), dev-jobs(#D85A30 주황계열), tech(#1D9E75 초록계열)

### B) 데이터 수집 + 포스팅 생성 파이프라인 ✅
- `scripts/collect/base.py` — 공통 유틸 (fetch, parse_rss, parse_html, RawItem)
- `scripts/collect/gov_policy.py` — 정책브리핑·고용부·국토부 RSS + 청년 키워드 필터
- `scripts/collect/dev_jobs.py` — 원티드·점핏 RSS + GitHub Trending + 스택 빈도 분석
- `scripts/collect/tech_news.py` — GeekNews·Bloter·ZDNet·TechCrunch·HN Top API
- `scripts/generate_post.py` — Claude API 호출 → JSON → Jekyll 마크다운 변환
- `scripts/run_all.py` — 전체 파이프라인 진입점
- `.github/workflows/daily-post.yml` — cron 스케줄 + Jekyll 빌드 + gh-pages 배포

---

## 전체 파일 구조

```
dailybrief/
├── .env.example                          # 환경변수 템플릿
├── .gitignore
├── Gemfile                               # Jekyll 의존성
├── requirements.txt                      # Python 의존성
├── _config.yml                           # Jekyll 설정 ← url 수정 필요
├── index.html                            # 메인 페이지
│
├── .github/
│   └── workflows/
│       └── daily-post.yml               # GitHub Actions
│
├── _layouts/
│   ├── default.html
│   └── post.html
│
├── _includes/
│   ├── header.html
│   ├── footer.html
│   ├── sidebar.html
│   ├── category-label.html
│   └── reading-time.html
│
├── assets/
│   ├── css/main.css
│   └── js/main.js
│
├── _posts/                               # 자동 생성되는 포스트들
│   └── YYYY-MM-DD-{category}.md
│
└── scripts/
    ├── run_all.py                        # 진입점
    ├── generate_post.py                  # Claude API → 마크다운
    └── collect/
        ├── __init__.py
        ├── base.py
        ├── gov_policy.py
        └── dev_jobs.py
        └── tech_news.py
```

---

## 진행 현황 (HANDOFF C~G 전부 완료)

### C) 배포 세팅 — ✅ 완료
- `_config.yml`: `url: https://adk24211.github.io`, `baseurl: /walapp`
- 레포 `adk24211/walapp` 생성·push, Secret `GROQ_API_KEY` 등록
- GitHub Pages: `gh-pages` 브랜치(Actions가 자동 생성·배포)

### D) 수집 소스 검증 및 보강 — ✅ 완료
- **핵심 수정**: `parse_rss`가 `feedparser.parse(url)` 직접 호출 → 봇 UA로 한국 사이트 차단.
  `fetch()`(브라우저 UA)로 받아 파싱하도록 변경 → 한국 매체 정상화
- 죽은 소스(404/DNS/403) 제거, 카테고리 개편에 맞춰 소스 재구성:
  - `domestic_news.py` — 구글뉴스(KR)·연합뉴스·한겨레
  - `world_news.py` — 구글뉴스(World)·BBC·Al Jazeera
  - `curious.py` — ScienceAlert·LiveScience·ScienceDaily·Smithsonian·MIT Tech Review
  - `gov_policy.py` — 정책브리핑(korea.kr) + 청년 키워드 필터

### E) 포스팅 품질 튜닝 — ✅ 완료
- 문체: 신문 기사체('-요' 금지, '-다'/명사형 종결)
- 분량: 1800~2800자, 섹션별 4~6문장, 독자 몰입 규칙(도입부·배경·전망)
- 후처리: 들여쓰기 제거, 한자·일본어 가나 제거, `_yaml_safe()` front matter 보정
- `max_tokens` 4096, 일일 한도 초과 시 경량 모델 폴백

### F) 아카이브 페이지 — ✅ 완료
- `/archive/` 월별 그룹핑 카드 리스트

### G) 카테고리 페이지 — ✅ 완료
- `/category/{domestic,world,curious,policy}/` (공통 include 사용)

---

## 추가 완료 항목 (HANDOFF 외)
- 검색(`/search/` + `/search.json`), 포스트 TOC·공유·이전다음·관련글
- 히어로 카드, 카드 호버 효과, 탭 이모지, Pretendard 폰트, favicon
- 법적 페이지: `/disclaimer/` `/privacy/` `/terms/` `/about/`, 포스트 하단 면책 박스
- SEO: robots.txt, 404, OG/트위터/JSON-LD, GA4(G-NS58PGSBFP), Search Console 인증

## 향후 후보 (선택)
- Groq 토큰 리셋 후 워크플로우 실행 → 4카테고리 포스트 최종 확인
- AdSense 신청 및 승인 후 `ads.txt` 추가
- Search Console에 `sitemap.xml` 제출
- 페이지네이션(글 누적 시), 카테고리별 OG 메타 최적화

---

## 핵심 코드 위치 빠른 참조

| 목적 | 파일 | 핵심 부분 |
|------|------|-----------|
| 카드 디자인 수정 | `assets/css/main.css` | `.post-card`, `.card-body`, `.card-accent` |
| 카테고리 컬러 변경 | `assets/css/main.css` | `:root` 변수 블록 (`--policy`, `--jobs`, `--tech`) |
| 다크모드 컬러 | `assets/css/main.css` | `[data-theme="dark"]` 블록 |
| 포스트 카드 레이아웃 | `index.html` | `{% for post in policy_posts %}` 루프 |
| Claude 프롬프트 수정 | `scripts/generate_post.py` | `_build_prompt()` 함수 |
| 수집 소스 추가/수정 | `scripts/collect/*.py` | `SOURCES` 리스트 또는 `collect()` 함수 |
| 스케줄 변경 | `.github/workflows/daily-post.yml` | `cron:` 값 |
| Jekyll 설정 | `_config.yml` | `url`, `baseurl` |

---

## Front Matter 규격 (포스트 파일 상단)

```yaml
---
layout: post
title: "제목 (40자 이내 권장)"
date: 2026-05-30 07:00:00 +0900
categories: [policy]          # policy / dev-jobs / tech-news 중 하나
tags:
  - 태그1
  - 태그2
summary: "카드에 표시될 요약 (80자 이내)"
callout: "강조할 핵심 정보 한 줄"          # 선택
callout_label: "신청 기간"                  # callout 앞 라벨, 선택
headline: "오늘의 헤드라인"                 # index.html h1용, 당일 첫 번째 포스트에만
---
```

---

## 로컬 개발 환경

```bash
# Ruby/Jekyll 로컬 서버
bundle install
bundle exec jekyll serve --livereload
# → http://localhost:4000

# Python 환경
pip install -r requirements.txt
cp .env.example .env   # ANTHROPIC_API_KEY 입력

# 전체 파이프라인 테스트
cd scripts
DRY_RUN=1 python run_all.py

# 특정 수집기만 테스트
python -m collect.tech_news
python -m collect.gov_policy
python -m collect.dev_jobs
```

---

## GitHub Actions 수동 실행 방법

1. GitHub 레포 → Actions 탭
2. "Daily Post Generator" 워크플로우 선택
3. "Run workflow" 클릭
4. `post_date`: 날짜 입력 (비우면 오늘)
5. `dry_run`: 체크하면 파일 저장 없이 테스트

---

## 주의사항

- `.env` 파일은 절대 커밋하지 말 것 (`.gitignore`에 포함되어 있음)
- `ANTHROPIC_API_KEY`는 GitHub Secrets에만 저장
- `scripts/` 디렉토리는 Jekyll 빌드에서 제외됨 (`_config.yml`의 `exclude` 목록)
- 포스팅 파일명 규칙: `YYYY-MM-DD-{category}.md` (같은 날 같은 카테고리는 덮어씌워짐)
- GitHub Pages 무료 플랜은 public 레포만 지원
