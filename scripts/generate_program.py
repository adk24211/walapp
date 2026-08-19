"""③ 해설 생성 — LLM은 '문장'만 만든다.

구 generate_post.py 와의 결정적 차이:

    구:  기사 본문을 던지고 title·summary·stats·compare·steps 를 전부 자유 생성
         → 금액·연령·기간까지 LLM이 지어낼 수 있었다
    현재: 금액·대상·기간·기관·URL 은 프롬프트에 '고정 사실'로 주고,
         LLM에게는 그것을 쉬운 말로 풀어 쓰는 일만 맡긴다

출력 계약(prose):
    {
      "summary":     "한두 문장 요약",
      "eligibility": ["자격 확인 항목", ...],
      "steps":       [{"title": ..., "body": ...}, ...],
      "faq":         [{"q": ..., "a": ...}, ...],
      "note":        "주의 안내"
    }
제목·금액·URL 은 이 계약에 아예 없다. 만들 수 없으면 틀릴 수도 없다.
"""
from __future__ import annotations

import json
import logging
import os
import re
import textwrap
import time

import schema
import taxonomy
from schema import ProgramRecord

log = logging.getLogger(__name__)

# 상위 모델 고정. 하루 발행량이 4~5건이라 무료 한도 안에서 충분히 돌아간다.
# 작은 모델로 자동 강등하면 같은 사이트 안에서 글마다 품질이 들쭉날쭉해진다.
#
# ⚠️ 값을 코드에 박아 두지 말 것. 2026-08-19 에 llama-3.3-70b-versatile 이
#    제공처에서 사라져 404 가 났는데, 하드코딩이라 코드를 고쳐 배포할 때까지
#    발행이 멈췄다. 모델 이름은 우리가 통제하지 못하는 값이다.
#    WALAPP_LLM_MODEL 로 덮어쓸 수 있게 두면 시크릿·환경변수만 바꿔 복구된다.
PRIMARY_MODEL = os.environ.get("WALAPP_LLM_MODEL", "").strip() or "llama-3.3-70b-versatile"


class ModelUnavailable(RuntimeError):
    """설정한 모델을 부를 수 없다.

    제도 하나가 실패한 것과는 성격이 다르다. 이건 설정이 깨진 것이고, 그대로
    두면 **모든** 제도가 조용히 반려된다. 실제로 그렇게 하루를 날렸다 —
    로그에는 '반려 4건' 만 남아서 나쁜 데이터 몇 건처럼 보였다.

    그래서 이 예외는 제도별 반려로 삼키지 않고 위로 올려 실행을 세운다.
    """

# 429 재시도 간격(초). 한도는 분 단위로 회복되므로 두 번째는 넉넉히 기다린다.
RETRY_DELAYS = (25, 65)

SYSTEM_PROMPT = (
    "당신은 정부 지원 제도를 일반 국민이 이해할 수 있게 풀어 쓰는 한국어 편집자입니다. "
    "맞춤법과 문법이 정확하고, 주어진 사실 밖으로 절대 나가지 않으며, "
    "정중한 존댓말('~합니다', '~입니다')로 일관되게 씁니다. "
    # 실제로 새어 나온 적이 있다. '방문申请', '最近 5년 이내' 처럼 중국어가 섞여
    # 그대로 발행됐다(6건). 모델이 한국어와 중국어를 함께 배운 탓이라 한 줄로
    # 못을 박아 둔다. 사후 검증도 verify.py 가 따로 한다.
    "한글과 숫자, 그리고 원문에 있는 한자 표기만 씁니다. "
    "중국어 간체나 일본어 문자는 한 글자도 쓰지 않습니다."
)


