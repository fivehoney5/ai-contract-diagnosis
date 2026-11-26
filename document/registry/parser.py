"""등기부 표 행(Row)을 권리 항목으로 바꾸고, 말소 여부와 선순위 금액을 정한다.

PDF 없이도 쓸 수 있게 Row 목록만 받는다 (테스트는 합성 Row로 한다).

말소 판정 (둘 중 하나라도 해당하면 cancelled):
    - strike : 행 글자의 절반 이상에 취소선
    - note   : 같은 구의 다른 행 등기목적에 "N번…말소"가 있음
선순위 금액 = 말소되지 않은 근저당권 채권최고액 + 저당권 채권액 + 전세권 전세금 + 주택임차권 임차보증금.
근저당권변경(부기 N-M) 행에 채권최고액이 있으면 그 금액으로 바꾼다.

개인정보: 권리자 칸 원문은 결과에 넣지 않는다. 이름은 개인이면 "***", 법인·기관이면 그대로 두고,
주민등록번호·주소는 모두 지운다.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date

from .pdf_reader import Row, norm

STRIKE_RATIO = 0.5  # 행 글자 중 이 비율 이상에 취소선이면 말소로 본다

# 등기목적 -> 권리 종류 (공백 지운 문자열에서 앞에서부터 찾는다)
KIND_RULES = (
    ("경매개시결정", "auction"),
    ("가압류", "provisional_seizure"),
    ("가처분", "provisional_disposition"),
    ("압류", "seizure"),
    ("가등기", "provisional_registration"),
    # 전세권을 담보로 잡은 근저당권. 전세금이 이미 선순위에 들어가므로 합계에서 뺀다
    ("전세권근저당권", "jeonse_mortgage"),
    ("전세권부근저당권", "jeonse_mortgage"),
    ("근저당권설정", "mortgage"),
    ("근저당권변경", "mortgage_change"),
    ("근저당권이전", "mortgage_transfer"),
    ("근질권", "pledge"),
    ("질권", "pledge"),
    ("저당권설정", "hypothec"),
    ("전세권설정", "jeonse_right"),
    ("전세권변경", "jeonse_right_change"),
    ("주택임차권", "lease_right"),
    ("임차권설정", "lease_right"),
    ("임차권", "lease_right"),
    ("신탁", "trust"),
    ("소유권보존", "ownership_preservation"),
    ("소유권이전", "ownership_transfer"),
)

KIND_LABEL = {
    "auction": "경매개시결정",
    "provisional_seizure": "가압류",
    "provisional_disposition": "가처분",
    "seizure": "압류",
    "provisional_registration": "가등기",
    "mortgage": "근저당권",
    "jeonse_mortgage": "전세권근저당권",
    "mortgage_change": "근저당권변경",
    "mortgage_transfer": "근저당권이전",
    "pledge": "질권",
    "hypothec": "저당권",
    "jeonse_right": "전세권",
    "jeonse_right_change": "전세권변경",
    "lease_right": "주택임차권",
    "trust": "신탁",
    "ownership_preservation": "소유권보존",
    "ownership_transfer": "소유권이전",
    "cancellation": "말소",
    "other": "기타",
}

RESTRICTION_KINDS = ("provisional_seizure", "seizure", "provisional_disposition", "auction")
SENIOR_KINDS = ("mortgage", "hypothec", "jeonse_right", "lease_right")
OWNER_KINDS = ("ownership_preservation", "ownership_transfer")

AMOUNT_LABELS = {
    "mortgage": ("채권최고액",),
    "mortgage_change": ("채권최고액",),
    "jeonse_mortgage": ("채권최고액",),
    "hypothec": ("채권액",),
    "jeonse_right": ("전세금",),
    "jeonse_right_change": ("전세금",),
    "lease_right": ("임차보증금", "보증금"),
}

# 대표 권리자를 고를 때 보는 순서 (채무자는 권리자가 아니라서 보지 않는다)
HOLDER_ROLES = (
    "근저당권자", "공동근저당권자", "저당권자", "전세권자", "임차권자", "가등기권자", "수탁자",
    "소유자", "공유자", "채권자", "권리자", "질권자",
)
ORG_WORDS = (
    "주식회사", "(주)", "㈜", "은행", "공사", "조합", "금고", "캐피탈", "보험", "신탁", "공단",
    "재단", "법인", "대한민국", "특별시", "광역시", "시청", "구청", "군청", "세무서", "국민건강",
    "농협", "수협", "신협", "새마을", "저축", "카드", "대부", "유한회사", "합자회사", "센터",
)

RRN_RE = re.compile(r"\d{6}\s*-\s*[\d*]{7}")
CANCEL_REF_RE = re.compile(r"(\d+(?:-\d+)?)번")
CANCEL_PART_RE = re.compile(r"\d+(?:-\d+)?번\D*?말소")  # "1번근저당권설정등기말소"
AMOUNT_RE = re.compile(r"금\s*([\d,]+)\s*원")
DATE_RE = re.compile(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일")


@dataclass
class Entry:
    section: str  # gap / eul
    rank: str
    purpose: str
    kind: str
    kind_label: str
    receipt_date: str | None
    cause: str
    amount: int | None
    holder: str | None  # 마스킹한 대표 권리자 이름
    status: str = "active"  # active / cancelled
    cancel_basis: list[str] = field(default_factory=list)  # strike, note
    cancelled_by: str | None = None  # 말소 등기의 순위번호
    page: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def mask_text(text: str | None) -> str:
    """주민등록번호를 지운다."""
    return RRN_RE.sub("******-*******", text or "")


def parse_date(text: str | None) -> date | None:
    m = DATE_RE.search(text or "")
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def parse_amount(text: str | None, labels: tuple[str, ...] = ()) -> int | None:
    """'채권최고액 금120,000,000원' -> 120000000. labels가 있으면 그 말 뒤 금액만 본다."""
    n = norm(text)
    if labels:
        for lb in labels:
            i = n.find(lb)
            if i >= 0:
                m = AMOUNT_RE.search(n, i)
                if m:
                    return int(m.group(1).replace(",", ""))
        return None
    m = AMOUNT_RE.search(n)
    return int(m.group(1).replace(",", "")) if m else None


def cancel_refs(purpose: str) -> list[str]:
    """등기목적 안의 '1번근저당권설정등기말소'에서 말소 대상 순위번호를 꺼낸다."""
    refs = []
    for part in CANCEL_PART_RE.findall(norm(purpose)):
        refs.extend(CANCEL_REF_RE.findall(part))
    return refs


def classify(purpose: str, cause: str = "") -> str:
    """등기목적으로 종류를 정한다. 말소 문구는 떼고 남은 것으로 본다
    (예: '소유권이전 3번신탁등기말소'는 소유권이전, '1번근저당권설정등기말소'만 있으면 말소)."""
    p = CANCEL_PART_RE.sub("", norm(purpose))
    if not p and CANCEL_PART_RE.search(norm(purpose)):
        return "cancellation"
    for word, kind in KIND_RULES:
        if word in p:
            if kind == "ownership_transfer" and "신탁" in norm(cause) and "신탁재산" not in norm(cause):
                return "trust"
            return kind
    return "other"


def mask_holder(holder_text: str | None) -> str | None:
    """권리자 칸에서 대표 이름 하나만 꺼내 개인이면 '***'로 가린다. 주소·번호는 버린다."""
    t = mask_text(holder_text)
    if not t.strip():
        return None
    tokens = t.split()
    name = None
    for role in HOLDER_ROLES:
        for i, tok in enumerate(tokens[:-1]):
            if norm(tok) == role:
                name = tokens[i + 1]
                # 법인명이 여러 낱말일 때 (예: 주식회사 가상은행)
                if name in ("주식회사", "유한회사") and i + 2 < len(tokens):
                    name = f"{name} {tokens[i + 2]}"
                break
        if name is not None:
            break
    if name is None:
        return None
    if any(w in name for w in ORG_WORDS):
        return name
    return "***"


def _rank_key(rank: str) -> str:
    """'1(전2)'처럼 옛 등기부에서 옮겨 온 표시는 떼고 순위번호만 남긴다."""
    return re.sub(r"\(전\d+(?:-\d+)?\)", "", norm(rank))


def _merge_continuations(rows: list[Row]) -> list[Row]:
    """순위번호가 빈 행(쪽이 넘어가며 이어진 행)을 앞 행에 붙인다."""
    out: list[Row] = []
    for r in rows:
        if out and not norm(r.cells.get("rank")) and out[-1].section == r.section and out[-1].subsection == r.subsection:
            prev = out[-1]
            n_prev = len(norm("".join(prev.cells.values())))
            n_cur = len(norm("".join(r.cells.values())))
            for k, v in r.cells.items():
                if v:
                    prev.cells[k] = (prev.cells.get(k, "") + "\n" + v).strip()
            # 취소선 비율은 글자 수로 가중 평균 (짧은 이어진 줄이 판정을 뒤집지 않게)
            if n_prev + n_cur:
                prev.struck_ratio = (prev.struck_ratio * n_prev + r.struck_ratio * n_cur) / (n_prev + n_cur)
            continue
        out.append(Row(r.section, r.subsection, dict(r.cells), r.struck_ratio, r.page, list(r.raw_cells)))
    return out


def build_entries(rows: list[Row]) -> list[Entry]:
    """갑구·을구 행을 Entry로 바꾸고 말소 여부를 정한다."""
    rows = _merge_continuations([r for r in rows if r.section in ("gap", "eul")])
    entries: list[Entry] = []
    for r in rows:
        purpose = r.cells.get("purpose", "")
        cause = r.cells.get("cause", "")
        holder = r.cells.get("holder", "")
        kind = classify(purpose, cause)
        labels = AMOUNT_LABELS.get(kind)
        rd = parse_date(r.cells.get("receipt"))
        e = Entry(
            section=r.section,
            rank=_rank_key(r.cells.get("rank", "")),
            purpose=norm(purpose),
            kind=kind,
            kind_label=KIND_LABEL[kind],
            receipt_date=rd.isoformat() if rd else None,
            cause=norm(mask_text(cause)),
            amount=parse_amount(holder, labels) if labels else None,
            holder=mask_holder(holder),
            page=r.page,
        )
        if r.struck_ratio >= STRIKE_RATIO:
            e.status = "cancelled"
            e.cancel_basis.append("strike")
        entries.append(e)

    # 말소 등기가 가리키는 순위번호를 말소 처리
    by_rank = {(e.section, e.rank): e for e in entries}
    for e in entries:
        for ref in cancel_refs(e.purpose):
            target = by_rank.get((e.section, ref))
            if target is None or target is e:
                continue
            target.status = "cancelled"
            if "note" not in target.cancel_basis:
                target.cancel_basis.append("note")
            target.cancelled_by = e.rank
    # 근저당권·전세권 변경: 말소되지 않은 가장 늦은 변경 금액을 원 등기에 반영
    for e in entries:
        if e.kind in ("mortgage_change", "jeonse_right_change") and e.status == "active" and e.amount is not None:
            parent = by_rank.get((e.section, e.rank.split("-")[0]))
            if parent is not None and parent.kind in ("mortgage", "jeonse_right"):
                parent.amount = e.amount
    # 부기 등기는 원 등기가 말소되면 같이 말소된 것으로 본다
    for e in entries:
        if "-" in e.rank:
            parent = by_rank.get((e.section, e.rank.split("-")[0]))
            if parent is not None and parent.status == "cancelled" and e.status == "active":
                e.status = "cancelled"
                e.cancel_basis.append("parent")
    return entries


def parse_title(rows: list[Row], header_text: str = "") -> dict:
    """표제부에서 주소, 전유 면적, 구조, 대지권 여부를 꺼낸다 (말소되지 않은 가장 마지막 행 기준)."""

    def last_active(sub):
        cand = [r for r in rows if r.section == "title" and r.subsection == sub and r.struck_ratio < STRIKE_RATIO]
        cand = _merge_continuations(cand)
        return cand[-1] if cand else None

    building = last_active("building")
    unit = last_active("unit")
    land_right = last_active("land_right")
    has_title = any(r.section == "title" for r in rows)

    address = road_address = None
    if building is not None:
        loc = building.cells.get("location", "")
        lines = [ln.strip() for ln in loc.splitlines() if ln.strip()]
        road = [ln for ln in lines if "도로명주소" in norm(ln)]
        jibun_lines = [ln for ln in lines if "도로명주소" not in norm(ln)]
        if road:
            idx = lines.index(road[0])
            road_address = " ".join(lines[idx:]).replace("[도로명주소]", "").strip() or None
            jibun_lines = lines[:idx]
        address = " ".join(jibun_lines) or None
    if header_text:
        # "[집합건물] 서울특별시 ... 제302호" -> 호수까지 포함된 표시용 주소
        h = re.sub(r"^\s*\[(집합건물|건물)\]\s*", "", header_text).strip()
        address_display = h or address
    else:
        address_display = address

    structure = area = unit_no = None
    if unit is not None:
        detail = unit.cells.get("detail", "")
        unit_no = " ".join(unit.cells.get("unit_no", "").split()) or None
        m = re.search(r"([\d.]+)\s*㎡", detail.replace("\n", " "))
        if m:
            area = float(m.group(1))
        s = re.split(r"[\d.]+\s*㎡", " ".join(detail.split()))[0].strip()
        structure = s or None
    elif building is not None:
        # 일반건물은 전유부분이 없다. 구조만 건물내역 첫 부분에서 꺼내고 면적은 비워 둔다
        m = re.match(r"\S+?조(?=\s|$)", " ".join(building.cells.get("detail", "").split()))
        structure = m.group(0) if m else None

    all_title_text = " ".join(norm(" ".join(r.raw_cells)) for r in rows if r.section == "title")
    separate_land = "별도등기있음" in all_title_text
    return {
        "address": address,
        "road_address": road_address,
        "address_display": address_display,
        "unit_no": unit_no,
        "exclusive_area_m2": area,
        "structure": structure,
        "has_land_right": land_right is not None,
        "separate_land_registration": separate_land,
        "has_title_section": has_title,
        "has_unit_section": unit is not None,
    }


def summarize(entries: list[Entry]) -> dict:
    """선순위 합계와 종류별 건수."""
    active = [e for e in entries if e.status == "active"]
    by_kind = {k: sum(e.amount or 0 for e in active if e.kind == k) for k in SENIOR_KINDS}
    missing = [e.rank for e in active if e.kind in SENIOR_KINDS and e.amount is None]
    owners = [e for e in entries if e.section == "gap" and e.kind in OWNER_KINDS + ("trust",) and e.status == "active"]
    return {
        "senior_amount_total": sum(by_kind.values()),
        "senior_breakdown": {
            "mortgage_max_claim": by_kind["mortgage"],
            "hypothec_claim": by_kind["hypothec"],
            "jeonse_right_deposit": by_kind["jeonse_right"],
            "lease_right_deposit": by_kind["lease_right"],
        },
        "senior_amount_missing_ranks": missing,
        "earliest_security_date": min(
            (e.receipt_date for e in active if e.kind in ("mortgage", "hypothec", "jeonse_right") and e.receipt_date),
            default=None,
        ),
        "counts": {
            "restriction": sum(1 for e in active if e.kind in RESTRICTION_KINDS),
            "provisional_registration": sum(1 for e in active if e.kind == "provisional_registration"),
            "trust": sum(1 for e in active if e.kind == "trust"),
            "lease_right": sum(1 for e in active if e.kind == "lease_right"),
            "jeonse_right": sum(1 for e in active if e.kind == "jeonse_right"),
            "mortgage": sum(1 for e in active if e.kind == "mortgage"),
            "cancelled": sum(1 for e in entries if e.status == "cancelled" and e.kind != "cancellation"),
        },
        "ownership_history": [
            {"rank": e.rank, "kind_label": e.kind_label, "receipt_date": e.receipt_date, "cause": e.cause, "holder": e.holder}
            for e in owners
        ],
    }
