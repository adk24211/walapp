"""발행 원장 — 중복 방지의 단일 진실 공급원.

`_data/registry.json` 은 "이 사이트가 지금까지 무엇을 발행했는가" 를 기록한다.
수집·발행·갱신 모든 단계가 이 파일을 먼저 조회하므로, 같은 제도가 두 번
새 글로 나가는 일이 자료구조 차원에서 불가능해진다. (REDESIGN.md §6.2)

git 에 커밋되므로 워크플로우 재실행이나 롤백에도 이력이 보존된다.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from schema import ProgramRecord

log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "_data"
PROGRAMS_DIR = ROOT / "_programs"

REGISTRY_FILE = DATA_DIR / "registry.json"
QUEUE_FILE = DATA_DIR / "queue.json"
REVIEW_FILE = DATA_DIR / "review_needed.json"
INCOMPLETE_FILE = DATA_DIR / "incomplete.json"
# 신청기한 표기 분포 (scripts/sync.py PeriodStats). 사이트에 나가지 않는 진단용이다.
PERIOD_FILE = DATA_DIR / "period_formats.json"

# 제도 원본 레코드. REDESIGN.md 는 `_data/programs/` 로 적었으나 `_records/` 로 옮겼다.
# Jekyll 은 `_data` 하위를 전부 읽어 site.data 에 올리는데, 레코드가 수천 건이 되면
# 빌드마다 쓸데없이 파싱된다. 밑줄로 시작하는 디렉터리는 Jekyll 이 통째로 무시한다.
RECORDS_DIR = ROOT / "_records"

# 유사도 임계값 — 이 이상이면 사람이 확인하도록 검토 대기열에 넣는다.
# 자동 병합하지 않는 이유: '청년월세지원' 과 '청년월세 한시 특별지원' 처럼
# 이름이 비슷해도 실제로 다른 제도인 경우가 있다.
SIMILARITY_THRESHOLD = 0.85


# ─────────────────────────────────────────────────────────────
#  JSON I/O
# ─────────────────────────────────────────────────────────────
def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.error("JSON 읽기 실패 [%s]: %s", path.name, e)
        return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


# ─────────────────────────────────────────────────────────────
#  원장
# ─────────────────────────────────────────────────────────────
@dataclass
class Entry:
    name: str
    slug: str
    path: str
    content_hash: str
    first_published: str
    last_updated: str
    last_checked: str = ""
    revision: int = 1
    status: str = "active"

    def to_dict(self) -> dict:
        return self.__dict__.copy()


class Registry:
    def __init__(self, path: Path = REGISTRY_FILE):
        self.path = path
        raw = _read_json(path, {})
        self.entries: dict[str, Entry] = {
            program_id: Entry(**data) for program_id, data in raw.items()
        }

    # ── 조회 ──
    def __contains__(self, program_id: str) -> bool:
        return program_id in self.entries

    def __len__(self) -> int:
        return len(self.entries)

    def get(self, program_id: str) -> Entry | None:
        return self.entries.get(program_id)

    def is_changed(self, record: ProgramRecord) -> bool:
        """이미 발행된 제도의 내용이 원천에서 바뀌었는지."""
        entry = self.entries.get(record.id)
        return entry is not None and entry.content_hash != record.content_hash

    def published_names(self) -> dict[str, str]:
        """유사도 비교용 {제도명: program_id}."""
        return {e.name or e.slug: pid for pid, e in self.entries.items()}

    # ── 기록 ──
    def register(self, record: ProgramRecord, today: str) -> Entry:
        """신규 발행 기록."""
        entry = Entry(
            name=record.name,
            slug=record.slug,
            path=f"_programs/{record.path()}",
            content_hash=record.content_hash,
            first_published=today,
            last_updated=today,
            last_checked=today,
            revision=1,
            status=record.status,
        )
        self.entries[record.id] = entry
        return entry

    def mark_updated(self, record: ProgramRecord, today: str) -> Entry:
        """내용이 바뀌어 갱신했을 때."""
        entry = self.entries.get(record.id)
        if entry is None:
            return self.register(record, today)
        entry.name = record.name
        entry.slug = record.slug
        entry.path = f"_programs/{record.path()}"
        entry.content_hash = record.content_hash
        entry.last_updated = today
        entry.last_checked = today
        entry.revision += 1
        entry.status = record.status
        return entry

    # ⚠️ 여기에 '원장 해시만 맞추는' 함수를 두지 말 것. 한 번 뒀다가 되돌렸다.
    #
    # 그럴듯해 보인다 — 레코드를 고치는 스크립트(upgrade_urls·reclassify_audiences)
    # 가 _records/ 만 쓰니 원장도 맞춰 주면 다음 동기화가 '동일' 로 잡을 것 같다.
    # 실제로는 반대다.
    #
    # 원장의 content_hash 는 **수집 시점에 원천 값으로 계산된 값**이다
    # (collect/adapters/base.py). 저장된 레코드에서 다시 계산한 값은 그것과
    # 같다는 보장이 없다 — 저장할 때 clean_text 를 거치기 때문이다. 그래서
    # 지역에서 계산한 해시로 원장을 덮어쓰면, 맞추려던 것이 오히려 어긋난다.
    #
    # 2026-08-22 실행이 그랬다. 재분류한 레코드 22개 중 19개가 '변경' 으로
    # 잡혀 8건이 재생성됐다(그날 한도 32건 중 8건). 그중 7건은 동기화가 매긴
    # 대상이 우리가 매긴 것과 **완전히 같았다** — 분류가 아니라 해시 때문이었다.
    #
    # 분류 규칙이나 해시 대상 필드를 바꾸면 영향받은 레코드당 재생성 1회가 든다.
    # 그건 피할 수 없는 비용이고, mark_updated 가 원장을 수집 시점 해시로
    # 되돌려 놓으므로 한 번으로 끝난다.

    def mark_checked(self, program_id: str, today: str, status: str | None = None) -> None:
        """내용은 그대로고 확인만 했을 때. revision 은 올리지 않는다."""
        entry = self.entries.get(program_id)
        if entry is None:
            return
        entry.last_checked = today
        if status:
            entry.status = status

    def save(self) -> None:
        _write_json(self.path, {pid: e.to_dict() for pid, e in self.entries.items()})
        log.info("원장 저장: %d건 (%s)", len(self.entries), self.path.name)


# ─────────────────────────────────────────────────────────────
#  레코드 저장소 (_data/programs/{id}.json)
# ─────────────────────────────────────────────────────────────
def save_record(record: ProgramRecord, prose: dict | None = None) -> None:
    """레코드 + 그때 생성된 해설을 함께 보관한다.

    해설을 같이 저장하는 이유: 상태만 바뀌는 재렌더(시행중 → 종료)에 LLM 호출을
    다시 쓰지 않기 위해서다. 마감일이 지난 것뿐인데 문장을 새로 뽑으면
    같은 제도의 설명이 날마다 조금씩 달라지고, 무료 한도도 그만큼 태운다.
    (템플릿을 고쳤을 때 전체 페이지를 다시 찍는 데도 쓸 수 있다.)

    `_prose` 로 밑줄을 붙여 둔다. `ProgramRecord.from_dict` 는 모르는 키를
    버리므로 레코드 역직렬화에는 영향이 없다.
    """
    payload = record.to_dict()
    if prose is not None:
        payload["_prose"] = prose
    _write_json(RECORDS_DIR / f"{record.id}.json", payload)


def load_prose(program_id: str) -> dict | None:
    """저장해 둔 해설. 없으면 None (이 경우 재생성이 필요하다)."""
    data = _read_json(RECORDS_DIR / f"{program_id}.json", None)
    prose = (data or {}).get("_prose")
    return prose if isinstance(prose, dict) and prose else None


def load_record(program_id: str) -> ProgramRecord | None:
    data = _read_json(RECORDS_DIR / f"{program_id}.json", None)
    return ProgramRecord.from_dict(data) if data else None


def load_all_records() -> dict[str, ProgramRecord]:
    if not RECORDS_DIR.exists():
        return {}
    out: dict[str, ProgramRecord] = {}
    for path in sorted(RECORDS_DIR.glob("*.json")):
        data = _read_json(path, None)
        if data:
            record = ProgramRecord.from_dict(data)
            out[record.id] = record
    return out


# ─────────────────────────────────────────────────────────────
#  보조 대기열
# ─────────────────────────────────────────────────────────────
def save_queue(payload: dict) -> None:
    _write_json(QUEUE_FILE, payload)


def load_queue() -> dict:
    return _read_json(QUEUE_FILE, {"generated_at": "", "pending": []})


def save_review_needed(items: list[dict]) -> None:
    _write_json(REVIEW_FILE, {"count": len(items), "items": items})


def save_incomplete(items: list[dict]) -> None:
    _write_json(INCOMPLETE_FILE, {"count": len(items), "items": items})


def save_period_report(data: dict) -> None:
    """신청기한 표기 분포를 남긴다. 못 읽은 표기가 다음 파서 작업 목록이 된다."""
    _write_json(PERIOD_FILE, data)


# ─────────────────────────────────────────────────────────────
#  유사도 (3계층 중복 방지)
# ─────────────────────────────────────────────────────────────
_NAME_STRIP_RE = re.compile(r"[\s\W_]+")
# 제도명에 흔한 수식어. 빼고 비교해야 '2026년 청년 지원' 과 '청년 지원' 이 붙는다.
_NOISE_TOKENS = ("사업", "지원사업", "제도", "정책", "20", "년도", "차")


def normalize_name(name: str) -> str:
    """비교용 이름 정규화. 기존 collect/base.py 의 normalize_title 과 같은 발상."""
    text = _NAME_STRIP_RE.sub("", str(name or "")).lower()
    for token in _NOISE_TOKENS:
        text = text.replace(token, "")
    return text


def _bigrams(text: str) -> set[str]:
    return {text[i:i + 2] for i in range(len(text) - 1)} or {text}


def similarity(a: str, b: str) -> float:
    """정규화 이름의 문자 바이그램 자카드 유사도."""
    sa, sb = _bigrams(normalize_name(a)), _bigrams(normalize_name(b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def find_similar(
    record: ProgramRecord,
    known: dict[str, str],
    threshold: float = SIMILARITY_THRESHOLD,
) -> tuple[str, float] | None:
    """이미 발행된 제도 중 유사한 것을 찾는다.

    `known` 은 {비교용 이름: program_id}. 자기 자신은 건너뛴다.
    """
    best_id, best_score = None, 0.0
    for name, program_id in known.items():
        if program_id == record.id:
            continue
        score = similarity(record.name, name)
        if score > best_score:
            best_id, best_score = program_id, score
    if best_id and best_score >= threshold:
        return best_id, round(best_score, 3)
    return None
