"""url_https 의 갈래를 전부 확인한다 — 네트워크 없이.

이 판정이 틀리면 신청 링크가 죽는다. 특히 두 갈래가 위험하다.

  · HEAD 를 막아 405 를 주는 서버를 '실패' 로 보면, https 가 멀쩡한데도
    영영 http 로 남는다.
  · https 로 열었는데 http 로 되돌려 보내는 서버를 '성공' 으로 보면,
    실제로는 https 를 안 쓰는 곳에 https 링크를 걸어 버린다.

둘 다 실제 서버 없이는 재현하기 어려우므로 urlopen 을 가짜로 세워 확인한다.

    python3 scripts/check_url_https.py
"""
import sys, types, urllib.error, contextlib
sys.path.insert(0, 'scripts')
from collect import url_https as U

class Resp:
    def __init__(self, url, status=200): self._u, self.status = url, status
    def geturl(self): return self._u
    def __enter__(self): return self
    def __exit__(self, *a): return False

def fake(mapping):
    """호스트 → 응답(또는 예외)."""
    def _open(req, timeout=None):
        host = req.full_url.split('//', 1)[1].rstrip('/')
        r = mapping[host]
        if isinstance(r, Exception): raise r
        return Resp(r)
    return _open

# HEAD 는 전송 단계에서 끊기고 GET 은 되는 서버 — .go.kr WAF 에서 실제로 본 모양이다.
def head_dies_get_works(url_ok="https://g.go.kr/"):
    def _open(req, timeout=None):
        if req.get_method() == "HEAD":
            raise OSError("connection reset by peer")
        return Resp(url_ok)
    return _open

def both_die(req, timeout=None):
    raise TimeoutError()

CASES = [
    ("https 정상",           {"a.go.kr": "https://a.go.kr/"},                     "http://a.go.kr/x", "https://a.go.kr/x"),
    ("HEAD 막힘(405)",       {"b.go.kr": urllib.error.HTTPError("https://b.go.kr/", 405, "no", None, None)}, "http://b.go.kr/y", "https://b.go.kr/y"),
    ("404 지만 https 응답",   {"c.go.kr": urllib.error.HTTPError("https://c.go.kr/", 404, "nf", None, None)}, "http://c.go.kr/", "https://c.go.kr/"),
    ("https→http 리다이렉트", {"d.go.kr": "http://d.go.kr/"},                      "http://d.go.kr/z", "http://d.go.kr/z"),
    ("연결 실패",             {"e.go.kr": OSError("refused")},                     "http://e.go.kr/",  "http://e.go.kr/"),
    ("타임아웃",              {"f.go.kr": TimeoutError()},                         "http://f.go.kr/",  "http://f.go.kr/"),
]

ok = True
for name, mapping, src, want in CASES:
    U.reset_cache()
    orig = U.urllib.request.urlopen
    U.urllib.request.urlopen = fake(mapping)
    try:
        got = U.upgrade(src)
    finally:
        U.urllib.request.urlopen = orig
    mark = "O" if got == want else "X"
    if got != want: ok = False
    print(f"  {mark} {name:<22} {src}  →  {got}")

# ── HEAD 실패 → GET 폴백 ──
U.reset_cache()
_o = U.urllib.request.urlopen
U.urllib.request.urlopen = head_dies_get_works()
try:
    got = U.upgrade("http://g.go.kr/x")
finally:
    U.urllib.request.urlopen = _o
mark = "O" if got == "https://g.go.kr/x" else "X"
if got != "https://g.go.kr/x": ok = False
print(f"  {mark} HEAD 끊김 → GET 으로 확인{'':<6} {got}")
print(f"      이유 기록: {U._reasons['g.go.kr']}")

# ── 둘 다 실패하면 그대로 ──
U.reset_cache()
_o = U.urllib.request.urlopen
U.urllib.request.urlopen = both_die
try:
    got = U.upgrade("http://h.go.kr/")
finally:
    U.urllib.request.urlopen = _o
mark = "O" if got == "http://h.go.kr/" else "X"
if got != "http://h.go.kr/": ok = False
print(f"  {mark} HEAD·GET 모두 실패 → 유지{'':<3} {got}")
print(f"      이유 기록: {U._reasons['h.go.kr']}")
print(f"      summary(): {U.summary().splitlines()[-1].strip()}")

# ── HTTP 는 시간 초과인데 TLS 악수는 되는 서버 (work24.go.kr 에서 실제로 본 모양) ──
U.reset_cache()
_o, _t = U.urllib.request.urlopen, U._tls_ok
U.urllib.request.urlopen = both_die
U._tls_ok = lambda netloc, timeout: (True, "TLS 악수 성공(TLSv1.3)")
try:
    got = U.upgrade("http://slow.go.kr/apply")
finally:
    U.urllib.request.urlopen, U._tls_ok = _o, _t
mark = "O" if got == "https://slow.go.kr/apply" else "X"
if got != "https://slow.go.kr/apply": ok = False
print(f"  {mark} 읽기 시간 초과 + 악수 성공 → 올림  {got}")
print(f"      이유 기록: {U._reasons['slow.go.kr']}")

