"""키워드로는 못 읽는 대상을 사람이 직접 지정한다. `_data/audience_overrides.json`.

왜 필요했나
───────────
청년내일채움공제(조회 551,148)의 원문은 스스로 대상이 둘이라고 적는다.

    ㅇ 지원대상별(**청년, 기업**) 가입자격을 갖춘경우 …
    ㅇ (기업) 고용보험 피보험자수 5인 이상~50인 미만 제조, 건설업종 중소기업

그런데 사업주 축의 키워드는 '사업주'·'고용주' 뿐이라 '기업' 을 못 읽는다.
'중소기업' 을 키워드로 넣으면 **근로자가 다니는 회사**까지 전부 걸려서 못 쓴다
(청년내일채움공제·실업크레딧·구직자 취업지원 … 죄다 중소기업을 언급한다).

키워드 규칙 하나로는 못 가르는 자리가 있다. 그럴 때 규칙을 억지로 넓히면
수십 건이 잘못 붙는다 — 이 저장소가 반복해서 겪은 실패다. 그래서 규칙은
그대로 두고, 그 한 건만 손으로 적는다.

⚠️ 이건 마지막 수단이다
───────────────────────
덮어쓰기가 늘어나면 규칙의 결함이 그 뒤에 숨는다. 그래서 두 가지를 강제한다.

  ① **근거를 원문에서 그대로 인용**해야 한다(`quote`). 그 문장이 레코드에서
     사라지면 검사가 실패한다 — 원문이 바뀌었는데 덮어쓰기만 남는 상태를
     막는다. 덮어쓰기가 스스로 만료되는 셈이다.

  ② 규칙이 이미 같은 답을 내면 검사가 실패한다. 규칙을 고쳐서 해결된 뒤에도
     덮어쓰기가 남아 있으면, 다음 사람은 그 태그가 규칙에서 온 것인지
     손에서 온 것인지 알 수 없다.

    python3 scripts/check_overrides.py     # 위 두 가지를 본다 (CI 에서 돈다)
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
OVERRIDES_FILE = ROOT / "_data" / "audience_overrides.json"


def load() -> dict:
    """{program_id: {add, remove, reason, quote, name}}. 파일이 없으면 빈 dict.

    ⚠️ 읽기에 실패해도 예외를 올리지 않는다. 이 파일이 깨졌다고 매일 도는
       동기화가 통째로 멈추면, 얻는 것보다 잃는 것이 크다. 대신
       check_overrides.py 가 CI 에서 잡는다.
    """
    if not OVERRIDES_FILE.exists():
        return {}
    try:
        data = json.loads(OVERRIDES_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def apply(program_id: str, audiences, table: dict | None = None) -> list[str]:
    """규칙이 낸 대상에 손으로 적은 것을 더하고 뺀다.

    ⚠️ 분류하는 **모든 자리**에서 불러야 한다. 지금은 두 곳이다 —
       수집(collect/adapters/base.py)과 재분류(reclassify_audiences.py).
       한 곳만 부르면 둘이 다른 답을 내고, 다음 동기화가 그 차이를 '변경' 으로
       잡아 재생성이 한 번 더 든다.
    """
    base = list(audiences or [])
    rule = (table if table is not None else load()).get(program_id)
    if not rule:
        # ⚠️ 정렬하지 말 것. 덮어쓰기가 없으면 **받은 그대로** 돌려줘야 한다.
        #    한 번 sorted() 로 돌려줬다가, 순서만 달라진 198건이 전부 '변경' 으로
        #    잡혔다. audiences 는 해시 대상이라(schema._HASHED_FIELDS) 순서가
        #    바뀌면 해시가 바뀌고, 그 198건이 다음 동기화에서 재생성된다 —
        #    하루 한도가 20건 남짓이니 열흘치다.
        return base

    drop = set(rule.get("remove") or [])
    out = [a for a in base if a not in drop]
    # 더하는 것은 적어 둔 순서대로 뒤에 붙인다. 규칙이 낸 것의 순서는 건드리지
    # 않는다 — 같은 이유다.
    for a in rule.get("add") or []:
        if a not in out and a not in drop:
            out.append(a)
    return out
