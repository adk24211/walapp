# 구현 현황 — 지원금 도감 전환

> `REDESIGN.md` 설계서의 **단계 1~5 구현 완료** (목 데이터 기준).
> 단계 0(API 활용신청)은 사용자 작업이고, 6~7은 그 뒤에 이어집니다.

---

## 지금 바로 돌려 보기

API 키가 하나도 없어도 파이프라인 전체가 끝까지 돕니다. 목 모드는 **표준 라이브러리만** 씁니다.

```bash
# 1) 제도 페이지 생성 (목 데이터 중 중앙부처 25건)
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
| `REGION_SCOPE` | `national` | 발행 범위. 중앙부처 우선 방침의 구현체. 지자체 포함은 `national,sido,sigungu` |
| `PUBLISH_LIMIT` | 5 | 하루 신규 발행 상한 |
| `REFRESH_LIMIT` | 10 | 하루 갱신 상한 |
| `POST_DATE` | 오늘(KST) | 기준 날짜 override |
| `DRY_RUN` | 0 | `1` 이면 파일을 쓰지 않음 |

---

## 목 데이터 안전장치 ⚠️

지원금 정보는 YMYL 영역이라 **가짜 수치가 공개되면 실제 피해로 이어집니다.** 5중으로 막아 뒀습니다.

1. 목 레코드는 `is_mock=true` → 제도 페이지 상단에 **경고 배너** 렌더
2. 같은 플래그로 `<meta name="robots" content="noindex, nofollow">` 삽입
3. `search.json` 색인에서 제외
4. `.gitignore` 에 `_programs/` · `_records/` · 원장 JSON → **생성물이 커밋되지 않음**
5. `daily-sync.yml` 첫 스텝이 `DATA_GO_KR_API_KEY` 부재 시 워크플로우를 **중단**

> 실 API 전환 시 `.gitignore` 의 목 데이터 블록을 통째로 지워야 워크플로우가
> 생성물과 원장을 커밋할 수 있습니다. (`_data/taxonomy.json` 은 목 데이터가 아니라
> 계속 커밋됩니다 — 빌드 때 허브 생성기가 읽습니다.)

---

## 검증한 것

### ① 중복이 구조적으로 불가능한가

```
1회차:  신규 25 · 변경 0 · 동일  0 · 필드누락 1 · 유사검토 1 · 범위밖 4
2회차:  신규  0 · 변경 0 · 동일 25 · 필드누락 1 · 유사검토 1 · 범위밖 4
        → "발행할 것도 갱신할 것도 없습니다. 오늘은 아무것도 쓰지 않습니다."
```

(목 데이터 31건 중 중앙부처 25건만 발행됩니다. 지자체 4건은 `REGION_SCOPE=national`
방침에 따라 보류, 1건은 필드 누락 격리, 1건은 유사 제도 검토 대기입니다.)

같은 소스를 다시 수집해도 신규 발행이 0입니다. 규칙이 아니라 **파일 경로가 제도 ID로 결정되기 때문**입니다.

3중 방어가 모두 발화하는 것도 확인했습니다.

| 계층 | 대상 | 결과 |
|------|------|------|
| 1 · ID 조회 | 재수집분 25건 | 전부 `unchanged` 로 흡수 |
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
| `/support/` | 25 | 전체 |
| `/support/finance/` | 4 | 분야 필터 |
| `/who/youth/` | 12 | 대상 교차 필터 (홈 카드 숫자와 일치) |
| `/who/parent/` | 3 | |
| `/region/national/` | 25 | 중앙부처만 |
| `/deadline/` | 6 | 상시·마감분 정확히 제외 |

시도 허브 17개는 해당 제도가 없어 **생성하지 않았고**, 탐색바에서도 링크를 뺐습니다.
빌드 결과물의 내부 링크를 전수 검사해 **깨진 링크 0건**을 확인했습니다.

범위 확대·축소도 확인했습니다.

```
REGION_SCOPE=national,sido,sigungu  →  신규 4 · 동일 25   (보류분이 그대로 발행됨)
REGION_SCOPE=national (다시 좁힘)   →  신규 0 · 동일 29   (발행분은 계속 추적됨)
```

---

## 설계서에서 바꾼 것

구현하면서 REDESIGN.md 와 달라진 부분입니다. 이유가 있는 변경입니다.

| 설계서 | 실제 | 이유 |
|--------|------|------|
| `scripts/queue.py` | `scripts/queueing.py` | `scripts/` 가 `sys.path` 에 들어가 표준 라이브러리 `queue` 를 가린다. `urllib3` 등이 이를 import 하므로 이름을 비켰다 |
| `_data/programs/{id}.json` | `_records/{id}.json` | Jekyll 은 `_data` 하위를 전부 파싱해 `site.data` 에 올린다. 레코드가 수천 건이 되면 빌드마다 낭비다. 밑줄 디렉터리는 Jekyll 이 통째로 무시한다 |
| 허브 33개 stub 파일 | `_plugins/hub_generator.rb` | 분류를 고칠 때마다 파일 33개를 손대야 한다. `_data/taxonomy.json` 하나를 진실로 두고 빌드 시점에 생성하며, 제도가 없는 시도 허브는 아예 만들지 않는다 |
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
    ├── bojo24.py         보조금24 어댑터 — ⚠️ 필드명 확정 필요
    └── welfare_central.py 중앙부처복지서비스 어댑터 — ⚠️ 필드명 확정 필요

_layouts/program.html     제도 상세
_layouts/hub.html         분야·대상·지역·마감·신규 공용
_includes/program-card.html
_plugins/hub_generator.rb 허브 자동 생성 (제도 있는 축만)
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
| **0** | 공공데이터포털 **API 2개** 활용신청 → 키 발급 → 어댑터 필드 확정 | **사용자** |
| 6 | `.gitignore` 의 목 데이터 블록 제거, 실 API 로 첫 동기화 | 단계 0 이후 |
| 7 | 초기 백필 (상위 100~300건 일괄 발행) | 단계 6 이후 |

중앙부처 우선 방침이라 단계 0에서 신청할 API 는 **2개뿐**입니다.

| 데이터셋 | 어댑터 | 확정할 것 |
|----------|--------|-----------|
| `15113968` 보조금24 | `collect/adapters/bojo24.py` | `ID_FIELD`, `FIELD_MAP` |
| `15090532` 중앙부처복지서비스 | `collect/adapters/welfare_central.py` | `ID_FIELD`, `FIELD_MAP`, 상세조회 필요 여부 |

지자체복지서비스(`15108347`)와 온통청년(`15143273`)은 범위를 넓힐 때 신청합니다.

두 어댑터 모두 `ID_FIELD` 가 가장 중요합니다. **이 값이 흔들리면 같은 제도가 매일 새 페이지로
발행되어** 컨셉 전환의 의미가 사라집니다.

### ID_FIELD 를 확인하는 법

`scripts/inspect_api.py` 가 필드명을 뽑아 `ID_FIELD` 후보와 `FIELD_MAP` 초안까지 출력합니다.

```bash
# ① 활용가이드(Swagger/OpenAPI) 문서에서 — 키 발급 전에도 가능
python3 scripts/inspect_api.py --docs "https://infuser.odcloud.kr/api/stages/<번호>/api-docs"
python3 scripts/inspect_api.py --docs ./api-docs.json     # 내려받은 파일도 가능