def build_prompt(record: ProgramRecord) -> str:
    cat_label = taxonomy.CATEGORIES.get(record.category, {}).get("label", "지원 제도")
    audience_labels = [taxonomy.AUDIENCES[a]["label"]
                       for a in record.audiences if a in taxonomy.AUDIENCES]

    period = record.apply_period
    if period.always:
        period_text = "상시 접수"
    elif period.start and period.end:
        period_text = f"{period.start} ~ {period.end}"
    elif period.end:
        period_text = f"{period.end}까지"
    else:
        period_text = "명시되지 않음"

    # 실제 원문은 선정기준만 2천 자가 넘는 경우가 있다. 프롬프트에는 앞부분만 넣는다.
    # 사후 검증(verify.py)은 **잘리지 않은 전체 원문**을 기준으로 하므로,
    # 여기서 잘라도 검증이 느슨해지지 않는다(허용 숫자 집합은 그대로다).
    def cap(text: str, limit: int = 1200) -> str:
        text = str(text or "").strip()
        return text if len(text) <= limit else text[:limit].rstrip() + " …(이하 생략)"

    facts = textwrap.dedent(f"""
        === 고정 사실 (원문 그대로. 이 밖의 수치·조건은 존재하지 않습니다) ===
        제도명: {record.name}
        분야: {cat_label}
        소관 기관: {record.org or "명시되지 않음"}
        지원 지역: {record.region.label}
        주요 대상: {", ".join(audience_labels) or "명시되지 않음"}

        [지원 대상]
        {cap(record.target_raw) or "(내용 없음)"}

        [지원 내용]
        {cap(record.benefit_raw) or "(내용 없음)"}

        [선정 기준]
        {cap(record.criteria_raw) or "(내용 없음)"}

        [신청 방법]
        {" · ".join(schema.apply_methods(record.how_to_raw)) or "(내용 없음)"}

        [구비 서류]
        {chr(10).join(f"- {d}" for d in record.documents_raw) or "(내용 없음)"}

        [신청 기간]
        {period_text}
    """).strip()

    rules = textwrap.dedent(r"""
        === 당신이 할 일 ===
        위 '고정 사실'을 처음 보는 사람도 이해할 수 있게 풀어 씁니다.
        사실을 새로 만들지 말고, 이미 있는 사실을 쉽게 설명하는 것이 전부입니다.

        ★ 수치 규칙 (가장 중요)
        - 금액·연령·기간·비율·횟수는 '고정 사실'에 적힌 값만 씁니다.
        - 고정 사실에 없는 숫자는 어떤 이유로도 쓰지 않습니다. 추정·반올림·예시 계산 모두 금지입니다.
        - 확실하지 않으면 숫자를 아예 빼고 서술합니다. ("소득 기준을 충족해야 합니다" 처럼)
        - 이 규칙 위반은 자동 검사로 걸러져 해당 문장이 통째로 삭제됩니다. 문장을 잃지 않으려면 지키세요.

        ★ 금지 사항
        - URL, 링크, 전화번호를 쓰지 않습니다. 공식 창구 링크는 시스템이 따로 붙입니다.
        - 제도명을 바꾸거나 새 제도명을 만들지 않습니다.
        - '고정 사실'에 없는 기관명·법령명·사업명을 쓰지 않습니다.
        - 한자와 일본어 가나를 쓰지 않습니다. 한글과 영문·숫자만 씁니다.

        ★ 문체
        - 모든 문장을 '~합니다 / ~입니다' 로 끝맺습니다.
        - 기사체('~한다')와 구어체('~해요')를 쓰지 않습니다.
        - **지시하는 어미('~하세요', '~하십시오', '~해 주세요')를 쓰지 않습니다.**
          신청 여부는 읽는 사람이 정합니다. 안내가 필요하면 '~하시기 바랍니다',
          '~하시면 됩니다', '~해야 합니다' 로 씁니다.
        - 같은 뜻의 문장을 반복하지 않습니다. 내용이 적으면 짧게 끝냅니다.

        === 출력 형식 (JSON만, 다른 텍스트 금지) ===
        {
          "summary": "이 제도가 무엇인지 한두 문장으로. 80~140자.",
          "eligibility": [
            "신청 자격을 스스로 확인할 수 있는 항목을 한 줄씩. 3~6개.",
            "'고정 사실'의 지원 대상·선정 기준을 항목으로 나눠 쓰세요."
          ],
          "steps": [
            {"title": "단계 제목", "body": "신청 절차를 2~4문장으로 설명. 존댓말. 날짜는 적지 않습니다."}
          ],
          "faq": [
            {"q": "페이지 어디에도 답이 없는 질문", "a": "고정 사실로 답할 수 있는 내용만 2~3문장."}
          ],
          "note": "이 제도에만 해당하는 주의사항 1문장. 없으면 빈 문자열."
        }

        === 필드 가이드 ===
        - summary: 필수.
        - steps: 신청 기간(날짜)은 적지 마세요. 오른쪽 신청 레일에 이미 있습니다.
          "신청 기간은 ○○ ~ ○○입니다" 같은 문장은 자리만 먹습니다.
          다만 지급·선정 시점처럼 신청 기간과 뜻이 다른 날짜는 적어도 됩니다.
        - eligibility: 3~6개. 고정 사실로 판단할 수 없는 조건은 넣지 않습니다.
        - steps: 2~4개. '신청 방법'에 근거가 있는 만큼만 만듭니다. 근거가 한 줄뿐이면 1개만 만드세요.
        - faq: 0~3개. 고정 사실로 답할 수 없는 질문은 만들지 않습니다. 없으면 빈 배열.

          ★ 되묻기 금지 — faq 에서 가장 중요한 규칙입니다.
          페이지에는 이미 다음 항목이 따로 실립니다. 그 항목이 답하는 질문은
          만들지 마세요. 같은 답을 두 번 읽게 됩니다.

            지원 내용(원문)        → "지원 금액은 얼마인가요?" "지원 내용은 무엇인가요?" 금지
            나도 받을 수 있나요?   → "지원 대상은 누구인가요?" "자격 요건은?" 금지
            어떻게 신청하나요?     → "어떻게 신청하나요?" "어디에 신청하나요?" 금지
            준비 서류·서식        → "어떤 서류가 필요한가요?" 금지
            신청 기간(화면 상단)   → "언제까지 신청할 수 있나요?" 금지
            문의처               → "어디에 문의하나요?" 금지

          남길 만한 것은 원문 안에 묻혀 있어 위 항목만 봐서는 놓치는 세부입니다.
          예: "금리 우대는 어떻게 적용되나요?" "인정소득은 어떻게 계산합니까?"
              "이용권은 어디서 쓸 수 있나요?" "내구연한은 어떻게 되나요?"

          그런 질문이 하나도 없으면 **빈 배열로 두세요.** 억지로 채우지 마세요.
          빈 배열이면 이 항목은 화면에 아예 나오지 않습니다.
        - note: 선택. **이 제도에만 해당하는** 주의사항이 있을 때만 씁니다.

          쓸 것: 예산 소진 시 조기 마감, 지자체 조례에 따라 대상 연령이 다름,
                 매년 대상이 바뀜, 다른 지원과 중복 수급 불가 같은 개별 조건.

          쓰지 말 것:
            · "자세한 사항은 ○○에 확인/문의하세요"
              → 문의처는 이 페이지의 '신청 창구' 표에 이미 있습니다.
            · "변경될 수 있습니다", "정책에 따라 달라질 수 있습니다"
              → 모든 제도가 그렇습니다. 푸터가 이미 말하고 있습니다.
            · "상시 접수입니다", "신청 기간은 ○○입니다"
              → 신청 기간은 오른쪽 신청 레일에 이미 있습니다. 날짜를 여기 적으면
                원천이 바뀔 때 레일만 갱신되고 이 문장은 낡은 채로 남습니다.

          해당하는 것이 없으면 **빈 문자열로 두세요.** 이 안내는 경고 아이콘이
          붙은 상자로 나갑니다. 모든 페이지에 뜨면 아무도 경고로 읽지 않습니다.
    """).strip()

    return f"{facts}\n\n{rules}"


