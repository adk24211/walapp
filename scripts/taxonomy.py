"""분류 체계 — 분야(category) / 대상(audience) / 지역(region).

원천 API의 분류는 행정 편의 기준이라 검색 의도와 어긋난다.
(예: '생애주기 > 청년', '가구상황 > 다문화' 같은 축이 뒤섞여 있다)
따라서 자체 분류로 재매핑하고, 원천 분류는 레코드에 원문 그대로 보관한다.

REDESIGN.md §11-4 결정사항: 자체 재매핑.
"""
from __future__ import annotations

# ─────────────────────────────────────────────────────────────
#  분야 (URL 1차 세그먼트 · 페이지 컬러 키)
# ─────────────────────────────────────────────────────────────
CATEGORIES: dict[str, dict] = {
    "housing": {
        "label": "주거",
        "emoji": "🏠",
        "icon": "ti-home",
        "desc": "월세·전세·공공임대 등 사는 곳과 관련된 지원 제도입니다.",
        "keywords": ["주거", "월세", "전세", "임대", "주택", "보증금", "이사", "housing"],
    },
    "jobs": {
        "label": "일자리·창업",
        "emoji": "💼",
        "icon": "ti-briefcase",
        "desc": "취업 준비, 재직자 지원, 창업 자금까지 일과 관련된 제도입니다.",
        "keywords": ["일자리", "취업", "고용", "구직", "창업", "직업훈련", "인턴", "채용"],
    },
    "care": {
        "label": "양육·돌봄",
        "emoji": "👶",
        "icon": "ti-baby-carriage",
        "desc": "임신·출산부터 육아, 가족 돌봄까지 지원하는 제도입니다.",
        "keywords": ["출산", "임신", "육아", "양육", "보육", "아동", "돌봄",
                     "어린이집", "입양", "위탁", "보호"],
    },
    "health": {
        "label": "건강·의료",
        "emoji": "🩺",
        "icon": "ti-heartbeat",
        "desc": "의료비, 건강검진, 심리 상담 등 건강과 관련된 지원입니다.",
        "keywords": ["의료", "건강", "치료", "진료", "검진", "심리", "정신건강",
                     "약제비", "신체건강", "재활", "간병"],
    },
    "education": {
        "label": "교육·역량",
        "emoji": "📚",
        "icon": "ti-school",
        "desc": "학비, 장학금, 직무 교육 등 배움을 지원하는 제도입니다.",
        "keywords": ["교육", "학자금", "장학", "등록금", "학습", "훈련", "자격증", "역량"],
    },
    "finance": {
        "label": "금융·자산",
        "emoji": "💰",
        "icon": "ti-coin",
        "desc": "목돈 마련, 대출, 세금 환급 등 돈과 관련된 제도입니다.",
        "keywords": ["금융", "적금", "저축", "대출", "자산", "이자", "세액공제",
                     "환급", "장려금", "서민금융", "연금", "수당", "급여", "보험료"],
    },
    "living": {
        "label": "생활·문화",
        "emoji": "🎫",
        "icon": "ti-ticket",
        "desc": "교통, 통신, 문화생활 등 일상의 부담을 덜어 주는 제도입니다.",
        "keywords": ["문화", "여가", "교통", "통신", "요금", "바우처", "할인",
                     "체육", "생활지원", "생활안정", "안전", "위기", "법률"],
    },
}

CATEGORY_KEYS = tuple(CATEGORIES.keys())
DEFAULT_CATEGORY = "living"