# ② 실제 API 를 호출해 응답 1건의 키를 그대로 덤프 — 가장 확실
python3 scripts/inspect_api.py --probe "https://api.odcloud.kr/api/gov24/v3/serviceList"         --key "발급받은키" --rows 20
```

**②가 최종 근거입니다.** 문서와 실제 응답이 어긋나는 경우가 드물지 않아, 키를 받은 뒤에는
반드시 ②로 다시 확인하세요.

②는 여러 행을 받아 **행마다 값이 전부 다른 필드**를 찾아 줍니다. 고유 ID 의 정의가 그것이기
때문입니다. 다만 제도명·지원내용도 행마다 다르므로, 이름 패턴 점수가 높은 것(`★` 표시)을
우선 보세요. 표본이 클수록 판별이 정확해집니다.

눈으로 고를 때 판단 기준:

| 조건 | 설명 |
|------|------|
| 행마다 값이 다른가 | 같은 값이 반복되면 ID 가 아니다 |
| 값이 안 비는가 | 일부 행이 비면 파일 경로를 만들 수 없다 |
| 값이 안 변하는가 | **가장 중요.** 오늘과 내일 같은 제도가 같은 값을 갖는지. 조회 시각이나 정렬 순서에 따라 바뀌는 일련번호(`rowNum`, `순번`)는 ID 가 아니다 |
| 표기가 안정적인가 | 접두사·자릿수가 들쭉날쭉하면 `slug` 가 흔들린다 |

`rowNum` 류를 ID 로 잡는 것이 가장 흔한 사고입니다. 정렬이 바뀌면 어제의 3번이 오늘 7번이
되어 **모든 제도가 매일 새 페이지로 발행됩니다.** 하루 간격으로 두 번 호출해 같은 제도의
값이 그대로인지 확인하면 확실합니다.

### 지자체까지 넓힐 때

세 가지만 바꾸면 됩니다.

1. 추가 API 활용신청 후 `collect/adapters/__init__.py` 의 `REAL_ADAPTERS` 에 등록
2. `REGION_SCOPE` 를 `national,sido,sigungu` 로 변경 (워크플로우 입력 또는 env)
3. 그 외에는 없음 — 시도 허브는 제도가 생기는 날 자동으로 만들어집니다

범위 밖 제도는 **버려지지 않고 발행만 보류**됩니다. 원천에서 매번 다시 읽으므로,
범위를 넓힌 날 신규로 잡혀 그대로 발행됩니다. 반대로 범위를 좁혀도 **이미 발행된
제도는 계속 추적**되므로 살아 있는 페이지가 낡은 채로 방치되지 않습니다.

`REDESIGN.md` §11 의 미결 항목은 모두 확정됐습니다.