# ─────────────────────────────────────────────────────────────
#  LLM 호출
# ─────────────────────────────────────────────────────────────
def generate(record: ProgramRecord, client) -> dict:
    """Groq 호출 → prose dict. client 가 None 이면 오프라인 폴백을 쓴다."""
    if client is None:
        return generate_offline(record)

    prompt = build_prompt(record)
    log.info("해설 생성: %s", record.name)

    def _call(model: str, max_tokens: int = 2400):
        return client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.35,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )

    response = _call_with_retry(_call, record)

    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return _coerce(json.loads(raw))


def _call_with_retry(call, record: ProgramRecord):
    """한도(429)에 걸리면 기다렸다 같은 모델로 다시 부른다.

    작은 모델로 내려가는 폴백은 두지 않는다 (사용자 확정 사항).
    하루 발행량이 4~5건이라 무료 한도에 여유가 있고, 같은 사이트 안에서 글마다
    문장 품질이 눈에 띄게 달라지는 것이 한 건 밀리는 것보다 나쁘다.
    끝까지 실패하면 예외를 올려 그 제도만 반려한다 — 다음 실행에서 다시 잡힌다.
    """
    delays = RETRY_DELAYS
    for attempt in range(len(delays) + 1):
        try:
            return call(PRIMARY_MODEL)
        except Exception as e:
            text = str(e).lower()
            # 모델이 없어졌거나 권한이 없다 — 재시도해도 같고, 다음 제도도 같다.
            if ("does not exist" in text or "do not have access" in text
                    or "model_not_found" in text):
                raise ModelUnavailable(
                    f"모델 '{PRIMARY_MODEL}' 을 부를 수 없습니다: {e}\n"
                    f"    제공처에서 모델이 내려갔거나 키에 권한이 없습니다.\n"
                    f"    WALAPP_LLM_MODEL 환경변수에 현재 쓸 수 있는 모델 이름을 넣으세요."
                ) from e
            if "413" in text or "too large" in text:
                # 프롬프트가 너무 길다 — 재시도해도 같으므로 출력만 줄여 한 번 더.
                log.warning("프롬프트 초과 [%s] → 출력 길이를 줄여 재시도", record.id)
                return call(PRIMARY_MODEL, 1600)
            rate_limited = "429" in text or "rate_limit" in text
            if not rate_limited or attempt >= len(delays):
                raise
            wait = delays[attempt]
            log.warning("%s 한도(429) → %d초 대기 후 재시도 (%d/%d)",
                        PRIMARY_MODEL, wait, attempt + 1, len(delays))
            time.sleep(wait)


