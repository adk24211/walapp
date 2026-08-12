# 구현 현황 — 지원금 도감 전환

> `REDESIGN.md` 설계서의 **단계 1~5 구현 완료** (목 데이터 기준).
> 단계 0(API 활용신청)은 사용자 작업이고, 6~7은 그 뒤에 이어집니다.

---

## 지금 바로 돌려 보기

API 키가 하나도 없어도 파이프라인 전체가 끝까지 돕니다. 목 모드는 **표준 라이브러리만** 씁니다.

```bash
# 1) 제도 페이지 생성 (목 데이터 29건)
python3 scripts/run_all.py

# 2) 사이트 빌드
bundle install
bundle exec jekyll serve --future
# → http://localhost:4000/walapp/
```

주요 환경변수:

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `MOCK_DATA` | 자동 | `DATA_GO_KR_API_KEY` 가 없으면 자동으로 목 모드. `1`/`0` 으로 강제 가능 |
| `PUBLISH_LIMIT` | 5 | 하루 신규 발행 상한 |
| `REFRESH_LIMIT` | 10 | 하루 갱신 상한 |
| `POST_DATE` | 오늘(KST) | 기준 날짜 override |
| `DRY_RUN` | 0 | `1` 이면 파일을 쓰지 않음 |

---

## 목 데이터 안전장치 ⚠️

지원금 정보는 YMYL 영역이라 **가짜 수치가 공개되면 실제 피해로 이어집니다.** 4중으로 막아 뒀습니다.

1. 목 레코드는 `is_mock=true` → 제도 페이지 상단에 **경고 배너** 렌더
2. 같은 플래그로 `<meta name="robots" content="noindex, nofollow">` 삽입
3. `search.json` 색인에서 제외
4. `.gitignore` 에 `_programs/` · `_records/` → **생성물이 커밋되지 않음**
5. `daily-sync.yml` 첫 스텝이 `DATA_GO_KR_API_KEY` 부재 시 워크플로우를 **중단**

> 실 API 전환 시 `.gitignore` 의 `_programs/` · `_records/` 두 줄을 지워야 워크플로우가
> 생성물을 커밋할 수 있습니다.

---

## 검증한 것

### ① 중복이 구조적으로 불가능한가

```
1회차:  신규 29 · 변경 0 · 동일  0 · 필드누락 1 · 유사검토 1
2회차:  신규  0 · 변경 0 · 동일 29 · 필드누락 1 · 유사검토 1
        → "발행할 것도 갱신할 것도 없습니다. 오늘은 아무것도 쓰지 않습니다."
```

같은 소스를 다시 수집해도 신규 발행이 0입니다. 규칙이 아니라 **파일 경로가 제도 ID로 결정되기 때문**입니다.

3중 방어가 모두 발화하는 것도 확인했습니다.

| 계층 | 대상 | 결과 |
|------|------|------|
| 1 · ID 조회 | 재수집분 29건 | 전부 `unchanged` 로 흡수 |
| 2 · `content_hash` | 내용 동일 | 갱신 스킵, `last_checked` 만 갱신 |
| 3 · 유사도 | `청년 월세 한시 특별지원` vs `청년월세 한시 특별지원` | 유사도 1.0 → `_data/review_needed.json` 격리 (자동 병합 안 함) |
| 필수 필드 | 지원대상 누락 1건 | `_data/incomplete.json` 격리, 발행 안 함 |

### ② 환각이 차단되는가

원본에 없는 수치를 섞은 가짜 LLM 출력을 넣어 봤습니다.

```
입력:  "월 최대 20만 원을 12개월간 지원합니다. 신청자는 평균 340만 원의 혜택을 받습니다."
       "작년 기준 채택률은 87%였습니다"
       "심사는 3주 안에 끝나며 통과율은 62%입니다."
       "경쟁률은 4대 1 수준이며 8만 명이 신청했습니다."

판정:  위반 수치 4건(8, 62, 87, 340) · 문장 4개 폐기

출력:  "월 최대 20만 원을 12개월간 지원합니다."          ← 원본에 있는 수치라 생존
       (나머지 4문장 전부 삭제)
```

`3주` 의 `3` 은 원본 날짜(2026-**03**-02)에 있어 통과했지만, 같은 문장의 `62%` 가 걸려 문장째 폐기됐습니다.

### ③ 페이지가 제대로 나오는가

브라우저 렌더링까지 확인했습니다.

- 제도 상세: JSON-LD `GovernmentService`, 목 경고 배너, noindex, 정부 비공식 고지, 공식 창구 CTA, 한눈에보기 표, 자격 체크리스트, 신청 절차, 구비 서류, 신청 일정, FAQ, 관련 제도 내부링크, 최종 확인일 — 전부 렌더
- 마감된 제도(`2026 상반기 지역사랑상품권`)에 **접수 종료 배너** 자동 표시
- 가로 스크롤 없음 (`document.scrollWidth <= clientWidth`)

허브 필터링 결과:

| 허브 | 건수 | 검증 |
|------|------|------|
| `/support/` | 29 | 전체 |
| `/who/youth/` | 16 | 대상 교차 필터 |
| `/region/national/` | 25 | 중앙부처만 |
| `/region/gyeonggi/` | 2 | 시군구(성남시)가 시도로 정상 롤업 |
| `/region/seoul/` | 1 | |
| `/deadline/` | 8 | 상시·마감분 정확히 제외 |

