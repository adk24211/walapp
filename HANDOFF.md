# Walapp — Claude Code 인수인계 문서

> 이 문서는 claude.ai에서 진행한 작업을 Claude Code에서 이어받아 계속하기 위한 인수인계 파일입니다.

---

## 프로젝트 개요

**Walapp** — 정부 청년 정책, 개발자 채용 동향, IT 테크 뉴스를 매일 자동으로 수집·요약해서 발행하는 Jekyll 기반 정적 사이트.

- 배포: GitHub Pages
- 자동화: GitHub Actions (매일 KST 07:00)
- AI 생성: Anthropic Claude API (claude-sonnet-4-20250514)
- 스타일: 카드형 뉴스레터 UI, 라이트/다크 모드 지원

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

## 남은 작업 (우선순위 순)

### C) 배포 세팅 — 가장 먼저 해야 함

```bash
# 1. _config.yml 수정
url: "https://YOUR_USERNAME.github.io"
# repo 이름이 있다면 baseurl도 수정
# baseurl: "/dailybrief"

# 2. GitHub 레포 생성 후 push
git init
git add .
git commit -m "init: dailybrief"
git remote add origin https://github.com/YOUR_USERNAME/dailybrief.git
git push -u origin main

# 3. GitHub Secrets 등록
# Settings → Secrets and variables → Actions → New repository secret
# Name: ANTHROPIC_API_KEY
# Value: sk-ant-...

# 4. GitHub Pages 설정
# Settings → Pages → Source: gh-pages 브랜치 선택
```

### D) 수집 소스 검증 및 보강

실제로 돌려보면 RSS URL이 막히거나 바뀐 것들이 있을 수 있음.

```bash
# 로컬에서 수집 테스트
cp .env.example .env        # .env에 ANTHROPIC_API_KEY 입력
pip install -r requirements.txt

# 수집만 테스트 (API 호출 없음)
cd scripts
python -c "from collect.gov_policy import collect; r = collect(); print(len(r))"
python -c "from collect.dev_jobs import collect; r, s = collect(); print(len(r), s)"
python -c "from collect.tech_news import collect; r = collect(); print(len(r))"

# 전체 파이프라인 테스트 (파일 저장 없음)
DRY_RUN=1 python run_all.py
```

**검증 포인트:**
- `gov_policy.py` — 정책브리핑 RSS URL이 실제 작동하는지 확인. 안 되면 `https://www.korea.kr/rss/policy.xml` 대신 다른 엔드포인트로 교체
- `dev_jobs.py` — 원티드 RSS는 로그인이 필요할 수 있음. 안 되면 사람인 RSS(`https://www.saramin.co.kr/zf_user/rss`) 로 대체
- `tech_news.py` — GeekNews RSS URL(`https://feeds.feedburner.com/geeknews-feed`) 확인 필요

**대체 소스 후보:**
```python
# 정책
"https://www.gov.kr/rss/news.do"                     # 정부24 뉴스
"https://www.moe.go.kr/rssFeed.do?m=010902"          # 교육부

# 채용
"https://www.saramin.co.kr/zf_user/rss"              # 사람인
"https://rss.jobkorea.co.kr/rss/it"                  # 잡코리아 IT

# 테크
"https://news.hada.io/rss"                           # GeekNews (대체)
"https://yozm.wishket.com/magazine/feed/"            # 요즘IT
```

### E) 포스팅 품질 튜닝

`scripts/generate_post.py`의 `_build_prompt()` 함수가 핵심.
실제 생성 결과를 보면서 프롬프트를 다듬는 작업.

```bash
# API 비용 아끼면서 프롬프트 테스트
SKIP_COLLECT=1 DRY_RUN=1 python scripts/run_all.py
# → .cache/last_collect.json 캐시 재사용, 파일 저장 없이 생성 결과만 출력
```

**튜닝 포인트:**
- 카드 `summary` 길이 (현재 80자 제한 → 너무 짧으면 늘리기)
- 본문 길이 (현재 600~900자 → 원하는 길이로 조정)
- `callout` 생성 품질 — 정책 포스트에서 핵심 수치가 잘 추출되는지 확인
- `headline` 생성 — index.html h1에 쓰이는 오늘의 헤드라인

### F) 아카이브 페이지

날짜별로 지난 포스팅을 모아보는 페이지.
`archive.html` 파일 하나 추가하면 됨.

```html
---
layout: default
title: 아카이브
---
<!-- 월별 그룹핑해서 포스트 목록 표시 -->
{% assign postsByYear = site.posts | group_by_exp: "post", "post.date | date: '%Y년 %m월'" %}
{% for group in postsByYear %}
  <h2>{{ group.name }}</h2>
  {% for post in group.items %}
    <!-- 카드 또는 리스트 형태로 표시 -->
  {% endfor %}
{% endfor %}
```

### G) (선택) 카테고리 페이지

`/category/policy`, `/category/dev-jobs`, `/category/tech-news` 각각의 페이지.
`jekyll-archives` 플러그인 또는 수동 페이지 생성 방식으로 구현.

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
