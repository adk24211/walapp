"""공개 문서가 코드에 없는 것을 말하고 있지 않은지 본다.

왜 만들었나
───────────
소개·법률 문서의 사실 주장을 코드와 하나씩 대조해 봤더니, 조용히 틀린 것이
둘 있었다. 둘 다 "예전에 맞았고 지금은 아닌" 부류라 눈으로는 안 걸린다.

  ① /about/ 과 /disclaimer/ 가 "공공데이터포털이 개방한 **두 개의** 공식 API
     에서 받아 온다" 고 단정하고 있었다. 두 번째(중앙부처 복지서비스)는
     OPTIONAL_ADAPTERS 라 ENABLE_WELFARE_CENTRAL=1 일 때만 켜지는데, 그 변수를
     1 로 두는 곳이 저장소 어디에도 없다. 발행된 제도 405건이 예외 없이
     source: "bojo24" 였다 — 기여분이 부분이 아니라 정확히 0이었다.

  ② /privacy/ 가 "다음 **두 가지** Google 서비스를 사용한다" 고 적어 두었는데,
     페이지는 글꼴도 바깥에서 받는다(fonts.googleapis.com · cdn.jsdelivr.net).
     글꼴 파일을 받는 것만으로 그쪽에 접속 IP 가 남는다.

  ③ 처음 만들 때 about·disclaimer 만 보게 했더니 /terms/ 제2조가 그대로
     빠져나갔다. 거기엔 갯수가 아니라 이름이 나란히 적혀 있었다 —
     "보조금24·중앙부처 복지서비스 API에서 받은 값입니다". 그래서 문서 목록에
     terms.html 을 넣고, 이름을 대는 문장도 잡도록 넓혔다.

두 경우 모두 문서가 처음 쓰일 때는 맞았거나 맞을 예정이었고, 코드가 나중에
달라졌다. 사람이 다시 읽지 않으면 영영 안 고쳐진다.

무엇을 보나
───────────
  · 원천 — _records/*.json 에 실제로 있는 source 값과, 공개 문서가 "여기서
    받아 온다" 고 단정한 원천이 맞는지.
  · 바깥 주소 — _layouts/default.html 이 실제로 부르는 호스트가 전부
    개인정보 처리방침에 적혀 있는지.

무엇을 보지 않나
────────────────
문장의 뜻을 읽지 않는다. 기계가 셀 수 있는 것만 본다 — 원천 개수와 호스트
목록. 나머지(무엇이 AI 문장인지, 검증이 무엇을 잡는지)는 사람이 봐야 한다.

    python3 scripts/check_claims.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

# Liquid 주석은 화면에 안 나간다. 빼고 봐야 한다 — 안 그러면 "한때 이렇게
# 적혀 있었다" 는 이력 주석이 지금의 주장으로 잡혀 자기 자신에 걸린다.
# (실제로 이 검사를 처음 돌렸을 때 그렇게 걸렸다)
_COMMENT_RE = re.compile(r"\{%-?\s*comment\s*-?%\}.*?\{%-?\s*endcomment\s*-?%\}", re.S)


def visible(path: Path) -> str:
    """화면에 실제로 나가는 부분만."""
    return _COMMENT_RE.sub(" ", path.read_text(encoding="utf-8"))

# 원천 이름 ↔ 공개 문서에 적히는 말. 어댑터가 늘면 여기도 늘린다.
SOURCE_LABELS = {
    "bojo24": "보조금24",
    "welfare-central": "중앙부처 복지서비스",
}

# 처리방침에 적을 필요가 없는 호스트.
# 사이트 자신과, 사용자를 보내기만 하는 바깥 링크(정책 안내 페이지)는 뺀다.
HOST_EXEMPT = {
    "adk24211.github.io",
    "policies.google.com",
    "www.aboutads.info",
    "tools.google.com",
    "github.com",
    "schema.org",
    "www.w3.org",
}

failures: list[str] = []


def check_sources() -> None:
    """공개 문서가 말하는 원천 개수 == 실제로 데이터가 온 원천 개수."""
    records = sorted((ROOT / "_records").glob("*.json"))
    if not records:
        failures.append("_records/ 가 비어 있어 원천을 셀 수 없습니다.")
        return

    live: set[str] = set()
    for path in records:
        try:
            live.add(json.loads(path.read_text(encoding="utf-8")).get("source") or "?")
        except json.JSONDecodeError:
            failures.append(f"{path.name} 을 읽지 못했습니다.")
    live.discard("?")

    print(f"실제 원천 {len(live)}곳: {', '.join(sorted(live))} (레코드 {len(records)}건)")

    # ⚠️ 잡는 것은 '갯수를 단정한 말' 이다. 원천이 하나인데 "두 개의 공식 API"
    #    라고 적혀 있으면 여기서 걸린다. 반대로 원천이 둘로 늘었는데 문서가
    #    "한 개" 라고 적혀 있어도 걸린다 — 어느 방향이든 어긋나면 알려야 한다.
    counts = {1: ("한 개", "하나"), 2: ("두 개", "둘"), 3: ("세 개", "셋")}
    # ⚠️ 세 문서를 다 본다. 이용약관을 빼 두었다가 제2조가 그대로 빠져나갔다.
    for doc in ("about.html", "disclaimer.html", "terms.html"):
        text = visible(ROOT / doc)
        for n, words in counts.items():
            for word in words:
                if re.search(rf"{word}의?\s*(공식\s*)?API", text) and n != len(live):
                    failures.append(
                        f"{doc}: '{word}… API' 라고 적혀 있는데 실제 원천은 {len(live)}곳입니다."
                    )

        # 문서가 이름을 대며 "여기서 받아 온다" 고 단정하는데 그 원천에서 온
        # 레코드가 하나도 없는 경우. ①이 정확히 이 모양이었다.
        for key, label in SOURCE_LABELS.items():
            if key in live:
                continue
            # '아직 켜지 않았습니다' 처럼 예정임을 밝힌 문장은 통과시킨다.
            for line in text.split("\n"):
                if label not in line:
                    continue
                if re.search(r"아직|않았|예정|계획|꺼(져|둔)|만들어 두", line):
                    continue
                # 이름을 대며 그 원천에서 왔다고 말하는 여러 어투를 잡는다.
                # "…에서 받아 옵니다" · "…에서 데이터를 받아" · "…API에서 받은 값"
                if re.search(r"받아\s*(옵니다|온다)|에서\s*데이터를\s*받아"
                             r"|에서\s*받은\s*값|에서\s*받아\s*", line):
                    failures.append(
                        f"{doc}: '{label}' 에서 받아 온다고 적혀 있는데 그 원천의 레코드가 0건입니다."
                    )


def check_external_hosts() -> None:
    """레이아웃이 부르는 바깥 호스트가 전부 처리방침에 적혀 있는가."""
    layout = visible(ROOT / "_layouts" / "default.html")
    hosts = {
        h for h in re.findall(r"https://([a-z0-9.-]+)", layout)
        if h not in HOST_EXEMPT
    }
    privacy = visible(ROOT / "privacy.html")

    print(f"레이아웃이 부르는 바깥 호스트 {len(hosts)}곳: {', '.join(sorted(hosts))}")

    # 호스트 이름을 그대로 적으라는 뜻이 아니다. 그 사업자를 알아볼 수 있는
    # 말이 처리방침에 있으면 된다.
    known = {
        "www.googletagmanager.com": ("Google Analytics", "googletagmanager"),
        "pagead2.googlesyndication.com": ("AdSense",),
        "fonts.googleapis.com": ("Google Fonts", "글꼴"),
        "fonts.gstatic.com": ("Google Fonts", "글꼴"),
        "cdn.jsdelivr.net": ("jsDelivr", "jsdelivr"),
    }
    for host in sorted(hosts):
        needles = known.get(host, (host,))
        if not any(n.lower() in privacy.lower() for n in needles):
            failures.append(
                f"privacy.html: {host} 를 부르고 있는데 처리방침에 그에 해당하는 안내가 없습니다."
            )

    # 갯수를 단정하는 말도 본다. "두 가지 Google 서비스" 가 ②였다.
    google = {h for h in hosts if "google" in h or "gstatic" in h}
    # 같은 사업자의 호스트가 여럿이므로 서비스 수가 아니라 '단정 여부' 만 본다.
    if re.search(r"다음\s*(두|세|네)\s*가지", privacy):
        failures.append(
            "privacy.html: 외부 서비스 개수를 문장에 단정하고 있습니다. "
            "호스트가 늘면 조용히 틀린 말이 됩니다 — 개수를 세지 말고 목록만 두십시오."
            f" (지금 Google 계열 호스트 {len(google)}곳)"
        )


def main() -> int:
    check_sources()
    check_external_hosts()
    if failures:
        print()
        for f in failures:
            print(f"  ✗ {f}")
        print(f"\n공개 문서와 코드가 어긋납니다 — {len(failures)}건.")
        return 1
    print("\n✅ 공개 문서가 말하는 원천·외부 서비스가 코드와 맞습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
