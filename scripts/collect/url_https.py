"""http:// 링크를 https:// 로 올린다 — 열리는 것만.

원천(bojo24)이 주는 신청 창구 주소에는 아직 http 가 섞여 있다. 정부·공공기관
사이트는 대부분 https 를 제공하는데 데이터에 옛 주소가 남아 있는 것이다.
그대로 두면 이 사이트가 사람을 평문 연결로 내보낸다.

그렇다고 문자열만 https 로 바꾸면 안 된다. https 를 열지 않는 서버가 하나라도
있으면 그 제도의 신청 버튼이 죽는다. **신청 링크가 죽는 건 http 로 나가는 것보다
나쁘다.** 지원금을 받으러 온 사람이 막다른 곳에 도착하기 때문이다.

그래서 실제로 열어 보고, 열릴 때만 바꾼다.

  · 실패·타임아웃·차단은 전부 '모름' 으로 보고 http 를 그대로 둔다.
  · https 가 http 로 되돌려 보내면(리다이렉트) 그 서버는 https 를 쓰지 않는
    것이므로 올리지 않는다.
  · 4xx 응답은 '열린다' 로 본다. 404 든 403 든 https 로 **응답은 했다** 는 뜻이라
    연결 자체는 되는 것이다. 우리가 확인하려는 건 페이지의 존재가 아니라
    https 를 받아 주는지다.
  · HEAD 가 전송 단계에서 끊기면 GET 으로, 그것도 안 되면 TLS 악수만 따로
    확인한다. 응답이 느려 읽기가 시간 초과되는 서버라도 악수가 됐다면 그
    호스트는 https 를 받아 주는 것이다.
  · 호스트 단위로 캐시한다. work24.go.kr 처럼 여러 제도가 같은 창구를 쓴다.

확인이 원리적으로 불가능한 호스트가 하나 있다(work24.go.kr). 러너가 해외
데이터센터 IP 라서 그 서버가 우리를 안 받아 준다. 그런 곳만 VERIFIED_BY_HAND
에 손으로 적어 두고 프로브를 건너뛴다. 그 목록의 규칙은 아래 주석 참고.

네트워크가 없는 곳(오프라인 검증, 목 모드)에서는 호스트마다 타임아웃만큼
기다리게 되므로 WALAPP_SKIP_HTTPS_PROBE=1 로 통째로 끌 수 있다. 껐을 때는
아무것도 바꾸지 않는다 — 확인 못 한 것을 올리지 않고, 손으로 적어 둔 목록도
쓰지 않는다. 목 파이프라인이 주소를 건드리면 안 되기 때문이다.
"""
from __future__ import annotations

import logging
import os
import socket
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit

log = logging.getLogger("url_https")

# 4초로 시작했다가 8초로 올렸다. 첫 실행에서 work24.go.kr·bokjiro.go.kr 처럼
# https 를 분명히 지원하는 정부 사이트가 '확인 안 됨' 으로 떨어졌는데, 응답이
# 느린 것이 원인 후보 중 하나였다. 하루 한 번 도는 작업이라 넉넉히 준다.
TIMEOUT = float(os.environ.get("WALAPP_HTTPS_PROBE_TIMEOUT", "8"))
UA = "Mozilla/5.0 (compatible; walapp-linkcheck/1.0)"
# 일부 공공기관 WAF 는 Accept 헤더가 없는 요청을 거른다.
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

# ── 사람이 직접 확인한 호스트 ──
# 프로브가 닿지 못하는 호스트를 위한 예외다.
#
# GitHub Actions 러너는 해외 데이터센터 IP 라서, 국내 포털 중에 이걸 막거나
# 무시하는 곳이 있다. work24.go.kr 이 그랬다 — 같은 .go.kr 인 bokjiro.go.kr 은
# HEAD 200 으로 즉시 통과하는데 work24 는 HEAD·GET·TLS 악수까지 전부 시간
# 초과였다. 정부 도메인을 일괄 차단하는 게 아니라 그 호스트만 우리를 안
# 받아 준다. 사이트가 https 를 안 하는 게 아니라 우리가 확인할 수 없는 것이다.
#
# ⚠️ 여기 넣는 것은 '확인했다' 가 아니라 '확인한 사람이 있다' 는 뜻이다.
#    브라우저로 직접 열어 보고, 누가 언제 무엇을 봤는지 함께 적을 것.
#    추측으로 채우면 이 목록이 있는 이유가 사라지고, 죽은 링크를 만드는
#    지름길이 된다.
VERIFIED_BY_HAND = {
    # 2026-08-19 adk24211 — 브라우저에서 https://www.work24.go.kr/ 가
    # https://www.work24.go.kr/cm/main.do 로 정상 리다이렉트되는 것을 확인.
    # 러너에서는 HEAD·GET·TLS 악수가 모두 시간 초과된다.
    "www.work24.go.kr",
}

# 호스트 → https 가 열리는가. 없으면 아직 안 봤다는 뜻.
_probed: dict[str, bool] = {}
# 호스트 → 그렇게 판정한 이유. 실패 원인을 로그로 봐야 다음에 고칠 수 있다.
_reasons: dict[str, str] = {}


def skip_probe() -> bool:
    return os.environ.get("WALAPP_SKIP_HTTPS_PROBE", "").strip() not in ("", "0", "false")


def reset_cache() -> None:
    """테스트용. 실행 중에는 호스트 판정을 바꾸지 않는다."""
    _probed.clear()
    _reasons.clear()


