"""429 를 어떻게 나눠 다루는지 고정한다.

한도에는 두 종류가 있고, 대응이 정반대다.

  · 분당(TPM/RPM) — 몇십 초면 회복된다. 기다렸다 다시 부르는 게 맞다.
  · 하루(TPD/RPD) — 복구까지 수십 분이다. 기다려도 소용없고, 남은 제도도
    전부 같은 이유로 실패한다. 즉시 포기하고 루프를 끊는 게 맞다.

둘을 섞으면 조용히 비싸진다. 2026-08-20 실행이 그랬다 — 하루 한도가 소진된
뒤에도 남은 11건을 계속 시도해, 건당 90초씩 합쳐 16분 30초를 버리고 전부
반려됐다(파이프라인 30분 중). 로그에는 '반려 11건' 으로만 보였다.

반대 방향의 실수는 더 나쁘다: 하루 한도라고 잘못 판정해 루프를 끊으면,
분당 한도에 한 번 걸린 날 그날 발행이 통째로 멈춘다. 그래서 '모르는 문구는
분당으로 본다'(재시도) 를 기본값으로 두고, 그것도 여기서 고정한다.

파이프라인 재시도·반려 로직을 건드리면 이걸 먼저 돌린다.

    python3 scripts/check_quota.py
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import generate_program  # noqa: E402
import publish           # noqa: E402
import registry          # noqa: E402

# run 46 로그에서 그대로 가져온 문구. 제공처가 형식을 바꾸면 여기가 먼저 깨진다.
TPD = ("Error code: 429 - {'error': {'message': 'Rate limit reached for model "
       "`openai/gpt-oss-120b` in organization `org_01k` service tier `on_demand` "
       "on tokens per day (TPD): Limit 200000, Used 199790, Requested 7873. "
       "Please try again in 55m10.416s.', 'code': 'rate_limit_exceeded'}}")
TPM = ("Error code: 429 - {'error': {'message': 'Rate limit reached for model "
       "`openai/gpt-oss-120b` on tokens per minute (TPM): Limit 30000, Used 29000, "
       "Requested 7873. Please try again in 12.3s.', 'code': 'rate_limit_exceeded'}}")

CASES = [
    ("하루 한도 (TPD)",   TPD,                              True),
    ("분당 한도 (TPM)",   TPM,                              False),
    ("요청수/일 (RPD)",   "429 ... on requests per day (RPD): Limit 1000", True),
    ("문구 없는 429",     "Error code: 429 - server busy",  False),
    # 날짜가 섞인 메시지를 하루 한도로 오인하면 안 된다.
    ("날짜만 든 429",     "429 error at 2026-08-20, retry later", False),
]

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'}  {label}{'  — ' + detail if detail else ''}")
    if not ok:
        failures.append(label)


def main() -> int:
    print("── ① 문구 판정 ──")
    for name, msg, want in CASES:
        got = generate_program._is_daily_quota(msg.lower())
        check(f"{name:16} → 하루한도={got}", got == want, "" if got == want else f"기대 {want}")

    print("\n── ② 재시도 동작 ──")
    slept: list[float] = []
    real_sleep = generate_program.time.sleep
    generate_program.time.sleep = slept.append          # 실제로 기다리지 않는다

    class Rec:
        id, name = "x", "테스트 제도"

    try:
        for name, msg, expect_calls, expect_exc in [
            ("하루 한도", TPD, 1, generate_program.DailyQuotaExhausted),
            ("분당 한도", TPM, 1 + len(generate_program.RETRY_DELAYS), RuntimeError),
        ]:
            slept.clear()
            calls: list[int] = []

            def call(model, max_tokens=None):
                calls.append(1)
                raise RuntimeError(msg)

            try:
                generate_program._call_with_retry(call, Rec())
                raised: type = type(None)
            except Exception as e:                       # noqa: BLE001
                raised = type(e)

            check(f"{name}: 호출 {len(calls)}회 · 대기 {sum(slept):.0f}초 · {raised.__name__}",
                  len(calls) == expect_calls and issubclass(raised, expect_exc),
                  "" if len(calls) == expect_calls else f"호출 {expect_calls}회 기대")
    finally:
        generate_program.time.sleep = real_sleep

    print("\n── ③ 소진 시점의 루프 ──")
    records = list(registry.load_all_records().values())[:5]
    if len(records) < 5:
        check("레코드 5건 필요", False, f"_records/ 에 {len(records)}건뿐")
        return 1

    publish.adapters = type("A", (), {"get": staticmethod(lambda s: None)})()  # 네트워크 차단
    attempted: list[str] = []
    real_generate = generate_program.generate

    def fake_generate(record, client=None):
        attempted.append(record.name)
        if len(attempted) >= 3:                          # 3번째에 소진
            raise generate_program.DailyQuotaExhausted(TPD)
        saved = registry.load_prose(record.id)
        if saved is None:
            raise RuntimeError("저장된 해설 없음")
        return saved

    generate_program.generate = fake_generate
    try:
        res = publish.run(records, [], registry.Registry(), datetime.date.today(),
                          client=object(), dry_run=True)
        escaped = None
    except generate_program.DailyQuotaExhausted as e:
        res, escaped = None, e
    finally:
        generate_program.generate = real_generate

    check("예외가 run() 밖으로 새지 않는다", escaped is None,
          "" if escaped is None else "run_all 이 실행을 세워 그날 발행분까지 잃는다")
    if res is not None:
        check(f"소진 뒤 남은 2건을 시도하지 않는다 (시도 {len(attempted)}/5회)",
              len(attempted) == 3)
        check(f"소진 전에 끝난 2건이 보존된다 (published {len(res.published)}건)",
              len(res.published) == 2)
        check(f"소진된 건은 사유와 함께 반려된다 (반려 {len(res.rejected)}건)",
              len(res.rejected) == 1
              and "일일 한도 소진" in res.rejected[0].get("reason", ""))

    print()
    if failures:
        print(f"✗ {len(failures)}건 실패: " + " · ".join(failures))
        return 1
    print("✅ 전부 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