# ─────────────────────────────────────────────────────────────
#  대상 (교차 축 — 한 제도가 여러 대상을 가질 수 있다)
# ─────────────────────────────────────────────────────────────
AUDIENCES: dict[str, dict] = {
    "youth": {
        "label": "청년",
        "emoji": "🧑‍🎓",
        "desc": "만 19~39세 청년이 신청할 수 있는 제도를 모았습니다.",
        "keywords": ["청년", "대학생", "사회초년생", "취업준비생", "만 19", "만 34", "만 39"],
    },
    "newlywed": {
        "label": "신혼·예비부부",
        "emoji": "💍",
        "desc": "결혼을 준비하거나 신혼 기간에 있는 가구를 위한 제도입니다.",
        "keywords": ["신혼", "예비부부", "혼인", "결혼"],
    },
    "parent": {
        "label": "양육가정",
        "emoji": "👪",
        "desc": "아이를 키우는 가정이 받을 수 있는 지원입니다.",
        "keywords": ["출산", "임신", "육아", "양육", "다자녀", "한부모", "아동", "보육"],
    },
    "senior": {
        "label": "어르신",
        "emoji": "🧓",
        "desc": "만 65세 이상 어르신을 위한 제도입니다.",
        "keywords": ["노인", "어르신", "고령", "만 65", "경로"],
    },
    "disabled": {
        "label": "장애인",
        "emoji": "♿",
        "desc": "장애인 당사자와 가족을 위한 지원 제도입니다.",
        "keywords": ["장애", "장애인", "중증"],
    },
    "jobseeker": {
        "label": "구직자",
        "emoji": "🔎",
        "desc": "일자리를 찾고 있는 분을 위한 제도입니다.",
        "keywords": ["구직", "실업", "미취업", "취업 준비", "재취업"],
    },
    "lowincome": {
        "label": "저소득 가구",
        "emoji": "🤝",
        "desc": "소득 기준을 충족하면 받을 수 있는 지원입니다.",
        "keywords": ["기초생활", "차상위", "중위소득", "수급자", "저소득"],
    },
    "business": {
        "label": "소상공인",
        "emoji": "🏪",
        "desc": "소상공인·자영업자를 위한 지원 제도입니다.",
        "keywords": ["소상공인", "자영업", "창업", "사업자", "점포"],
    },
    # 아홉 번째로 늘렸다. '결혼이민자 통번역서비스' 를 정리하다 이 축이 통째로
    # 비어 있다는 것이 드러났다 — 그 제도는 여덟 대상 중 어디에도 맞지 않아
    # 대상이 0개였고, 어느 대상 허브에도 뜨지 않았다.
    #
    # ⚠️ '결혼' 이 아니라 여기로 와야 한다. 결혼이민자는 신혼부부가 아니다.
    #    newlywed 의 NOT_AUDIENCE_PHRASES 에 '결혼이민' 이 들어 있는 것이 짝이다.
    "multicultural": {
        "label": "다문화가족",
        "emoji": "🌏",
        "desc": "결혼이민자와 그 가족, 이주배경을 가진 분을 위한 제도입니다.",
        # '외국인' 만으로는 너무 넓다(외국인등록증·외국인근로자 고용 등이 걸린다).
        # 가족·정착을 가리키는 말로 좁힌다.
        "keywords": ["다문화", "결혼이민", "이주배경", "외국인주민", "중도입국"],
    },
}

AUDIENCE_KEYS = tuple(AUDIENCES.keys())

# ── 격일 발행 그룹 ──────────────────────────────────────────
# 테마 8개를 4개씩 두 조로 나눠 하루씩 번갈아 발행한다(조당 테마 1건 = 하루 4건).
# 8개를 매일 채우는 것보다 건당 품질에 쓸 예산이 두 배가 된다. (사용자 확정 사항)
#
# 조 편성 기준은 '검색 수요를 두 조에 고르게 나누는 것'이다. 청년·양육가정처럼
# 수요가 큰 테마를 한쪽에 몰면 그 조가 도는 날만 트래픽이 뛴다.
#
# ⚠️ 테마가 9개가 되어 4+4 로 나뉘지 않는다. 수요가 작은 쪽(2조)에 다문화가족을
#    붙여 5+4 로 둔다. 그 결과 2조가 도는 날은 발행 상한이 6×5+1 = 31건이 된다
#    (1조는 6×4+1 = 25건 그대로).
#
#    31건은 하루 토큰 한도(TPD 200,000 ÷ 건당 차감 약 6,100 ≈ 32건)에 거의
#    닿는다. 여유가 거의 없다는 뜻이지만, 넘으면 그 자리에서 멈추고 그때까지
#    발행한 것은 그대로 배포된다(generate_program.DailyQuotaExhausted).
#    예전처럼 남은 건마다 90초씩 헛기다리지 않는다.
#
#    지금은 다문화가족을 대표 대상으로 갖는 제도가 2건뿐이라 실제로는 훨씬
#    적게 나간다. 이 테마가 6건을 꾸준히 채우기 시작하면 PER_THEME_LIMIT 을
#    한 급 내리는 것을 검토할 것.
AUDIENCE_GROUPS: tuple[tuple[str, ...], ...] = (
    ("youth", "parent", "jobseeker", "senior"),
    ("lowincome", "newlywed", "disabled", "business", "multicultural"),
)


