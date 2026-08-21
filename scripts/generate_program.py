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
#
# 2026-08-16 llama-3.3-70b-versatile 종료. 제공처가 권한 대체는 둘이었다:
#   openai/gpt-oss-120b   또는   qwen/qwen3.6-27b
#
# gpt-oss-120b 를 고른 이유는 이 사이트가 겪은 일 때문이다. Llama 로 생성한
# 해설에 중국어가 6건 섞여 나갔다("방문申请", "最近 5년 이내", "海外" 가
# "外海" 로 뒤집힌 것까지 — verify.py 주석 참고). Qwen 은 중국어 비중이 큰
# 모델군이라 같은 사고를 더 겪을 이유가 없다. 크기도 이쪽이 커서 '상위 모델
# 고정' 이라는 원래 방침에 맞는다.
PRIMARY_MODEL = os.environ.get("WALAPP_LLM_MODEL", "").strip() or "openai/gpt-oss-120b"


class ModelUnavailable(RuntimeError):
    """설정한 모델을 부를 수 없다.

    제도 하나가 실패한 것과는 성격이 다르다. 이건 설정이 깨진 것이고, 그대로
    두면 **모든** 제도가 조용히 반려된다. 실제로 그렇게 하루를 날렸다 —
    로그에는 '반려 4건' 만 남아서 나쁜 데이터 몇 건처럼 보였다.

    그래서 이 예외는 제도별 반려로 삼키지 않고 위로 올려 실행을 세운다.
    """


class DailyQuotaExhausted(RuntimeError):
    """오늘 쓸 수 있는 토큰을 다 썼다(TPD/RPD).

    같은 429 라도 분당 한도와는 성격이 완전히 다르다.

      · 분당 한도(TPM/RPM) — 몇십 초 기다리면 회복된다. 재시도가 듣는다.
      · 하루 한도(TPD/RPD) — 제공처가 알려 주는 복구 시각이 '46분 뒤' 다.
        25초·65초를 기다려 봐야 같은 429 를 두 번 더 맞고 반려된다.
        게다가 **남은 제도 전부가 같은 이유로 실패한다.**

    2026-08-20 실행이 그랬다. 13건을 낸 뒤 한도가 소진됐는데, 남은 11건이
    각각 재시도 90초씩 합쳐 16분 30초를 버리고 전부 반려됐다(파이프라인 30분).
    한 건도 더 나갈 수 없는 상태에서 16분을 기다린 것이다.

    그래서 재시도하지 않고 즉시 올린다. 받는 쪽(publish.run)은 남은 제도를
    포기하되 **이미 발행한 것은 그대로 지킨다** — 그날 나간 13건은 정상이었고,
    실행을 실패로 만들면 그것까지 배포되지 않는다.
    """

# 429 재시도 간격(초).
#
# ⚠️ 분당 한도(RPM/TPM)에만 듣는 값이다. 하루 총량(TPD)이 소진된 429 에는
#    듣지 않는다 — 그때 제공처가 알려 주는 복구 시각은 '46분 뒤' 같은 값이라
#    25초·65초를 기다려 봐야 같은 429 를 두 번 더 맞고 반려된다.
#    2026-08-20 실행에서 반려 11건이 각각 90초씩, 합쳐 16분 30초를 그렇게
#    버렸다(파이프라인 30분 중). 고칠 여지가 있는 자리다.
RETRY_DELAYS = (25, 65)

# 출력 토큰 상한.
#
# 2400 으로 오래 잘 돌았는데, gpt-oss-120b 로 바꾼 첫 실행에서 4건 중 3건이
# 400 "Failed to validate JSON" 으로 떨어졌다. gpt-oss 는 추론형이라 답을
# 내기 전에 추론 토큰을 먼저 쓰고, 그게 이 상한을 함께 먹는다. 한도에 걸려
# JSON 이 중간에 잘리면 그대로 검증 실패다. 그래서 8000 으로 올려 잡았다.
#
# ⚠️ **이 값은 넉넉할수록 좋은 값이 아니다.** 그렇게 알고 8000 을 줬는데,
#    2026-08-20 실행에서 반대라는 것이 드러났다.
#
#    Groq 는 하루 토큰 총량(TPD)으로 끊고, 그 한도에서 깎는 값이 실사용이
#    아니라 **입력 + max_tokens 예약분**이다. 그날 로그가 그대로 보여 준다:
#
#      실사용 평균  입력 2167 + 출력 1617 = 3784
#      한도 차감    평균 7556            ← 절반이 예약만 하고 버려졌다
#      → Limit 200000, Used 199790 로 소진. 25건 중 13건만 나가고 11건 반려.
#
#    상한을 높이 잡는 것은 공짜가 아니라 **하루 발행량을 직접 깎는다.**
#
# 그래서 실제 출력 관측치에 맞춰 내린다.
#   출력 최대  3119 (2026-08-19 4건) · 2506 (2026-08-20 13건)
#   4000 은 그 위로 28% 여유다. JSON 잘림을 막기에 충분하고,
#   차감이 7556 → 약 6100 으로 줄어 하루 26건 → 32건이 된다.
#
# 모델을 바꿔 출력이 길어지면 WALAPP_LLM_MAX_TOKENS 로 올릴 수 있다.
# 올릴 때는 위의 대가(하루 발행량 감소)를 함께 계산할 것.
MAX_TOKENS = int(os.environ.get("WALAPP_LLM_MAX_TOKENS", "4000"))

