"""목(mock) 데이터 어댑터 — API 키 없이 파이프라인 전체를 검증하기 위한 개발용 소스.

⚠️ 여기 담긴 값은 실제 제도 정보가 아니다. 형태만 실제와 비슷하게 맞춘 가짜 데이터다.
   이 어댑터가 만든 레코드는 `is_mock=True` 가 붙고, 그 결과로
     · 제도 페이지 상단에 경고 배너가 렌더되고
     · <meta name="robots" content="noindex"> 가 삽입되며
     · 생성물이 git 에 커밋되지 않는다 (.gitignore 의 `_programs/`)
   실 API 전환 시 `collect/adapters/bojo24.py` 를 채우고 MOCK_DATA=0 으로 돌리면 된다.

데이터 구성 의도 — 파이프라인의 분기를 전부 밟도록 짰다:
  · 7개 분야 전부 등장
  · 전국 / 시도 / 시군구 3단계 지역
  · 상시 접수 · 마감일 있음 · 이미 마감됨
  · 필수 필드 누락 레코드 (격리 동작 확인)
  · 서로 다른 소스에 중복 등재된 유사 제도 (유사도 검토 동작 확인)
"""
from __future__ import annotations

from .base import BaseAdapter

# (source_id, name, kwargs)
_ROWS: list[tuple[str, str, dict]] = [
    # ── 주거 ────────────────────────────────────────────────
    ("H0001", "청년 월세 한시 특별지원", dict(
        org="국토교통부",
        target_raw="만 19~34세 무주택 청년 중 부모와 별도 거주하며 임차보증금 5천만 원 이하, 월세 60만 원 이하 주택에 거주하는 사람",
        benefit_raw="월 최대 20만 원을 최대 12개월간 나누어 지원합니다. 실제 납부한 월세 범위 안에서만 지급됩니다.",
        criteria_raw="청년 본인 가구 기준 중위소득 60% 이하이면서 재산가액 1억 2천만 원 이하, 원가구는 중위소득 100% 이하이면서 재산가액 4억 7천만 원 이하여야 합니다.",
        how_to_raw="복지로 누리집 또는 모바일 앱에서 온라인 신청하거나, 주소지 관할 행정복지센터를 방문해 신청합니다. 신청 후 소득·재산 조사에 약 45일이 걸립니다.",
        documents_raw=["월세 지원 신청서", "임대차계약서 사본", "월세 이체 증빙 서류", "가족관계증명서", "통장 사본"],
        apply_start="2026-03-02", apply_end="2027-02-26",
        apply_url="https://www.bokjiro.go.kr/", official_url="https://www.molit.go.kr/",
        category="housing", audiences=["youth", "lowincome"],
        source_category_raw="생애주기 > 청년 / 주거",
    )),
    ("H0002", "신혼부부 전세임대 주택 공급", dict(
        org="한국토지주택공사",
        target_raw="혼인 신고일 기준 7년 이내 신혼부부 또는 6개월 이내 혼인 예정인 예비 신혼부부로서 무주택 세대구성원",
        benefit_raw="입주 대상자가 원하는 주택을 고르면 기관이 집주인과 전세계약을 맺고 저렴하게 재임대합니다. 전세보증금의 5% 정도만 부담하면 됩니다.",
        criteria_raw="가구 월평균 소득이 전년도 도시근로자 가구원수별 월평균 소득의 70% 이하여야 하며, 총자산은 기준액 이하여야 합니다.",
        how_to_raw="LH 청약플러스 누리집에서 모집 공고를 확인한 뒤 온라인으로 신청합니다. 공고는 연 2~3회 올라옵니다.",
        documents_raw=["주민등록등본", "가족관계증명서", "혼인관계증명서", "소득 증빙 서류"],
        always=True,
        apply_url="https://apply.lh.or.kr/", official_url="https://www.lh.or.kr/",
        category="housing", audiences=["newlywed"],
        source_category_raw="주거 > 임대주택",
    )),
    ("H0003", "서울시 청년 부동산 중개보수 지원", dict(
        org="서울특별시",
        target_raw="서울시에 거주하는 만 19~39세 청년 1인 가구로, 거래금액 2억 원 이하 주택을 임차한 사람",
        benefit_raw="실제 지출한 중개보수와 등기 대행 수수료를 최대 40만 원까지 지원합니다.",
        criteria_raw="신청일 기준 서울시에 주민등록이 되어 있어야 하며, 연 소득 4천만 원 이하여야 합니다.",
        how_to_raw="청년몽땅정보통 누리집에서 온라인으로만 신청받습니다. 분기별로 접수 기간이 따로 공고됩니다.",
        documents_raw=["임대차계약서 사본", "중개보수 영수증", "주민등록초본", "소득금액증명원"],
        apply_start="2026-07-01", apply_end="2026-09-30",
        region_scope="sido", sido="seoul",
        category="housing", audiences=["youth"],
        source_category_raw="주거 > 청년",
    )),
    ("H0004", "경기도 청년 보증금 이자 지원", dict(
        org="경기도",
        target_raw="경기도에 거주하는 만 19~34세 청년 임차인",
        benefit_raw="전월세 보증금 대출 이자의 일부를 최대 연 2% 범위에서 지원합니다.",
        criteria_raw="연 소득 5천만 원 이하이면서 대출 잔액이 남아 있어야 합니다.",
        how_to_raw="경기도 일자리재단 누리집에서 신청합니다.",
        documents_raw=["대출 잔액 증명서", "임대차계약서 사본", "주민등록초본"],
        apply_start="2026-02-01", apply_end="2026-05-31",
        region_scope="sido", sido="gyeonggi",
        category="housing", audiences=["youth"],
        source_category_raw="주거 > 금융",
    )),

    # ── 일자리·창업 ─────────────────────────────────────────
    ("J0001", "청년일자리도약장려금", dict(
        org="고용노동부",
        target_raw="5인 이상 우선지원대상기업이 6개월 이상 실업 상태인 만 15~34세 청년을 정규직으로 채용한 경우",
        benefit_raw="채용한 기업에 1년간 최대 720만 원을 지원하고, 근속 2년을 채우면 청년 본인에게 480만 원을 추가 지급합니다.",
        criteria_raw="채용일 기준 고용보험 피보험자 수가 5인 이상이어야 하며, 채용 전 3개월 이내 감원이 없어야 합니다.",
        how_to_raw="고용24 누리집에서 사업 참여를 신청한 뒤 운영기관 심사를 거쳐 채용을 진행합니다.",
        documents_raw=["사업 참여 신청서", "사업자등록증 사본", "근로계약서 사본", "고용보험 피보험자격 취득 내역"],
        always=True,
        apply_url="https://www.work24.go.kr/", official_url="https://www.moel.go.kr/",
        category="jobs", audiences=["youth", "jobseeker", "business"],
        source_category_raw="일자리 > 고용장려금",
    )),
    ("J0002", "국민취업지원제도 1유형", dict(
        org="고용노동부",
        target_raw="15~69세 구직자 중 가구 단위 중위소득 60% 이하이면서 재산 4억 원 이하인 사람",
        benefit_raw="구직촉진수당을 월 50만 원씩 최대 6개월간 지급하고, 부양가족이 있으면 1인당 월 10만 원을 더합니다. 취업 지원 서비스도 함께 제공합니다.",
        criteria_raw="최근 2년 안에 100일 또는 800시간 이상 취업한 경험이 있어야 합니다. 경험이 없어도 선발형으로 신청할 수 있습니다.",
        how_to_raw="고용24 누리집에서 온라인 신청하거나 거주지 관할 고용센터를 방문합니다. 신청 후 1개월 이내에 수급 자격 결정을 통보받습니다.",
        documents_raw=["참여 신청서", "개인정보 수집 이용 동의서", "가구원 소득·재산 신고서"],
        always=True,
        apply_url="https://www.work24.go.kr/", official_url="https://www.moel.go.kr/",
        category="jobs", audiences=["jobseeker", "lowincome"],
        source_category_raw="일자리 > 취업지원",
    )),
    ("J0003", "소상공인 정책자금 융자", dict(
        org="중소벤처기업부",
        target_raw="상시 근로자 수와 매출액이 소상공인 기준을 충족하는 사업자",
        benefit_raw="운전자금은 업체당 최대 7천만 원, 시설자금은 최대 5억 원까지 낮은 금리로 빌려줍니다.",
        criteria_raw="사업자등록을 마치고 실제 영업 중이어야 하며, 신용도와 사업성 평가를 통과해야 합니다.",
        how_to_raw="소상공인시장진흥공단 누리집에서 온라인 신청 후 지역센터 상담을 거칩니다.",
        documents_raw=["사업자등록증 사본", "부가가치세 과세표준증명원", "소득금액증명원", "임대차계약서 사본"],
        always=True,
        category="jobs", audiences=["business"],
        source_category_raw="창업 > 자금",
    )),
    ("J0004", "내일배움카드 직업훈련 지원", dict(
        org="고용노동부",
        target_raw="구직자, 재직자, 자영업자 등 직업훈련이 필요한 국민 대부분",
        benefit_raw="1인당 300만 원에서 500만 원까지 훈련비를 지원합니다. 훈련 과정에 따라 자기부담률이 15~55% 사이에서 달라집니다.",
        criteria_raw="공무원, 사립학교 교직원, 월 임금 300만 원 이상 대규모기업 재직자 등은 제외됩니다.",
        how_to_raw="고용24 누리집에서 카드를 발급받은 뒤, 원하는 훈련 과정을 검색해 수강 신청합니다.",
        documents_raw=["신청서", "신분증", "훈련 과정 수강 신청 내역"],
        always=True,
        category="jobs", audiences=["jobseeker", "youth"],
        source_category_raw="일자리 > 직업훈련",
    )),
    ("J0005", "부산시 청년 일경험 프로그램", dict(
        org="부산광역시",
        target_raw="부산에 거주하는 만 18~34세 미취업 청년",
        benefit_raw="3개월간 지역 기업에서 일할 기회를 제공하고 월 활동비 180만 원을 지급합니다.",
        criteria_raw="신청일 기준 고용보험에 가입되어 있지 않아야 하며, 부산시에 주민등록이 되어 있어야 합니다.",
        how_to_raw="부산일자리정보망에서 참여 기업을 확인하고 온라인으로 지원합니다.",
        documents_raw=["참여 신청서", "주민등록초본", "졸업증명서 또는 재학증명서"],
        apply_start="2026-04-01", apply_end="2026-06-30",
        region_scope="sido", sido="busan",
        category="jobs", audiences=["youth", "jobseeker"],
        source_category_raw="일자리 > 청년",
    )),

    # ── 양육·돌봄 ───────────────────────────────────────────
    ("C0001", "첫만남이용권", dict(
        org="보건복지부",
        target_raw="출생 신고를 마치고 주민등록번호를 받은 모든 아동",
        benefit_raw="첫째 아이는 200만 원, 둘째 아이부터는 300만 원을 국민행복카드 바우처로 지급합니다.",
        criteria_raw="소득이나 재산과 무관하게 출생 아동이면 모두 받을 수 있습니다.",
        how_to_raw="복지로 온라인 신청 또는 주소지 행정복지센터 방문 신청이 가능합니다. 출생 신고와 함께 처리할 수 있습니다.",
        documents_raw=["신청서", "국민행복카드", "출생증명서"],
        always=True,
        apply_url="https://www.bokjiro.go.kr/",
        category="care", audiences=["parent"],
        source_category_raw="생애주기 > 영유아",
    )),
    ("C0002", "아이돌봄 서비스 지원", dict(
        org="여성가족부",
        target_raw="만 12세 이하 아동을 둔 맞벌이 가정, 한부모 가정, 다자녀 가정 등",
        benefit_raw="아이돌보미가 가정을 방문해 아동을 돌봅니다. 소득 구간에 따라 이용 요금의 15~85%를 정부가 부담합니다.",
        criteria_raw="가구 소득이 기준 중위소득 150% 이하이면 정부 지원 비율이 높아집니다. 그 이상이면 전액 본인 부담으로 이용할 수 있습니다.",
        how_to_raw="아이돌봄서비스 누리집에서 회원 가입 후 신청하고, 행정복지센터에서 정부지원 자격을 판정받습니다.",
        documents_raw=["아이돌봄 서비스 신청서", "가족관계증명서", "맞벌이 증빙 서류"],
        always=True,
        category="care", audiences=["parent", "lowincome"],
        source_category_raw="가족 > 돌봄",
    )),
    ("C0003", "부모급여", dict(
        org="보건복지부",
        target_raw="만 0~1세 아동을 양육하는 가정",
        benefit_raw="0세 아동은 월 100만 원, 1세 아동은 월 50만 원을 현금으로 지급합니다. 어린이집을 이용하면 보육료 바우처로 대체 지급됩니다.",
        criteria_raw="소득과 재산에 관계없이 해당 연령 아동을 양육하면 받을 수 있습니다.",
        how_to_raw="복지로에서 온라인 신청하거나 주소지 행정복지센터에 방문합니다. 출생일 포함 60일 안에 신청해야 출생월부터 소급 지급됩니다.",
        documents_raw=["신청서", "통장 사본", "신분증"],
        always=True,
        apply_url="https://www.bokjiro.go.kr/",
        category="care", audiences=["parent"],
        source_category_raw="생애주기 > 영유아",
    )),
    ("C0004", "가족돌봄청년 자기돌봄비 지원", dict(
        org="보건복지부",
        target_raw="아픈 가족을 돌보는 만 13~34세 청년",
        benefit_raw="연 200만 원 범위에서 본인의 학업·취업·건강 관리에 쓸 수 있는 자기돌봄비를 지원합니다.",
        criteria_raw="가구 소득이 기준 중위소득 100% 이하이면서 실제 돌봄을 수행하고 있음이 확인되어야 합니다.",
        how_to_raw="주소지 행정복지센터에 방문 신청하면 담당자가 돌봄 부담 정도를 조사합니다.",
        documents_raw=["신청서", "가족관계증명서", "돌봄 대상자 진단서", "소득 증빙 서류"],
        apply_start="2026-01-02", apply_end="2026-11-30",
        category="care", audiences=["youth", "lowincome"],
        source_category_raw="가족 > 청년",
    )),

    # ── 건강·의료 ───────────────────────────────────────────
    ("M0001", "재난적의료비 지원", dict(
        org="보건복지부",
        target_raw="과도한 의료비 지출로 경제적 어려움을 겪는 기준 중위소득 100% 이하 가구",
        benefit_raw="본인부담 의료비의 50~80%를 연간 최대 5천만 원까지 지원합니다.",
        criteria_raw="재산 합계액이 7억 원 이하여야 하며, 질환별로 정해진 의료비 기준을 넘겨야 합니다.",
        how_to_raw="국민건강보험공단 지사에 방문하거나 병원 내 사회복지팀을 통해 신청합니다. 퇴원일 다음 날부터 180일 안에 신청해야 합니다.",
        documents_raw=["지원 신청서", "진료비 계산서·영수증", "진단서", "가족관계증명서", "소득·재산 증빙 서류"],
        always=True,
        category="health", audiences=["lowincome"],
        source_category_raw="보건의료 > 의료비",
    )),
    ("M0002", "청년 마음건강 지원 바우처", dict(
        org="보건복지부",
        target_raw="만 19~34세 청년 중 심리 상담이 필요한 사람",
        benefit_raw="전문 심리 상담을 회당 8만 원 범위에서 10회까지 지원합니다. 본인부담금은 소득 구간에 따라 0~2만 원입니다.",
        criteria_raw="소득 기준 없이 신청할 수 있으나, 예산 범위 안에서 우선순위에 따라 선정합니다.",
        how_to_raw="주소지 행정복지센터에 방문 신청한 뒤 바우처 카드를 발급받아 제공기관에서 이용합니다.",
        documents_raw=["신청서", "신분증", "우선순위 증빙 서류"],
        apply_start="2026-01-15", apply_end="2026-10-31",
        category="health", audiences=["youth"],
        source_category_raw="보건의료 > 정신건강",
    )),
    ("M0003", "국가 암검진 사업", dict(
        org="보건복지부",
        target_raw="건강보험 가입자 중 검진 대상 연령에 해당하는 사람과 의료급여 수급권자",
        benefit_raw="위암·대장암·간암·유방암·자궁경부암·폐암 검진 비용의 90~100%를 지원합니다.",
        criteria_raw="암 종류별로 대상 연령과 검진 주기가 다릅니다. 건강보험료 상위 50%는 본인부담금 10%가 발생합니다.",
        how_to_raw="국민건강보험공단이 보내는 검진표를 받은 뒤 지정 검진기관에 예약해 방문합니다.",
        documents_raw=["신분증", "국가암검진 대상자 확인서"],
        always=True,
        category="health", audiences=["senior"],
        source_category_raw="보건의료 > 건강검진",
    )),

    # ── 교육·역량 ───────────────────────────────────────────
    ("E0001", "국가장학금 1유형", dict(
        org="교육부",
        target_raw="국내 대학에 재학 중인 소득 8구간 이하 학부생",
        benefit_raw="소득 구간에 따라 연간 최대 570만 원까지 등록금을 지원합니다.",
        criteria_raw="직전 학기 성적이 100점 만점에 80점 이상이어야 하며, 12학점 이상 이수해야 합니다. 기초·차상위 계층은 성적 기준이 완화됩니다.",
        how_to_raw="한국장학재단 누리집에서 학기별 신청 기간에 온라인으로 신청하고 가구원 동의 절차를 마칩니다.",
        documents_raw=["신청서", "가족관계증명서", "가구원 정보 제공 동의서"],
        apply_start="2026-05-20", apply_end="2026-06-19",
        official_url="https://www.kosaf.go.kr/",
        category="education", audiences=["youth", "lowincome"],
        source_category_raw="교육 > 장학금",
    )),
    ("E0002", "K-MOOC 온라인 강좌", dict(
        org="교육부",
        target_raw="학습을 원하는 국민 누구나",
        benefit_raw="대학 수준의 온라인 강좌를 무료로 수강할 수 있고, 이수하면 이수증을 발급합니다.",
        criteria_raw="별도의 자격 요건이 없습니다.",
        how_to_raw="K-MOOC 누리집에 회원 가입한 뒤 원하는 강좌를 수강 신청합니다.",
        documents_raw=[],
        always=True,
        category="education", audiences=["youth", "jobseeker"],
        source_category_raw="교육 > 평생학습",
    )),
    ("E0003", "평생교육 이용권", dict(
        org="교육부",
        target_raw="만 19세 이상 성인 중 기준 중위소득 65% 이하 가구원",
        benefit_raw="1인당 연간 35만 원의 평생교육 강좌 수강비를 지원합니다.",
        criteria_raw="예산 범위 안에서 소득이 낮은 순으로 선정합니다.",
        how_to_raw="평생교육바우처 누리집에서 신청 기간에 온라인 신청합니다.",
        documents_raw=["신청서", "건강보험료 납부확인서"],
        apply_start="2026-02-05", apply_end="2026-03-15",
        category="education", audiences=["lowincome"],
        source_category_raw="교육 > 평생학습",
    )),

    # ── 금융·자산 ───────────────────────────────────────────
    ("F0001", "청년도약계좌", dict(
        org="금융위원회",
        target_raw="만 19~34세 청년 중 직전 과세기간 총급여가 7,500만 원 이하인 사람",
        benefit_raw="매월 최대 70만 원까지 5년간 납입하면 소득 구간별로 정부가 기여금을 더해 주고, 이자소득에 세금을 매기지 않습니다.",
        criteria_raw="가구 소득이 기준 중위소득 250% 이하여야 하며, 직전 3개 과세기간 중 1회 이상 금융소득종합과세 대상이면 가입할 수 없습니다.",
        how_to_raw="취급 은행 앱에서 매월 정해진 기간에 가입 신청하면 서민금융진흥원이 자격을 심사합니다.",
        documents_raw=["별도 서류 없이 앱에서 비대면 심사"],
        always=True,
        category="finance", audiences=["youth"],
        source_category_raw="금융 > 자산형성",
    )),
    ("F0002", "근로장려금", dict(
        org="국세청",
        target_raw="소득이 적은 근로자, 사업자, 종교인 가구",
        benefit_raw="가구 유형에 따라 연간 최대 165만 원에서 330만 원까지 지급합니다.",
        criteria_raw="가구원 재산 합계가 2억 4천만 원 미만이어야 하며, 가구 유형별 소득 상한을 넘지 않아야 합니다.",
        how_to_raw="국세청 홈택스 또는 손택스 앱에서 신청합니다. 안내문을 받았다면 ARS 전화로도 신청할 수 있습니다.",
        documents_raw=["신청서", "소득 증빙 서류"],
        apply_start="2026-05-01", apply_end="2026-05-31",
        category="finance", audiences=["lowincome"],
        source_category_raw="금융 > 세제지원",
    )),
    ("F0003", "청년내일저축계좌", dict(
        org="보건복지부",
        target_raw="만 19~34세 근로 청년 중 가구 소득이 기준 중위소득 100% 이하인 사람",
        benefit_raw="본인이 월 10만 원을 저축하면 정부가 월 10만 원에서 30만 원을 더해 3년간 적립합니다.",
        criteria_raw="근로·사업소득이 월 50만 원을 넘고 250만 원 이하여야 하며, 가구 재산이 지역별 기준 이하여야 합니다.",
        how_to_raw="복지로 또는 주소지 행정복지센터에서 모집 기간에 신청합니다. 모집은 연 1회입니다.",
        documents_raw=["신청서", "근로 증빙 서류", "가족관계증명서", "통장 사본"],
        apply_start="2026-05-02", apply_end="2026-05-21",
        category="finance", audiences=["youth", "lowincome"],
        source_category_raw="금융 > 자산형성",
    )),
    ("F0004", "햇살론 유스", dict(
        org="서민금융진흥원",
        target_raw="만 19~34세 대학생, 미취업 청년, 사회초년생",
        benefit_raw="연 3%대 금리로 최대 1,200만 원까지 생활자금을 빌려줍니다.",
        criteria_raw="연 소득 3,500만 원 이하이면서 신용평점 하위 20%에 해당하거나 소득이 적은 청년이어야 합니다.",
        how_to_raw="서민금융진흥원 앱에서 사전 심사를 받은 뒤 취급 은행에서 약정을 체결합니다.",
        documents_raw=["신분증", "재직 또는 재학 증빙 서류", "소득 증빙 서류"],
        always=True,
        category="finance", audiences=["youth"],
        source_category_raw="금융 > 대출",
    )),

    # ── 생활·문화 ───────────────────────────────────────────
    ("L0001", "문화누리카드", dict(
        org="문화체육관광부",
        target_raw="만 6세 이상 기초생활수급자와 차상위계층",
        benefit_raw="1인당 연간 14만 원을 공연·전시·영화·도서·여행·체육 활동에 쓸 수 있습니다.",
        criteria_raw="주민등록상 나이가 만 6세 이상이면서 수급 자격이 유지되어야 합니다.",
        how_to_raw="문화누리카드 누리집이나 주소지 행정복지센터에서 발급받습니다. 전년도 발급자는 자동 재충전됩니다.",
        documents_raw=["신분증", "발급 신청서"],
        apply_start="2026-02-03", apply_end="2026-11-28",
        category="living", audiences=["lowincome"],
        source_category_raw="문화 > 바우처",
    )),
    ("L0002", "청년 문화예술패스", dict(
        org="문화체육관광부",
        target_raw="2006년 또는 2007년에 태어난 청년",
        benefit_raw="공연과 전시 관람에 쓸 수 있는 최대 20만 원의 이용권을 지급합니다.",
        criteria_raw="소득 기준 없이 해당 출생연도에 해당하면 신청할 수 있으며, 예산 소진 시 마감됩니다.",
        how_to_raw="문화예술패스 누리집에서 제휴 예매처를 고른 뒤 본인 인증을 거쳐 발급받습니다.",
        documents_raw=["본인 명의 휴대전화 또는 공동인증서"],
        apply_start="2026-08-10", apply_end="2026-12-31",
        category="living", audiences=["youth"],
        source_category_raw="문화 > 청년",
    )),
    ("L0003", "K-패스 대중교통비 환급", dict(
        org="국토교통부",
        target_raw="월 15회 이상 대중교통을 이용하는 만 19세 이상 국민",
        benefit_raw="이용 금액의 20~53%를 다음 달에 환급합니다. 청년과 저소득층은 환급률이 더 높습니다.",
        criteria_raw="사업에 참여하는 지방자치단체에 주민등록이 되어 있어야 합니다.",
        how_to_raw="K-패스 누리집이나 앱에서 카드를 발급받아 회원 가입하면 자동으로 적립됩니다.",
        documents_raw=["본인 명의 교통카드"],
        always=True,
        category="living", audiences=["youth", "lowincome"],
        source_category_raw="교통 > 요금지원",
    )),
    ("L0004", "에너지바우처", dict(
        org="산업통상자원부",
        target_raw="생계·의료·주거·교육 급여 수급 가구 중 노인, 영유아, 장애인 등이 포함된 가구",
        benefit_raw="가구원 수에 따라 여름철과 겨울철 냉난방 요금을 최대 70만 원 상당 지원합니다.",
        criteria_raw="주민등록표상 세대원 중 더위·추위에 취약한 대상자가 포함되어 있어야 합니다.",
        how_to_raw="주소지 행정복지센터에 방문 신청하거나 복지로에서 온라인 신청합니다.",
        documents_raw=["신청서", "신분증", "대상자 확인 서류"],
        apply_start="2026-05-27", apply_end="2026-12-31",
        category="living", audiences=["lowincome", "senior", "disabled"],
        source_category_raw="생활 > 에너지",
    )),
    ("L0005", "성남시 청년 교통비 지원", dict(
        org="경기도 성남시",
        target_raw="성남시에 1년 이상 거주한 만 19~24세 청년",
        benefit_raw="연간 최대 12만 원의 교통비를 지역화폐로 지급합니다.",
        criteria_raw="신청일 기준 성남시에 주민등록이 되어 있어야 하며, 다른 교통비 지원 사업과 중복해서 받을 수 없습니다.",
        how_to_raw="성남시 청년정책 누리집에서 반기별로 신청합니다.",
        documents_raw=["신청서", "주민등록초본", "지역화폐 카드"],
        apply_start="2026-08-01", apply_end="2026-08-31",
        region_scope="sigungu", sido="gyeonggi", sigungu="성남시",
        category="living", audiences=["youth"],
        source_category_raw="교통 > 청년",
    )),

    # ── 이미 마감된 제도 (status=closed 분기 확인용) ────────
    ("L0006", "2026 상반기 지역사랑상품권 할인 판매", dict(
        org="행정안전부",
        target_raw="지역사랑상품권을 발행하는 지방자치단체 주민",
        benefit_raw="액면가의 5~10%를 할인한 금액으로 상품권을 구매할 수 있습니다.",
        criteria_raw="지자체별로 1인당 월 구매 한도가 다르게 정해져 있습니다.",
        how_to_raw="지자체 지역화폐 앱 또는 지정 판매처에서 구매합니다.",
        documents_raw=["본인 명의 계좌", "신분증"],
        apply_start="2026-01-02", apply_end="2026-06-30",
        category="living", audiences=["lowincome"],
        source_category_raw="생활 > 지역화폐",
    )),

    # ── 필수 필드 누락 (격리 동작 확인용) ───────────────────
    ("X0001", "지역 맞춤형 생활 지원 사업", dict(
        org="어느 지방자치단체",
        target_raw="",          # 지원 대상 누락 → _data/incomplete.json 으로 격리되어야 함
        benefit_raw="지자체 예산 범위에서 지원합니다.",
        how_to_raw="담당 부서에 문의합니다.",
        always=True,
        region_scope="sido", sido="chungnam",
        category="living",
        source_category_raw="생활 > 기타",
    )),

    # ── 유사 제도 (다른 source_id, 사실상 같은 제도) ────────
    #    → 유사도 검토 대기열(_data/review_needed.json)에 잡혀야 함
    ("H0009", "청년월세 한시 특별지원", dict(
        org="국토교통부 주거복지정책과",
        target_raw="만 19~34세 무주택 청년으로 보증금 5천만 원 이하 주택에 거주하는 사람",
        benefit_raw="월 최대 20만 원을 12개월 동안 지원합니다.",
        criteria_raw="청년 가구 기준 중위소득 60% 이하여야 합니다.",
        how_to_raw="복지로에서 온라인으로 신청합니다.",
        documents_raw=["임대차계약서 사본", "월세 이체 증빙 서류"],
        apply_start="2026-03-02", apply_end="2027-02-26",
        category="housing", audiences=["youth"],
        source_category_raw="주거 > 청년",
    )),
]


class Adapter(BaseAdapter):
    source = "mock"

    def fetch(self, limit: int | None = None) -> list:
        rows = _ROWS if limit is None else _ROWS[:limit]
        return [self.build(source_id, name, is_mock=True, **kwargs)
                for source_id, name, kwargs in rows]