def audience_group(day_index: int) -> tuple[str, ...]:
    """그날 발행할 테마 조. `day_index` 는 date.toordinal() 을 넣는다.

    날짜에서 바로 계산하므로 상태 파일이 필요 없다. 워크플로우가 하루 걸러
    실패해도 다음 실행이 자기 차례를 스스로 안다.
    """
    return AUDIENCE_GROUPS[day_index % len(AUDIENCE_GROUPS)]


def pick_primary_audience(
    audiences: list[str], blob: str = "", from_source: bool = False
) -> str:
    """대표 테마 하나를 고른다.

    한 제도가 청년·구직자 양쪽에 걸치는 일이 흔한데, 발행은 한 번뿐이므로
    '어느 테마의 오늘 1건으로 셀지' 를 정해야 한다. 나머지 테마 허브에는
    `audiences` 로 계속 노출되므로 사라지지 않는다.

    원천이 직접 분류한 값이면 **표기 순서 첫 번째**를 쓴다 (사용자 확정 사항).
    복지로의 lifeArray·trgterIndvdlArray 는 앞쪽이 대표 대상이다.
    키워드 추정이면 본문에 실제로 몇 번 걸렸는지로 고른다 — AUDIENCES 딕셔너리
    선언 순서를 그대로 쓰면 '청년' 이 항상 이겨 대표가 한쪽으로 쏠린다.
    """
    if not audiences:
        return ""
    if from_source:
        return audiences[0]

    def hits(key: str) -> int:
        return sum(1 for kw in AUDIENCES.get(key, {}).get("keywords", []) if kw in blob)

    # 동점이면 선언 순서가 앞선 쪽 — 결과가 실행마다 흔들리지 않게 결정적으로 만든다.
    return max(audiences, key=lambda a: (hits(a), -AUDIENCE_KEYS.index(a)))


# ─────────────────────────────────────────────────────────────
#  지역 (17개 시도 + 전국)
# ─────────────────────────────────────────────────────────────
SIDO: dict[str, str] = {
    "seoul": "서울특별시",
    "busan": "부산광역시",
    "daegu": "대구광역시",
    "incheon": "인천광역시",
    "gwangju": "광주광역시",
    "daejeon": "대전광역시",
    "ulsan": "울산광역시",
    "sejong": "세종특별자치시",
    "gyeonggi": "경기도",
    "gangwon": "강원특별자치도",
    "chungbuk": "충청북도",
    "chungnam": "충청남도",
    "jeonbuk": "전북특별자치도",
    "jeonnam": "전라남도",
    "gyeongbuk": "경상북도",
    "gyeongnam": "경상남도",
    "jeju": "제주특별자치도",
}

SIDO_KEYS = tuple(SIDO.keys())

# 시도 축약 표기 → 키. 원천 데이터가 '서울', '서울시', '서울특별시'를 섞어 쓰므로
# 정식명·축약명·행정 약칭을 모두 받아 준다.
_SIDO_SHORT: dict[str, str] = {
    "서울": "seoul", "부산": "busan", "대구": "daegu", "인천": "incheon",
    "광주": "gwangju", "대전": "daejeon", "울산": "ulsan", "세종": "sejong",
    "경기": "gyeonggi", "강원": "gangwon", "충북": "chungbuk", "충남": "chungnam",
    "전북": "jeonbuk", "전남": "jeonnam", "경북": "gyeongbuk", "경남": "gyeongnam",
    "제주": "jeju",
    "충청북": "chungbuk", "충청남": "chungnam",
    "전라북": "jeonbuk", "전라남": "jeonnam",
    "경상북": "gyeongbuk", "경상남": "gyeongnam",
}

