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
}

AUDIENCE_KEYS = tuple(AUDIENCES.keys())


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


def classify_audiences(*texts: str) -> list[str]:
    """텍스트에서 대상을 추정. 복수 매칭 가능하며, 매칭이 없으면 빈 리스트."""
    blob = " ".join(t for t in texts if t)
    return [key for key, meta in AUDIENCES.items()
            if any(kw in blob for kw in meta["keywords"])]


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
