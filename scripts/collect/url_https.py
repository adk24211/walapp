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
  · 호스트 단위로 캐시한다. work24.go.kr 처럼 여러 제도가 같은 창구를 쓴다.

네트워크가 없는 곳(오프라인 검증, 목 모드)에서는 호스트마다 타임아웃만큼
기다리게 되므로 WALAPP_SKIP_HTTPS_PROBE=1 로 통째로 끌 수 있다. 껐을 때는
아무것도 바꾸지 않는다 — 확인 못 한 것을 올리지는 않는다.
"""
from __future__ import annotations

import logging
import os
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit

log = logging.getLogger("url_https")

TIMEOUT = float(os.environ.get("WALAPP_HTTPS_PROBE_TIMEOUT", "4"))
UA = "Mozilla/5.0 (compatible; walapp-linkcheck/1.0)"

# 호스트 → https 가 열리는가. None 은 아직 안 봤다는 뜻.
_probed: dict[str, bool] = {}


def skip_probe() -> bool:
    return os.environ.get("WALAPP_SKIP_HTTPS_PROBE", "").strip() not in ("", "0", "false")


def reset_cache() -> None:
    """테스트용. 실행 중에는 호스트 판정을 바꾸지 않는다."""
    _probed.clear()


def probe(netloc: str, *, timeout: float | None = None) -> bool:
    """이 호스트가 https 를 받아 주는가."""
    if netloc in _probed:
        return _probed[netloc]

    ok = False
    url = f"https://{netloc}/"
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout or TIMEOUT) as resp:
            # 리다이렉트를 따라간 뒤의 최종 주소가 기준이다.
            # https → http 로 되돌리는 서버는 https 를 쓰지 않는 것이다.
            ok = urlsplit(resp.geturl()).scheme == "https"
    except urllib.error.HTTPError as err:
        # 4xx·5xx 도 https 로 응답이 온 것이다. HEAD 를 막아 405 를 주는
        # 서버가 흔한데, 그건 https 를 못 쓴다는 뜻이 아니다.
        final = getattr(err, "url", None) or url
        ok = urlsplit(final).scheme == "https"
    except Exception as exc:  # noqa: BLE001 — 무엇이 터지든 '모름' 으로 본다
        log.debug("https 확인 실패 %s: %s", netloc, exc)
        ok = False

    _probed[netloc] = ok
    log.debug("https %s: %s", netloc, "가능" if ok else "확인 안 됨")
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
    bits = [f"https 확인 {len(_probed)}개 호스트", f"올림 {len(up)}", f"유지 {len(keep)}"]
    if keep:
        bits.append("유지된 호스트: " + ", ".join(keep))
    return " · ".join(bits)