_SIDO_ALIASES: dict[str, str] = dict(_SIDO_SHORT)
for _short, _key in _SIDO_SHORT.items():
    _SIDO_ALIASES[_short + "시"] = _key
    _SIDO_ALIASES[_short + "도"] = _key
for _key, _full in SIDO.items():
    _SIDO_ALIASES[_full] = _key

# 긴 별칭을 먼저 시도해야 '충청북' 이 '충청'류 짧은 값에 가로채이지 않는다.
_SIDO_ALIASES_BY_LEN: tuple[tuple[str, str], ...] = tuple(
    sorted(_SIDO_ALIASES.items(), key=lambda kv: -len(kv[0]))
)

REGION_NATIONAL = "national"


def sido_key(name: str | None) -> str | None:
    """시도 표기를 정규 키로 변환. 매칭 실패 시 None."""
    if not name:
        return None
    text = str(name).strip()
    if text in _SIDO_ALIASES:
        return _SIDO_ALIASES[text]
    # 부분 일치 (예: '경기도 성남시' → gyeonggi)
    for alias, key in _SIDO_ALIASES_BY_LEN:
        if text.startswith(alias):
            return key
    return None


def region_label(scope: str, sido: str | None = None, sigungu: str | None = None) -> str:
    """지역 표시용 라벨."""
    if scope == REGION_NATIONAL:
        return "전국"
    name = SIDO.get(sido or "", sido or "")
    if sigungu:
        return f"{name} {sigungu}"
    return name or "지역"


# ─────────────────────────────────────────────────────────────
#  키워드 기반 분류 (어댑터가 원천 분류를 못 주거나 신뢰할 수 없을 때)
# ─────────────────────────────────────────────────────────────
def classify_category(*texts: str) -> str:
    """텍스트에서 분야를 추정. 가장 많이 매칭된 분야를 고른다."""
    blob = " ".join(t for t in texts if t)
    best, best_score = DEFAULT_CATEGORY, 0
    for key, meta in CATEGORIES.items():
        score = sum(1 for kw in meta["keywords"] if kw in blob)
        if score > best_score:
            best, best_score = key, score
    return best


# ── 대상 추정에서 걸러내는 문맥 ──
#
# 키워드가 본문에 있다고 그 사람이 신청 대상인 것은 아니다. 발행된 126건을
# 전수로 훑어 보니 태그 294개 중에 이런 것들이 섞여 있었다:
#
#   · 전기 요금 복지할인 → 어르신
#     "노인복지주택 … 감액대상에서 **제외합니다**"  — 제외 목록이다
#   · 모두의창업(로컬트랙) → 양육가정
#     "예비창업자를 위한 **보육**공간"  — 창업 인큐베이팅이지 아이 보육이 아니다
#   · 자영업자 실업급여 → 어르신
#     "**노인**장기요양기관을 운영하는 사람"  — 기관 이름이다
#   · 노인장기요양보험 → 저소득
#     "장기요양 **수급자**로 결정될 경우"  — 그 급여를 받는 사람이지 저소득이 아니다
#
# 반대로 놓치면 안 되는 것들이 훨씬 많다. '다자녀 가구 금리우대', '장애인 가구
# 우대', '구직급여 수급자격' 처럼 본문 깊숙이 적힌 자격 경로가 진짜인 경우가
# 절반이 넘는다. **받을 수 있는 사람이 제도를 못 찾는 쪽이 더 나쁘므로**,
# 애매하면 남긴다. 여기 넣는 것은 '이건 신청 대상이 아니다' 가 분명한 것만이다.

