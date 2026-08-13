"""공공데이터 API 응답 필드명 조사기 — 어댑터의 ID_FIELD·FIELD_MAP 을 확정하기 위한 도구.

어댑터에 적어 둔 필드명은 전부 **추정값**이다. 실제 값은 두 경로로 확인할 수 있고,
이 스크립트가 둘 다 지원한다.

    # ① 활용가이드(Swagger/OpenAPI) 문서에서 스키마 필드명 뽑기 — 키 발급 전에도 가능
    python3 scripts/inspect_api.py --docs "https://infuser.odcloud.kr/api/stages/44436/api-docs"
    python3 scripts/inspect_api.py --docs ./api-docs.json      # 내려받은 파일도 가능

    # ② 실제 API 를 한 번 호출해 응답 1건의 키를 그대로 덤프 — 가장 확실하다
    python3 scripts/inspect_api.py --probe "https://api.odcloud.kr/api/gov24/v3/serviceList" --key "발급받은키"

②가 최종 근거다. 문서와 실제 응답이 어긋나는 경우가 드물지 않아서, 키를 받은 뒤에는
반드시 ②로 확인할 것.

출력에서 확인할 것:
  · **서비스 고유 ID** — 이 값이 어댑터의 `ID_FIELD` 가 된다. 가장 중요하다.
    제도 페이지의 파일 경로가 이 값으로 결정되므로, 잘못 잡으면 같은 제도가
    매일 새 페이지로 발행된다.
  · 지원대상 / 지원내용 / 선정기준 / 신청방법 / 구비서류 / 신청기한 / 소관기관 필드명
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

TIMEOUT = 20
UA = "Mozilla/5.0 (compatible; walapp-inspect/1.0)"

# 고유 ID 후보로 볼 이름 패턴. 앞에 있을수록 강한 신호다.
ID_PATTERNS = (
    (re.compile(r"^서비스\s*ID$|^servId$", re.I), 100),
    (re.compile(r"서비스.*(ID|아이디|코드|번호)", re.I), 90),
    (re.compile(r"^(id|key|no|seq)$", re.I), 70),
    (re.compile(r"(ID|아이디)$", re.I), 60),
    (re.compile(r"(코드|번호|CD|CODE|NO)$", re.I), 40),
)

# 어댑터 FIELD_MAP 에 채워야 하는 항목 → (정규식, 점수).
# 점수를 두는 이유: 힌트가 겹치는 필드가 많다. 예를 들어 '신청기한' 과
# '온라인신청사이트URL' 은 둘 다 '신청' 을 포함하므로, 단순 부분일치로 고르면
# 같은 필드가 두 항목에 배정돼 dict 키가 중복된다(뒤엣것이 앞엣것을 덮어쓴다).
# 아래 점수로 정렬해 필드·항목을 각각 한 번씩만 배정한다.
WANTED: dict[str, tuple[tuple[str, int], ...]] = {
    "name":                ((r"서비스명|사업명|제도명|servNm", 100), (r"^(title|name)$", 60)),
    "org":                 ((r"소관기관|소관부처|부처명", 100), (r"기관명|담당부서|부서명", 70)),
    "target_raw":          ((r"지원대상", 100), (r"대상", 60)),
    "benefit_raw":         ((r"지원내용", 100), (r"급여|혜택|지원금액", 70)),
    "criteria_raw":        ((r"선정기준", 100), (r"자격|요건|기준", 60)),
    "how_to_raw":          ((r"신청방법|신청절차", 100), (r"접수방법|처리절차", 70)),
    "documents_raw":       ((r"구비서류|제출서류", 100), (r"서류", 60)),
    "apply_period_raw":    ((r"신청기한|신청기간|접수기간", 100), (r"기한|기간", 50)),
    "apply_url":           ((r"(온라인|인터넷).*(신청).*(URL|주소|사이트)", 100),
                            (r"신청.*(URL|주소|사이트)", 90),
                            (r"온라인.*(URL|주소)", 70)),
    "official_url":        ((r"상세.*(URL|주소|링크)", 100), (r"(URL|링크|주소)$", 60)),
    "source_category_raw": ((r"서비스분야|지원유형", 100), (r"분야|유형|카테고리", 60)),
}


def fetch_text(target: str) -> str:
    """URL 또는 로컬 파일에서 원문 읽기."""
    if not target.lower().startswith(("http://", "https://")):
        return Path(target).read_text(encoding="utf-8")
    request = urllib.request.Request(target, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
        raw = resp.read()
    for encoding in ("utf-8", "euc-kr", "cp949"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def fetch_json(target: str) -> dict:
    """URL 또는 로컬 파일에서 JSON 읽기."""
    return json.loads(fetch_text(target))


def parse_xml_rows(text: str) -> tuple[dict, list[dict]]:
    """XML 응답을 (최상위 스칼라 필드, 반복 레코드 목록) 으로 나눈다.

    상세조회 응답은 최상위에 본문 필드가 있고 그 아래 반복 섹션이 따로 달리는
    형태가 흔하다. 반복 요소만 뽑으면 정작 필요한 본문 필드를 통째로 놓친다.
    (실제로 복지로 상세조회에서 이 일이 났다)
    """
    import xml.etree.ElementTree as ET
    from collections import Counter

    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise ValueError(f"XML 파싱 실패: {e}") from e

    # 최상위 스칼라 = 루트의 직계 자식 중 손자가 없는 것
    scalars = {
        child.tag: (child.text or "").strip()
        for child in root if len(child) == 0
    }

    # 반복 레코드 = 자식이 여럿이고 손자가 없는 요소 중 가장 많이 반복되는 태그
    candidates = [
        el for el in root.iter()
        if el is not root and len(el) >= 2 and all(len(c) == 0 for c in el)
    ]
    rows: list[dict] = []
    if candidates:
        common = Counter(el.tag for el in candidates).most_common(1)[0][0]
        rows = [
            {c.tag: (c.text or "").strip() for c in el}
            for el in candidates if el.tag == common
        ]
    return scalars, rows


# ─────────────────────────────────────────────────────────────
#  ① 활용가이드(OpenAPI) 파싱
# ─────────────────────────────────────────────────────────────
def schemas_of(doc: dict) -> dict[str, dict]:
    """OpenAPI 2(definitions)와 3(components.schemas)을 모두 받는다."""
    if isinstance(doc.get("definitions"), dict):
        return doc["definitions"]
    return (doc.get("components") or {}).get("schemas") or {}


def walk_properties(schema: dict, schemas: dict, seen: set[str] | None = None) -> list[str]:
    """스키마에서 프로퍼티 이름을 재귀로 모은다 ($ref·배열 포함)."""
    seen = seen if seen is not None else set()
    names: list[str] = []

    ref = schema.get("$ref")
    if ref:
        key = ref.rsplit("/", 1)[-1]
        if key in seen:
            return names
        seen.add(key)
        return walk_properties(schemas.get(key, {}), schemas, seen)

    if schema.get("type") == "array" or "items" in schema:
        return walk_properties(schema.get("items") or {}, schemas, seen)

    for name, prop in (schema.get("properties") or {}).items():
        names.append(name)
        if isinstance(prop, dict) and ("$ref" in prop or prop.get("type") in ("array", "object")):
            names.extend(walk_properties(prop, schemas, seen))
    return names


def inspect_docs(target: str) -> None:
    doc = fetch_json(target)
    info = doc.get("info") or {}

    print("━" * 62)
    print(f"  {info.get('title') or '(제목 없음)'}")
    if info.get("description"):
        print(f"  {str(info['description']).strip()[:200]}")
    print("━" * 62)

    servers = doc.get("servers") or []
    if servers:
        print("\n[base URL]")
        for s in servers:
            print(f"  {s.get('url')}")
    elif doc.get("host"):
        scheme = (doc.get("schemes") or ["https"])[0]
        print(f"\n[base URL]\n  {scheme}://{doc['host']}{doc.get('basePath', '')}")

    paths = doc.get("paths") or {}
    print(f"\n[오퍼레이션] {len(paths)}개")
    for path, methods in paths.items():
        for method, op in (methods or {}).items():
            if method.lower() not in ("get", "post"):
                continue
            print(f"\n  {method.upper()} {path}")
            if op.get("summary"):
                print(f"    설명: {op['summary']}")
            params = op.get("parameters") or []
            if params:
                print("    요청 파라미터:")
                for p in params:
                    required = " (필수)" if p.get("required") else ""
                    desc = p.get("description") or ""
                    print(f"      - {p.get('name')}{required}  {desc[:60]}")

    schemas = schemas_of(doc)
    all_fields: list[str] = []
    print(f"\n[응답 스키마] {len(schemas)}개")
    for name, schema in schemas.items():
        fields = walk_properties(schema, schemas)
        if not fields:
            continue
        print(f"\n  ▸ {name} — {len(fields)}개 필드")
        for f in fields:
            print(f"      {f}")
        all_fields.extend(fields)

    report(sorted(set(all_fields)))


# ─────────────────────────────────────────────────────────────
#  ② 실제 응답 프로브
# ─────────────────────────────────────────────────────────────
def inspect_probe(endpoint: str, api_key: str, per_page: int = 3, extra: str = "",
                  raw: bool = False) -> None:
    # odcloud 계열은 page/perPage, apis.data.go.kr 계열은 pageNo/numOfRows 를 쓴다.
    # 양쪽을 다 넣어도 서로 무시하므로 한 번에 보낸다.
    params = {
        "serviceKey": api_key,
        "page": 1, "perPage": per_page,
        "pageNo": 1, "numOfRows": per_page,
    }
    query = urllib.parse.urlencode(params)
    if extra:
        query += "&" + extra.lstrip("&")
    url = f"{endpoint}{'&' if '?' in endpoint else '?'}{query}"
    print(f"호출: {endpoint} (rows={per_page}{' · ' + extra if extra else ''})\n")

    try:
        text = fetch_text(url)
    except Exception as e:
        print(f"✗ 요청 실패: {e}")
        print("\n  키가 승인 직후면 반영에 시간이 걸릴 수 있습니다.")
        print("  Encoding/Decoding 키를 바꿔 넣어 보세요 — 둘 중 하나만 통하는 경우가 흔합니다.")
        sys.exit(1)

    stripped = text.lstrip()
    if stripped.startswith("<"):
        # 복지로 계열은 XML 로만 응답한다
        try:
            scalars, rows = parse_xml_rows(text)
        except ValueError as e:
            print(f"✗ {e}")
            print(text[:800])
            sys.exit(1)
        total = "?"
        import re as _re
        m = _re.search(r"<totalCount>\s*(\d+)\s*</totalCount>", text)
        if m:
            total = m.group(1)

        if scalars:
            print(f"[최상위 필드] {len(scalars)}개 — 상세조회는 보통 여기 본문이 있습니다")
            for key, value in scalars.items():
                shown = value.replace("\n", " ")
                print(f"  {key:<24} = {shown[:70]}{'…' if len(shown) > 70 else ''}")
            print()
        if rows:
            print(f"[반복 섹션] <{'?'}> {len(rows)}개 — 이름/내용 쌍이면 섹션형 구조입니다")
            for row in rows[:8]:
                print("  " + " | ".join(f"{k}={str(v)[:40]}" for k, v in row.items()))
            print()

        if not rows and not scalars:
            print("✗ 응답에서 레코드를 찾지 못했습니다. 원문 앞부분:")
            print(text[:1200])
            sys.exit(1)
        if not rows:
            rows = [scalars]
    else:
        payload = json.loads(text)
        rows = payload.get("data") or payload.get("body") or payload.get("items") or []
        if isinstance(rows, dict):
            rows = rows.get("items") or [rows]
        if not rows:
            print("✗ 응답에 데이터 행이 없습니다. 최상위 키:", list(payload.keys()))
            print(json.dumps(payload, ensure_ascii=False, indent=2)[:1200])
            sys.exit(1)
        total = payload.get("totalCount", "?")

    if raw:
        print("━" * 62)
        print("  응답 원문 (인증키는 응답에 포함되지 않습니다)")
        print("━" * 62)
        print(text[:6000])
        if len(text) > 6000:
            print(f"\n… (전체 {len(text)}자 중 앞 6000자)")
        print()

    print(f"[응답 메타] 총 {total}건 · 이번 응답 {len(rows)}행\n")

    first = rows[0]
    print("[첫 행의 필드와 값]")
    for key, value in first.items():
        text = str(value).replace("\n", " ")
        print(f"  {key:<24} = {text[:70]}{'…' if len(text) > 70 else ''}")

    # 여러 행에서 값이 전부 다른 필드 = ID 후보 (강한 신호)
    if len(rows) > 1:
        unique_fields = [
            k for k in first
            if len({str(r.get(k)) for r in rows}) == len(rows) and all(str(r.get(k)).strip() for r in rows)
        ]
        if unique_fields:
            print("\n[행마다 값이 전부 다른 필드] ← 고유 ID 후보")
            # 이름 패턴 점수가 높은 것을 위로 올린다. 제도명·지원내용도 행마다 다르므로
            # '값이 다르다' 만으로는 ID 를 특정할 수 없다.
            def name_score(field: str) -> int:
                return max((s for p, s in ID_PATTERNS if p.search(field)), default=0)
            for k in sorted(unique_fields, key=lambda f: (-name_score(f), f)):
                mark = " ★" if name_score(k) >= 60 else ""
                print(f"  {k}{mark}  예: {', '.join(str(r.get(k)) for r in rows[:3])}")
            if len(rows) < 10:
                print(f"  (표본 {len(rows)}행 — `--rows 20` 으로 늘리면 판별이 더 확실해집니다)")

    report(list(first.keys()))


# ─────────────────────────────────────────────────────────────
#  결론 리포트
# ─────────────────────────────────────────────────────────────
def report(fields: list[str]) -> None:
    if not fields:
        print("\n✗ 필드를 찾지 못했습니다. 문서 구조가 예상과 다를 수 있습니다.")
        return

    print("\n" + "━" * 62)
    print("  결론 — 어댑터에 채울 값")
    print("━" * 62)

    scored: list[tuple[int, str]] = []
    for field in fields:
        best = max((score for pattern, score in ID_PATTERNS if pattern.search(field)), default=0)
        if best:
            scored.append((best, field))
    scored.sort(key=lambda x: (-x[0], x[1]))

    print("\n▸ ID_FIELD 후보 (위쪽일수록 유력)")
    if scored:
        for score, field in scored[:6]:
            print(f"    ID_FIELD = \"{field}\"")
    else:
        print("    ✗ 자동으로 못 찾았습니다. 위 목록에서 제도마다 값이 다른 필드를 직접 고르세요.")

    # 필드·항목을 각각 한 번씩만 배정한다 (점수 높은 짝부터).
    id_field = scored[0][1] if scored else None
    candidates: list[tuple[int, str, str]] = []
    for dest, rules in WANTED.items():
        for field in fields:
            if field == id_field:
                continue  # ID 필드는 FIELD_MAP 에 넣지 않는다
            best = max((score for pattern, score in rules
                        if re.search(pattern, field, re.I)), default=0)
            if best:
                candidates.append((best, dest, field))
    candidates.sort(key=lambda x: (-x[0], x[1], x[2]))

    assigned: dict[str, str] = {}
    used_fields: set[str] = set()
    for _score, dest, field in candidates:
        if dest in assigned or field in used_fields:
            continue
        assigned[dest] = field
        used_fields.add(field)

    print("\n▸ FIELD_MAP 초안 (검토 후 어댑터에 붙여넣기)")
    print("    FIELD_MAP = {")
    for dest in WANTED:
        field = assigned.get(dest)
        if field:
            print(f'        "{field}": "{dest}",')
        else:
            print(f'        # ✗ 못 찾음 → "{dest}"  (필드 목록에서 직접 고르세요)')
    print("    }")

    unmapped = [f for f in fields if f not in used_fields and f != id_field]
    if unmapped:
        print(f"\n▸ 매핑되지 않은 필드 {len(unmapped)}개 (필요하면 알려 주세요)")
        print("    " + ", ".join(unmapped[:25]) + ("…" if len(unmapped) > 25 else ""))

    print("\n다음 단계: 위 출력을 그대로 붙여 주시면 두 어댑터의 매핑을 채우겠습니다.")
    print("  · scripts/collect/adapters/bojo24.py")
    print("  · scripts/collect/adapters/welfare_central.py")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="공공데이터 API 응답 필드명 조사 — 어댑터 ID_FIELD/FIELD_MAP 확정용",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--docs", metavar="URL|파일",
                       help="활용가이드(Swagger/OpenAPI) 문서 주소 또는 내려받은 JSON 파일")
    group.add_argument("--probe", metavar="ENDPOINT",
                       help="실제 API 엔드포인트를 호출해 응답 키를 덤프 (--key 필요)")
    parser.add_argument("--key", help="공공데이터포털 인증키 (--probe 와 함께)")
    parser.add_argument("--rows", type=int, default=3, help="프로브로 받아 볼 행 수 (기본 3)")
    parser.add_argument("--extra", default="",
                        help="추가 쿼리스트링 (예: \"callTp=L&srchKeyCode=001\")")
    parser.add_argument("--raw", action="store_true",
                        help="응답 원문을 그대로 출력한다. 구조 추정이 어긋날 때 쓴다. "
                             "응답 본문에는 인증키가 들어 있지 않다.")
    args = parser.parse_args()

    if args.docs:
        inspect_docs(args.docs)
    else:
        api_key = args.key or __import__("os").environ.get("DATA_GO_KR_API_KEY", "")
        if not api_key:
            parser.error("--probe 에는 --key 또는 DATA_GO_KR_API_KEY 환경변수가 필요합니다.")
        inspect_probe(args.probe, api_key, args.rows, args.extra, args.raw)
    return 0


if __name__ == "__main__":
    sys.exit(main())