# ── HTTP 도 TLS 도 안 되는 서버 → 유지 ──
U.reset_cache()
_o, _t = U.urllib.request.urlopen, U._tls_ok
U.urllib.request.urlopen = both_die
U._tls_ok = lambda netloc, timeout: (False, "TLS 악수 실패(TimeoutError: )")
try:
    got = U.upgrade("http://dead.go.kr/")
finally:
    U.urllib.request.urlopen, U._tls_ok = _o, _t
mark = "O" if got == "http://dead.go.kr/" else "X"
if got != "http://dead.go.kr/": ok = False
print(f"  {mark} HTTP·TLS 모두 실패 → 유지{'':<5} {got}")

# ── 인증서 검증을 끄지 않았는가 ──
# 실제 서버로 확인하려 했더니 개발 컨테이너의 프록시가 TLS 를 가로채 자기
# 인증서를 내밀어서, 만료된 인증서도 통과해 버렸다. 네트워크에 기대는 검사는
# 환경에 따라 답이 달라져 쓸모가 없다. 코드가 검증을 켜 두는지를 직접 본다.
import ssl as _ssl, inspect  # noqa: E402
_src = inspect.getsource(U._tls_ok)
_ctx = _ssl.create_default_context()
_verifies = _ctx.verify_mode == _ssl.CERT_REQUIRED and _ctx.check_hostname
_no_bypass = ("CERT_NONE" not in _src and "check_hostname = False" not in _src
              and "_create_unverified" not in _src)
mark = "O" if (_verifies and _no_bypass) else "X"
if not (_verifies and _no_bypass): ok = False
print(f"  {mark} 인증서 검증 켜져 있음{'':<9} 기본 컨텍스트 검증={_verifies} · 우회 코드 없음={_no_bypass}")

# 건드리면 안 되는 것들
U.reset_cache()
for src in ("https://a.go.kr/", "", "mailto:x@y.kr", "tel:1588-0000"):
    got = U.upgrade(src)
    mark = "O" if got == src else "X"
    if got != src: ok = False
    print(f"  {mark} 그대로 둠{'':<14} {src!r}  →  {got!r}")

# 스위치
import os
U.reset_cache(); os.environ["WALAPP_SKIP_HTTPS_PROBE"] = "1"
got = U.upgrade("http://a.go.kr/")
del os.environ["WALAPP_SKIP_HTTPS_PROBE"]
mark = "O" if got == "http://a.go.kr/" else "X"
if got != "http://a.go.kr/": ok = False
print(f"  {mark} 프로브 끔{'':<14} http://a.go.kr/  →  {got}")

# 호스트 캐시 — 같은 호스트를 두 번 열지 않는다
U.reset_cache()
calls = []
orig = U.urllib.request.urlopen
U.urllib.request.urlopen = lambda req, timeout=None: (calls.append(req.full_url), Resp("https://g.go.kr/"))[1]
try:
    for _ in range(4): U.upgrade("http://g.go.kr/page")
finally:
    U.urllib.request.urlopen = orig
mark = "O" if len(calls) == 1 else "X"
if len(calls) != 1: ok = False
print(f"  {mark} 호스트 캐시{'':<12} 4번 호출 → 실제 프로브 {len(calls)}회")


# ─────────────────────────────────────────────────────────────
#  링크를 내리지 않는가 (sync._keep_verified_https)
# ─────────────────────────────────────────────────────────────
# 확인은 매 실행마다 네트워크를 탄다. 어느 날 실패하면 원천의 http 가 그대로
# 올라오는데, 그걸 받으면 링크가 평문으로 되돌아가고 '오늘 갱신된 제도' 로도
# 잡힌다. 확인 실패는 새 정보가 아니다.
import copy  # noqa: E402
import registry, schema  # noqa: E402
from sync import _keep_verified_https  # noqa: E402

_all = registry.load_all_records()
if not _all:
    print("\n  (레코드가 없어 내림 방지 검사는 건너뜁니다)")
else:
    base = next(iter(_all.values()))

    def guard(name, stored, incoming, want, want_hash_same):
        global ok
        existing = copy.deepcopy(base); existing.apply_url = stored
        existing.content_hash = schema.compute_hash(existing)
        new = copy.deepcopy(base); new.apply_url = incoming
        new.content_hash = schema.compute_hash(new)
        _keep_verified_https(new, existing)
        hit = (new.apply_url == want) and ((new.content_hash == existing.content_hash) == want_hash_same)
        if not hit: ok = False
        print(f"  {'O' if hit else 'X'} {name:<30} → {new.apply_url or '—'}")

    print()
    guard("확인 실패 → https 유지",   "https://a.go.kr/", "http://a.go.kr/",     "https://a.go.kr/", True)
    guard("원천이 주소를 바꿈 → 존중",  "https://a.go.kr/", "http://b.go.kr/",     "http://b.go.kr/",  False)
    guard("경로가 바뀜 → 존중",       "https://a.go.kr/x", "https://a.go.kr/y",  "https://a.go.kr/y", False)
    guard("저장이 http → 올림 허용",   "http://a.go.kr/",  "https://a.go.kr/",    "https://a.go.kr/", False)
    guard("저장이 비어 있음 → 그대로",  "",                 "http://a.go.kr/",     "http://a.go.kr/",  False)

print("\n" + ("전부 통과" if ok else "실패 있음"))
sys.exit(0 if ok else 1)