def _attempt(netloc: str, method: str, timeout: float) -> tuple[bool | None, str]:
    """한 번 두드려 본다.

    반환값의 첫 항목: True 가능 · False 불가 · None 판단 못 함(다음 방법을 시도).
    """
    url = f"https://{netloc}/"
    req = urllib.request.Request(url, method=method, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # 리다이렉트를 따라간 뒤의 최종 주소가 기준이다.
            # https → http 로 되돌리는 서버는 https 를 쓰지 않는 것이다.
            if urlsplit(resp.geturl()).scheme == "https":
                return True, f"{method} {resp.status}"
            return False, f"{method} {resp.status} → http 로 되돌림"
    except urllib.error.HTTPError as err:
        # 4xx·5xx 도 https 로 응답이 온 것이다. HEAD 를 막아 405 를 주는
        # 서버가 흔한데, 그건 https 를 못 쓴다는 뜻이 아니다.
        final = getattr(err, "url", None) or url
        if urlsplit(final).scheme == "https":
            return True, f"{method} {err.code}"
        return False, f"{method} {err.code} → http 로 되돌림"
    except Exception as exc:  # noqa: BLE001 — 무엇이 터지든 '모름' 으로 본다
        return None, f"{method} 실패({type(exc).__name__}: {exc})"


def _tls_ok(netloc: str, timeout: float) -> tuple[bool, str]:
    """이 호스트와 https 로 악수가 되는가.

    HEAD·GET 이 둘 다 '읽기 시간 초과' 로 떨어지는 서버가 있다(work24.go.kr).
    그런데 읽기가 시간 초과됐다는 건 **연결과 TLS 협상은 이미 끝났다**는 뜻이다.
    응답이 늦을 뿐 https 를 받아 주지 않는 게 아니다. 그래서 마지막으로 악수만
    따로 해 본다.

    인증서 검증까지 하는 기본 컨텍스트를 쓴다. 악수가 통과했다면 그 호스트는
    올바른 인증서로 https 를 서빙하고 있다는 뜻이고, 우리가 알고 싶은 것은
    딱 거기까지다 — 스킴만 바꿀 뿐 호스트와 경로는 그대로 두기 때문이다.

    ⚠️ 검증을 끄지 말 것. 인증서가 틀린 곳으로 사람을 보내면 http 로 보내는
       것보다 나쁘다.
    """
    host = netloc.split(":")[0]
    port = int(netloc.split(":")[1]) if ":" in netloc else 443
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                return True, f"TLS 악수 성공({tls.version()})"
    except Exception as exc:  # noqa: BLE001
        return False, f"TLS 악수 실패({type(exc).__name__}: {exc})"


def probe(netloc: str, *, timeout: float | None = None) -> bool:
    """이 호스트가 https 를 받아 주는가.

    HEAD 로 먼저 두드리고, 연결 자체가 안 되면 GET 으로 한 번 더 본다.
    HEAD 를 응답 코드로 거절하는 서버(405)는 위에서 이미 '가능' 으로 잡히므로,
    여기까지 오는 것은 연결·TLS·타임아웃 같은 전송 단계 실패다. 그런 서버 중에
    HEAD 만 연결 단계에서 끊는 곳이 있어 GET 으로 확인한다. 본문은 읽지 않는다.
    """
    if netloc in _probed:
        return _probed[netloc]

    if netloc in VERIFIED_BY_HAND:
        _probed[netloc] = True
        _reasons[netloc] = "사람이 직접 확인한 호스트 — 프로브 건너뜀"
        log.info("https %s: 가능 (%s)", netloc, _reasons[netloc])
        return True

    limit = timeout or TIMEOUT
    reasons: list[str] = []
    ok = False
    settled = False
    for method in ("HEAD", "GET"):
        verdict, why = _attempt(netloc, method, limit)
        reasons.append(why)
        if verdict is not None:
            ok = verdict
            settled = True
            break

    # HTTP 로는 판단이 안 났다 — 연결·TLS·타임아웃 단계에서 막힌 것이다.
    # 악수만 따로 확인한다. 자세한 이유는 _tls_ok.
    if not settled:
        ok, why = _tls_ok(netloc, limit)
        reasons.append(why)

    _probed[netloc] = ok
    _reasons[netloc] = " · ".join(reasons)
    log.info("https %s: %s (%s)", netloc, "가능" if ok else "확인 안 됨", _reasons[netloc])
    return ok


def upgrade(url: str, *, timeout: float | None = None) -> str:
    """http:// 주소를 https:// 로. 확인되지 않으면 원래 값 그대로."""
    if not url:
        return url
    if not url.lower().startswith("http://"):
        return url
    if skip_probe():
        return url

    parts = urlsplit(url)
    if not parts.netloc:
        return url
    if not probe(parts.netloc, timeout=timeout):
        return url
    return urlunsplit(("https", parts.netloc, parts.path, parts.query, parts.fragment))


def summary() -> str:
    """이번 실행에서 뭘 확인했는지 한 줄. 동기화 로그에 남긴다."""
    if not _probed:
        return "https 확인: 없음"
    up = sorted(h for h, ok in _probed.items() if ok)
    keep = sorted(h for h, ok in _probed.items() if not ok)
    lines = [f"https 확인 {len(_probed)}개 호스트 · 올림 {len(up)} · 유지 {len(keep)}"]
    # 유지된 호스트는 이유까지 남긴다. 이게 없으면 왜 안 올라갔는지 알 길이 없어
    # 다음에 또 추측만 하게 된다.
    by_hand = sorted(h for h in up if h in VERIFIED_BY_HAND)
    if by_hand:
        # 손으로 넣은 예외는 눈에 띄게 남긴다. 조용히 늘어나면 안 되는 목록이다.
        lines.append("  손으로 확인한 호스트: " + ", ".join(by_hand))
    for host in keep:
        lines.append(f"  유지 {host}: {_reasons.get(host, '이유 기록 없음')}")
    return "\n".join(lines)