# ① 이 문구 안의 키워드는 세지 않는다. 그 대상을 볼 때만 blob 에서 지운다.
#
# ⚠️ **대상별로 나눠 둔 것이 핵심이다.** 처음엔 하나의 공용 목록으로 두고
#    blob 에서 통째로 지웠는데, 한 문구에 서로 다른 대상의 키워드가 함께 들어
#    있는 경우가 많아 멀쩡한 태그까지 날아갔다. "실업급여 수급자" 를 지우면
#    '수급자'(저소득 오분류)만 사라지는 게 아니라 '실업'(구직자 — 이건 맞는
#    태그다)까지 사라진다. 실제로 그렇게 행복주택·심리안정지원의 구직자
#    태그가 잘못 제거됐다.
NOT_AUDIENCE_PHRASES: dict[str, tuple[str, ...]] = {
    # '보육' 이 창업 인큐베이팅을 뜻하는 자리
    "parent": ("보육공간", "창업보육", "보육센터"),
    # 결혼이민자는 신혼부부가 아니다
    "newlywed": ("결혼이민",),
    # '사업자' 가 소상공인을 뜻하지 않는 자리
    "business": ("공공사업자", "사업자등록 없"),
    # 법령·기관 이름 안의 '노인'
    "senior": ("노인복지법", "노인복지주택", "노인장기요양기관", "노인복지시설"),
    "disabled": ("장애인복지법",),
    # 다른 급여를 받는 사람이라는 뜻의 '수급자' — 소득 기준이 아니다.
    # (같은 문구의 '실업'·'구직' 은 구직자 태그로 살아 있어야 하므로 여기에만 둔다)
    "lowincome": ("장기요양 수급자", "실업급여 수급자", "실업급여수급자",
                  "구직급여 수급자", "수급자에게", "가족요양비"),
}

# ② 이 말이 키워드 가까이에 있으면 그 자리는 세지 않는다(제외·부정 문맥).
#    키워드가 나오는 자리마다 확인해서, 전부 부정 문맥이면 태그를 주지 않는다.
NEGATION_MARKERS = ("제외", "미지급", "지급하지", "해당하지", "아니한", "아닌 ", "불가")
NEGATION_WINDOW = 30   # 앞뒤 글자 수


def _counts_as_audience(blob: str, keyword: str) -> bool:
    """이 키워드가 '신청 대상' 을 가리키는 자리에 한 번이라도 나오는가."""
    start = 0
    while True:
        i = blob.find(keyword, start)
        if i < 0:
            return False
        window = blob[max(0, i - NEGATION_WINDOW): i + len(keyword) + NEGATION_WINDOW]
        if not any(m in window for m in NEGATION_MARKERS):
            return True          # 부정 문맥이 아닌 자리가 하나라도 있으면 인정
        start = i + 1


def classify_audiences(*texts: str) -> list[str]:
    """텍스트에서 대상을 추정. 복수 매칭 가능하며, 매칭이 없으면 빈 리스트.

    단순 부분일치가 아니다 — 위 NOT_AUDIENCE_PHRASES·NEGATION_MARKERS 참고.
    규칙을 바꾸면 scripts/check_audience.py 를 먼저 돌린다.
    """
    blob = " ".join(t for t in texts if t)
    found = []
    for key, meta in AUDIENCES.items():
        scoped = blob
        for phrase in NOT_AUDIENCE_PHRASES.get(key, ()):
            scoped = scoped.replace(phrase, " ")
        if any(_counts_as_audience(scoped, kw) for kw in meta["keywords"]):
            found.append(key)
    return found


# ─────────────────────────────────────────────────────────────
#  복지로 원천 분류 → 자체 분류 매핑
# ─────────────────────────────────────────────────────────────
# 중앙부처복지서비스(15090532)는 응답에 원천이 직접 분류한 값을 준다.
#   intrsThemaArray   관심주제  예: "생활지원,일자리,서민금융"
#   lifeArray         생애주기  예: "청년,중장년,노년"
#   trgterIndvdlArray 가구유형  예: "장애인,저소득"
# 본문 키워드로 추정하는 것보다 정확하므로 이쪽을 우선한다.
# 표에 없는 값이 오면 기존 키워드 추정으로 넘어간다(안전한 실패).

BOKJIRO_THEME_TO_CATEGORY: dict[str, str] = {
    "신체건강": "health",
    "정신건강": "health",
    "생활지원": "living",
    "주거": "housing",
    "일자리": "jobs",
    "문화·여가": "living",
    "문화여가": "living",
    "안전·위기": "living",
    "안전위기": "living",
    "임신·출산": "care",
    "임신출산": "care",
    "보육": "care",
    "교육": "education",
    "입양·위탁": "care",
    "입양위탁": "care",
    "보호·돌봄": "care",
    "보호돌봄": "care",
    "서민금융": "finance",
    "법률": "living",
}