---

## 설계서에서 바꾼 것

구현하면서 REDESIGN.md 와 달라진 부분입니다. 이유가 있는 변경입니다.

| 설계서 | 실제 | 이유 |
|--------|------|------|
| `scripts/queue.py` | `scripts/queueing.py` | `scripts/` 가 `sys.path` 에 들어가 표준 라이브러리 `queue` 를 가린다. `urllib3` 등이 이를 import 하므로 이름을 비켰다 |
| `_data/programs/{id}.json` | `_records/{id}.json` | Jekyll 은 `_data` 하위를 전부 파싱해 `site.data` 에 올린다. 레코드가 수천 건이 되면 빌드마다 낭비다. 밑줄 디렉터리는 Jekyll 이 통째로 무시한다 |
| 허브 33개 stub 파일 | `_plugins/hub_generator.rb` | 분류를 고칠 때마다 파일 33개를 손대야 한다. `_data/taxonomy.json` 하나를 진실로 두고 빌드 시점에 36개를 생성한다 |
| `/support/{category}/{slug}/` 수동 | `permalink: /support/:path/` | 파일 경로가 곧 URL. 별도 매핑이 필요 없다 |

`_plugins/` 를 쓸 수 있는 이유는 배포가 GitHub Pages 기본 빌더가 아니라 워크플로우 안의
`bundle exec jekyll build` 이기 때문입니다. 구 구조가 준 뜻밖의 이점입니다.

---

## 파일 지도

```
scripts/
├── run_all.py            진입점 — ①동기화 ②큐 ③발행 ④갱신 ⑤인덱스
├── schema.py             ProgramRecord 표준 스키마 + content_hash + slug
├── taxonomy.py           분야 7 · 대상 8 · 지역 18 (Liquid 로 내보냄)
├── registry.py           발행 원장 · 레코드 저장소 · 유사도 판정      ★ 중복 방지의 뿌리
├── sync.py               ① 원천 → 원장 대조 → 신규/변경/동일/격리
├── queueing.py           ② 우선순위 점수 (지역·대상·마감·신설·제도명)
├── generate_program.py   ③ 해설 프롬프트 + 오프라인 폴백
├── verify.py             ③ 수치 후검증                                ★ 환각 차단
├── publish.py            ③④ 생성 → 검증 → 파일 쓰기 → 원장 기록
├── render.py             레코드+해설 → Jekyll 마크다운
├── migrate_brief.py      ⑤ 구 포스트 격리 · canonical 정리
└── collect/adapters/
    ├── base.py           어댑터 인터페이스 + 정규화
    ├── mock.py           목 데이터 31건 (모든 분기를 밟도록 구성)
    └── bojo24.py         실 API 어댑터 — ⚠️ 필드명 확정 필요

_layouts/program.html     제도 상세
_layouts/hub.html         분야·대상·지역·마감·신규 공용
_includes/program-card.html
_plugins/hub_generator.rb 허브 36개 자동 생성
assets/css/support.css    분야 컬러 7종 + 제도 페이지 컴포넌트
```

---

## 구 사이트 처리 (단계 5 완료)

- `_posts` 272건 → **삭제하지 않고** `/brief/` 로 격리 (`permalink` 변경)
- 중복 제목 26그룹 → 본문이 가장 긴 1건을 정본으로, 나머지 **42건에 `canonical_url` 지정**
  - canonical 은 반드시 절대 URL. 상대 경로면 `baseurl`(`/walapp`)이 빠져 존재하지 않는 주소를 가리킨다
- 272건 전부 `archived: true` → 레이아웃이 "발행 중단" 안내 배너 표시
- `/archive/` `/guide/` `/weekly/` → canonical + 메타 리프레시로 새 페이지에 연결 (404 방지)
- `404.html` 이 주소 변경을 안내
- 구 워크플로우 `daily-post.yml` 삭제, RSS 수집기(`korea_policy.py`·`curious.py`)와
  `generate_post.py` 삭제

---

## 남은 일

| 단계 | 내용 | 담당 |
|------|------|------|
| **0** | 공공데이터포털 활용신청 → 키 발급 → `bojo24.py` 의 `ID_FIELD`·`FIELD_MAP` 확정 | **사용자** |
| 6 | `.gitignore` 에서 `_programs/`·`_records/` 제거, 실 API 로 첫 동기화 | 단계 0 이후 |
| 7 | 초기 백필 (상위 100~300건 일괄 발행) | 단계 6 이후 |

`bojo24.py` 의 `ID_FIELD` 가 가장 중요합니다. **이 값이 흔들리면 같은 제도가 매일 새 페이지로
발행되어** 컨셉 전환의 의미가 사라집니다. 활용가이드에서 가장 먼저 확인하세요.

미결 결정 사항은 `REDESIGN.md` §11 에 그대로 남아 있습니다. 그중 **기존 272개 포스트 처리**는
`/brief/` 격리로 일단 구현했으나, Search Console 유입 데이터를 보고 `noindex` 로 바꿀지
최종 판단이 필요합니다.