# ── 호출 간격 ──
# 분당 한도에 반응이 아니라 선제로 맞춘다.
#
# 예전에는 4건을 몰아 던져 429 를 14번 맞고, 재시도가 25초·65초씩 기다려
# 넘겼다. 튕긴 요청도 왕복 비용이고 대기도 그대로 시간이라, 같은 처리량을
# 훨씬 비싸게 산 셈이다. 처음부터 간격을 두면 튕길 일이 줄어든다.
#
# 0 을 주면 간격 없이 던진다(목 모드·오프라인에는 애초에 호출이 없다).
MIN_CALL_INTERVAL = float(os.environ.get("WALAPP_LLM_MIN_INTERVAL", "22"))
_last_call_at = 0.0


def _pace() -> None:
    """직전 호출로부터 MIN_CALL_INTERVAL 초가 지나도록 기다린다."""
    global _last_call_at
    if MIN_CALL_INTERVAL <= 0:
        return
    if _last_call_at:
        wait = MIN_CALL_INTERVAL - (time.monotonic() - _last_call_at)
        if wait > 0:
            log.info("  └ 분당 한도 회피: %.0f초 대기", wait)
            time.sleep(wait)
    _last_call_at = time.monotonic()

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

        === 쓰는 법 ===
        위 블록의 이름('고정 사실' 등)을 문장에 옮겨 적지 마세요. 그건 자료를
        건네는 방식이지 읽는 사람이 아는 말이 아닙니다.
          나쁨: "고정 사실에 따르면 대상은 내국인입니다."
          좋음: "대상은 내국인입니다."

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

    def _call(model: str, max_tokens: int = MAX_TOKENS):
        _pace()
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

    # 실제로 몇 토큰을 썼는지 남긴다.
    #
    # 무료 한도가 분 단위로 걸린다. 한 실행에서 4건을 만드는 데 429 가 14번
    # 났다 — 성공 1건당 3~4번 튕긴 셈이고, 재시도가 25초·65초씩 기다려 그
    # 단계만 3분 17초가 걸렸다. 발행량을 올리려면 한 건이 실제로 얼마를
    # 먹는지부터 알아야 하는데, 그 숫자가 어디에도 남지 않고 있었다.
    #
    # max_tokens 는 상한이지 사용량이 아니다. 8000 을 요청해도 실제로 2000 만
    # 쓴다면 상한을 낮춰 분당 처리량을 늘릴 여지가 있다 — 추측하지 말고 재자.
    usage = getattr(response, "usage", None)
    if usage is not None:
        log.info("  └ 토큰: 입력 %s · 출력 %s · 합계 %s (출력 상한 %d)",
                 getattr(usage, "prompt_tokens", "?"),
                 getattr(usage, "completion_tokens", "?"),
                 getattr(usage, "total_tokens", "?"), MAX_TOKENS)

    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return _coerce(json.loads(raw))


def _failed_generation(err: Exception, limit: int = 600) -> str:
    """오류 응답에서 모델이 실제로 뱉은 것을 꺼낸다.

    제공처가 failed_generation 필드에 원문을 넣어 준다. SDK 예외 모양이
    버전마다 달라 여러 자리를 뒤진 뒤, 그래도 없으면 예외 문자열에서 찾는다.
    """
    for attr in ("body", "response"):
        obj = getattr(err, attr, None)
        if isinstance(obj, dict):
            found = obj.get("error", {}).get("failed_generation")
            if found:
                return str(found)[:limit]
    text = str(err)
    m = re.search(r"'failed_generation':\s*(['\"])(.*?)\1", text, re.S)
    if m:
        return m.group(2)[:limit]
    return ""


def _is_daily_quota(text: str) -> bool:
    """이 429 가 하루 한도인가. text 는 소문자로 넘어온다.

    Groq 는 어느 한도인지 문구에 적어 준다:
        "... on tokens per day (TPD): Limit 200000, Used 199790 ..."
        "... on tokens per minute (TPM): ..."
    'day' 만 보면 날짜가 섞인 다른 메시지에 걸릴 수 있어 형태를 좁게 잡는다.
    모르는 문구는 False — 재시도하는 쪽이 안전한 기본값이다(한 건만 늦어진다).
    """
    return any(k in text for k in ("per day", "(tpd)", "(rpd)"))


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
            # JSON 생성·검증 실패는 그 제도만 반려된다. 그런데 로그에는
            # "실패했다" 만 남고 모델이 실제로 뭘 뱉었는지가 없어서, 프롬프트를
            # 고쳐야 할지 모델 문제인지 판단할 수가 없었다(24건 중 3건).
            # 오류 응답에 failed_generation 이 들어 있으니 앞부분을 남긴다.
            if "failed to generate json" in text or "failed to validate json" in text:
                snippet = _failed_generation(e)
                if snippet:
                    log.warning("JSON 실패 [%s] 모델 출력 앞부분: %s", record.id, snippet)
                raise
            if "413" in text or "too large" in text:
                # 프롬프트가 너무 길다 — 재시도해도 같으므로 출력만 줄여 한 번 더.
                log.warning("프롬프트 초과 [%s] → 출력 길이를 줄여 재시도", record.id)
                return call(PRIMARY_MODEL, max(1600, MAX_TOKENS // 2))
            rate_limited = "429" in text or "rate_limit" in text
            # 하루 한도는 기다려서 풀리는 종류가 아니다. 자세한 이유는
            # DailyQuotaExhausted 참고. 분당 한도와 문구로 구분된다 —
            # "on tokens per day (TPD)" vs "on tokens per minute (TPM)".
            if rate_limited and _is_daily_quota(text):
                raise DailyQuotaExhausted(str(e)) from e
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