BOKJIRO_LIFE_TO_AUDIENCE: dict[str, str] = {
    "영유아": "parent",
    "아동": "parent",
    "청년": "youth",
    "노년": "senior",
    # '청소년'·'중장년' 은 우리 대상 축에 대응하는 항목이 없어 매핑하지 않는다.
    # 억지로 청년/어르신에 붙이면 대상별 허브가 부정확해진다.
}

BOKJIRO_TARGET_TO_AUDIENCE: dict[str, str] = {
    "장애인": "disabled",
    "저소득": "lowincome",
    "다자녀": "parent",
    "한부모·조손": "parent",
    "한부모조손": "parent",
    "임신·출산": "parent",
    "임신출산": "parent",
    "노인": "senior",
    # '보훈대상자' 는 대응 항목이 없어 매핑하지 않는다.
    #
    # '다문화·탈북민' 은 이제 multicultural 이 생겼지만 **그래도 매핑하지 않는다.**
    # 원천이 둘을 한 항목으로 묶어 주는데, 탈북민만 대상인 제도까지 '다문화가족'
    # 으로 찍히기 때문이다. 위 '청소년'·'중장년' 과 같은 이유다 — 억지로 붙이면
    # 대상별 허브가 부정확해진다. 키워드 경로('다문화', '결혼이민')는 문서 안의
    # 실제 표현을 보므로 이 문제가 없다.
}


def _split_codes(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").replace("|", ",").split(",") if part.strip()]


# '생활지원' 은 어디에도 안 들어가는 것을 담는 포괄 분류다. 다른 주제가 함께 오면
# 그쪽이 실제 성격을 더 잘 나타낸다.
# 예: "생활지원,일자리,서민금융" 인 장애인자립자금대여를 '생활·문화' 로 보내면
#     일자리 허브에서 사라진다.
BOKJIRO_GENERIC_THEMES = frozenset({"생활지원"})


def map_bokjiro(thema: str = "", life: str = "", target: str = "") -> tuple[str | None, list[str]]:
    """복지로 원천 분류 → (분야, 대상 목록). 매핑 실패 시 분야는 None.

    분야는 포괄 주제를 뺀 뒤 **원천 표기 순서에서 첫 번째**를 쓴다.
    복수 주제가 오는 경우가 흔하고(예: "생활지원,일자리,서민금융"), 앞쪽이 대표 주제라고
    보는 것이 원천 표기 순서와 맞다.
    """
    mapped = [BOKJIRO_THEME_TO_CATEGORY[code]
              for code in _split_codes(thema)
              if code in BOKJIRO_THEME_TO_CATEGORY]
    specific = [BOKJIRO_THEME_TO_CATEGORY[code]
                for code in _split_codes(thema)
                if code in BOKJIRO_THEME_TO_CATEGORY and code not in BOKJIRO_GENERIC_THEMES]
    ordered = specific or mapped
    category = ordered[0] if ordered else None

    audiences: list[str] = []
    for code in _split_codes(life):
        mapped = BOKJIRO_LIFE_TO_AUDIENCE.get(code)
        if mapped and mapped not in audiences:
            audiences.append(mapped)
    for code in _split_codes(target):
        mapped = BOKJIRO_TARGET_TO_AUDIENCE.get(code)
        if mapped and mapped not in audiences:
            audiences.append(mapped)

    return category, audiences


# ─────────────────────────────────────────────────────────────
#  Jekyll 내보내기
# ─────────────────────────────────────────────────────────────
def export_for_jekyll() -> dict:
    """`_data/taxonomy.json` 내용.

    라벨·이모지·설명을 파이썬과 Liquid 양쪽에서 쓰므로 진실 공급원을 하나로 둔다.
    템플릿이 하드코딩한 한글 라벨을 갖지 않게 하려는 목적이다.
    """
    return {
        "categories": {
            key: {k: v for k, v in meta.items() if k != "keywords"}
            for key, meta in CATEGORIES.items()
        },
        "category_order": list(CATEGORY_KEYS),
        "audiences": {
            key: {k: v for k, v in meta.items() if k != "keywords"}
            for key, meta in AUDIENCES.items()
        },
        "audience_order": list(AUDIENCE_KEYS),
        "sido": dict(SIDO),
        "sido_order": list(SIDO_KEYS),
    }