def _coerce(data: dict) -> dict:
    """LLM 출력에서 계약에 있는 키만 남기고 타입을 맞춘다."""
    out: dict = {
        "summary": str(data.get("summary") or "").strip(),
        "note": str(data.get("note") or "").strip(),
        "eligibility": [],
        "steps": [],
        "faq": [],
    }
    for item in data.get("eligibility") or []:
        text = str(item).strip()
        if text:
            out["eligibility"].append(text)
    for item in data.get("steps") or []:
        if isinstance(item, dict) and str(item.get("body") or "").strip():
            out["steps"].append({
                "title": str(item.get("title") or "").strip(),
                "body": str(item["body"]).strip(),
            })
    for item in data.get("faq") or []:
        if isinstance(item, dict) and item.get("q") and item.get("a"):
            out["faq"].append({"q": str(item["q"]).strip(), "a": str(item["a"]).strip()})
    return out


# ─────────────────────────────────────────────────────────────
#  오프라인 폴백 — API 키 없이 파이프라인을 끝까지 돌리기 위한 것
# ─────────────────────────────────────────────────────────────
# '·' 로는 자르지 않는다. 한국어에서 가운뎃점은 문장 구분자가 아니라 낱말 이음표라
# ('소득·재산 조사') 여기서 자르면 '신청 후 소득' 같은 토막 문장이 나온다.
_SENT_SPLIT_RE = re.compile(r"(?<=다\.)\s*|(?<=니다\.)\s*|\n")


def generate_offline(record: ProgramRecord) -> dict:
    """LLM 없이 원본 필드를 재배치해 해설 형태를 만든다.

    문장을 '지어내지' 않고 원본을 항목으로 쪼개기만 하므로 검증에 걸릴 수치가
    구조적으로 생기지 않는다. 레이아웃·렌더러·검증기를 API 키 없이 확인하는 용도다.
    실제 발행 품질은 아니며, GROQ_API_KEY 가 있으면 이 함수는 호출되지 않는다.
    """
    region = record.region.label
    summary = record.benefit_raw or record.target_raw
    if record.org:
        # 조사 '이(가)' 를 쓰지 않는다. 기관명 받침에 따라 달라지는데 병기하면
        # '성남시이(가)' 처럼 읽힌다. 받침과 무관한 '에서' 로 우회한다.
        # 지자체 제도는 소관 기관과 지원 지역이 같은 말이라('경기도 성남시' × 2) 지역을 뺀다.
        if region in record.org or record.org in region:
            summary = f"{record.org}에서 운영하는 제도입니다. {summary}"
        else:
            summary = f"{record.org}에서 {region} 대상으로 운영하는 제도입니다. {summary}"

    eligibility: list[str] = []
    for chunk in _split_items(record.target_raw):
        eligibility.append(chunk if chunk.endswith(("다", "요", ".")) else f"{chunk}에 해당하는지 확인이 필요합니다")
    for chunk in _split_items(record.criteria_raw):
        eligibility.append(chunk)
    eligibility = [e for e in dict.fromkeys(eligibility) if e][:6]

    steps: list[dict] = []
    how_to_items = _split_items("\n".join(schema.apply_methods(record.how_to_raw)))
    for index, chunk in enumerate(how_to_items[:4], 1):
        steps.append({"title": f"{index}단계", "body": chunk})
    if not steps:
        methods = schema.apply_methods(record.how_to_raw)
        if methods:
            steps = [{"title": "신청 방법", "body": " · ".join(methods) + "으로 신청합니다."}]

    faq: list[dict] = []
    if record.documents_raw:
        faq.append({
            "q": "어떤 서류를 준비해야 하나요?",
            "a": "필요한 서류는 " + ", ".join(record.documents_raw) + "입니다. 기관에 따라 추가 서류를 요청할 수 있습니다.",
        })
    if record.apply_period.always:
        faq.append({"q": "언제까지 신청할 수 있나요?", "a": "상시 접수하는 제도입니다. 예산 사정에 따라 조기 마감될 수 있습니다."})

    return {
        "summary": summary,
        "eligibility": eligibility,
        "steps": steps,
        "faq": faq,
        # 주의 안내는 비운다. 원문만 보고는 이 제도에만 해당하는 조건을 가려낼
        # 수 없고, 아무 제도에나 맞는 말은 푸터가 이미 하고 있다.
        "note": "",
    }


def _split_items(text: str) -> list[str]:
    if not text:
        return []
    parts = [p.strip(" -–—") for p in _SENT_SPLIT_RE.split(text)]
    return [p for p in parts if len(p) > 4]
