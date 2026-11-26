"""등기사항전부증명서 PDF에서 표의 행을 읽고, 행마다 취소선(말소 표시) 비율을 잰다.

인터넷등기소에서 발급한 PDF는 글자 층(text layer)이 있어서 pdfplumber로 바로 읽는다.
말소된 등기는 글자 위에 가로선(보통 빨간 선)이 그어져 있으므로,
글자 높이의 가운데 부분을 지나가는 가로선을 취소선으로 본다.
표 테두리는 글자의 위나 아래에 있어서 가운데를 지나지 않으므로 취소선으로 잡히지 않는다.

스캔 이미지 PDF(글자 층 없음)는 NoTextLayerError를 낸다. OCR 연동은 아직 하지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 표 제목 (공백을 지운 뒤 비교)
SECTION_TITLES = {
    "【표제부】": "title",
    "【갑구】": "gap",
    "【을구】": "eul",
}
SUBSECTION_TITLES = {
    "(1동의건물의표시)": "building",
    "(대지권의목적인토지의표시)": "land",
    "(전유부분의건물의표시)": "unit",
    "(대지권의표시)": "land_right",
}
STOP_MARKERS = ("주요등기사항요약",)

# 머리글 칸 이름 -> 키. 앞에 있는 것부터 맞춰 본다.
HEADER_KEYS = (
    ("순위번호", "rank"),
    ("표시번호", "rank"),
    ("등기목적", "purpose"),
    ("등기원인", "cause"),
    ("권리자", "holder"),
    ("대지권종류", "land_kind"),
    ("대지권비율", "land_ratio"),
    ("소재지번", "location"),
    ("건물내역", "detail"),
    ("건물번호", "unit_no"),
    ("지목", "land_category"),
    ("면적", "land_area"),
    ("접수", "receipt"),
)

# 취소선 판정 (글자 높이 대비 위치, 선 두께)
STRIKE_BAND = (0.25, 0.80)  # 글자 위쪽에서 25%-80% 사이를 지나면 취소선
MAX_LINE_THICKNESS = 2.0


class NoTextLayerError(Exception):
    """글자 층이 없는 PDF (스캔 이미지). OCR이 필요하다."""


class RegistryReadError(Exception):
    """PDF를 열 수 없거나 등기부 표를 찾지 못함."""


@dataclass
class Row:
    section: str  # title / gap / eul
    subsection: str | None  # 표제부일 때 building / land / unit / land_right
    cells: dict[str, str]
    struck_ratio: float  # 행 글자 중 취소선이 그어진 글자 비율 (0-1)
    page: int
    raw_cells: list[str] = field(default_factory=list)


@dataclass
class RegistryDocument:
    rows: list[Row]
    header_text: str  # 각 쪽 맨 위 "[집합건물] 주소" 줄
    issued_text: str | None  # "열람일시 : ..." 또는 "발행일 : ..." 문구
    page_count: int


def norm(text: str | None) -> str:
    """공백·줄바꿈을 모두 지운다 (등기부는 글자 사이에 공백이 들어간 경우가 많음)."""
    return re.sub(r"\s+", "", text or "")


def _strike_segments(page) -> list[tuple[float, float, float]]:
    """가로선 후보 (y, x0, x1). line 객체와 얇은 사각형 모두 본다."""
    segs = []
    for ln in page.lines:
        if abs(ln["top"] - ln["bottom"]) <= MAX_LINE_THICKNESS and ln["x1"] - ln["x0"] > 3:
            segs.append(((ln["top"] + ln["bottom"]) / 2, ln["x0"], ln["x1"]))
    for r in page.rects:
        h = r["bottom"] - r["top"]
        w = r["x1"] - r["x0"]
        if h <= MAX_LINE_THICKNESS and w > 3 and w > h * 5:
            segs.append(((r["top"] + r["bottom"]) / 2, r["x0"], r["x1"]))
    return segs


def _is_struck(ch: dict, segs) -> bool:
    h = ch["bottom"] - ch["top"]
    if h <= 0:
        return False
    lo = ch["top"] + h * STRIKE_BAND[0]
    hi = ch["top"] + h * STRIKE_BAND[1]
    cx = (ch["x0"] + ch["x1"]) / 2
    return any(lo <= y <= hi and x0 <= cx <= x1 for y, x0, x1 in segs)


def _header_map(cells: list[str]) -> dict[int, str] | None:
    keys = {}
    for i, c in enumerate(cells):
        n = norm(c)
        for word, key in HEADER_KEYS:
            if word in n:
                keys[i] = key
                break
    if "rank" in keys.values() and len(keys) >= 3:
        return keys
    return None


def _match_title(text: str):
    n = norm(text)
    sec = next((v for k, v in SECTION_TITLES.items() if k in n), None)
    sub = next((v for k, v in SUBSECTION_TITLES.items() if k in n), None)
    return sec, sub


def read_registry_pdf(source) -> RegistryDocument:
    """PDF 경로나 파일 객체를 읽어 표 행 목록을 돌려준다.

    예외: NoTextLayerError (스캔 이미지), RegistryReadError (열기 실패, 표 없음).
    """
    try:
        import pdfplumber
    except ImportError as e:  # pragma: no cover - 설치 안내
        raise RegistryReadError("pdfplumber가 설치되어 있지 않습니다 (pip install -r document/registry/requirements.txt)") from e

    try:
        pdf = pdfplumber.open(source)
    except Exception as e:  # 손상·암호화 등
        raise RegistryReadError(f"PDF를 열 수 없습니다: {type(e).__name__}") from e

    rows: list[Row] = []
    header_text = ""
    issued_text = None
    with pdf:
        page_count = len(pdf.pages)
        total_chars = sum(len(p.chars) for p in pdf.pages)
        if total_chars == 0:
            raise NoTextLayerError("글자 층이 없는 PDF입니다 (스캔 이미지로 보임)")

        section = subsection = None
        col_map: dict[int, str] | None = None
        stopped = False
        for pno, page in enumerate(pdf.pages, start=1):
            if stopped:
                break
            text_lines = page.extract_text_lines() if hasattr(page, "extract_text_lines") else []
            for tl in text_lines:
                n = norm(tl["text"])
                if not header_text and ("[집합건물]" in n or "[건물]" in n):
                    header_text = tl["text"].strip()
                if issued_text is None and ("열람일시" in n or "발행일" in n):
                    issued_text = tl["text"].strip()

            segs = _strike_segments(page)
            struck_chars = [ch for ch in page.chars if ch["text"].strip() and _is_struck(ch, segs)]
            strike_ys = {round(y, 1) for y, _, _ in segs
                         if any(abs(((c["top"] + c["bottom"]) / 2) - y) < (c["bottom"] - c["top"]) / 2 for c in struck_chars)}

            def keep(obj, _ys=strike_ys):
                if obj.get("object_type") in ("line", "rect"):
                    h = obj["bottom"] - obj["top"]
                    if h <= MAX_LINE_THICKNESS and round((obj["top"] + obj["bottom"]) / 2, 1) in _ys:
                        return False
                return True

            # 취소선은 표 테두리로 잘못 쓰이면 칸이 쪼개지므로 표 찾기 전에 뺀다
            clean = page.filter(keep)
            # 표 밖 제목 줄 (표보다 위에 있는 제목)
            titles = []
            for tl in text_lines:
                s, sub = _match_title(tl["text"])
                if s or sub:
                    titles.append((tl["top"], s, sub))
                if any(m in norm(tl["text"]) for m in STOP_MARKERS):
                    titles.append((tl["top"], "stop", None))

            tables = clean.find_tables()
            events = [(t[0], "title", t) for t in titles]
            for tb in tables:
                for r in tb.rows:
                    top = min((c[1] for c in r.cells if c), default=0)
                    events.append((top, "row", r))
            events.sort(key=lambda e: (e[0], 0 if e[1] == "title" else 1))

            seen_rows = set()
            for _, kind, obj in events:
                if kind == "title":
                    _, s, sub = obj
                    if s == "stop":
                        stopped = True
                        break
                    if s:
                        section, subsection, col_map = s, None, None
                    if sub:
                        subsection, col_map = sub, None
                    continue
                r = obj
                key = id(r)
                if key in seen_rows:
                    continue
                seen_rows.add(key)
                bboxes = [c for c in r.cells]
                cells_text = []
                chars_in_row = []
                for bb in bboxes:
                    if bb is None:
                        cells_text.append("")
                        continue
                    crop = clean.crop(bb, strict=False)
                    cells_text.append((crop.extract_text() or "").strip())
                    chars_in_row.extend(c for c in crop.chars if c["text"].strip())
                joined = " ".join(cells_text)
                if any(m in norm(joined) for m in STOP_MARKERS):
                    stopped = True
                    break
                s, sub = _match_title(joined)
                if s or sub:
                    if s:
                        section, subsection, col_map = s, None, None
                    if sub:
                        subsection, col_map = sub, None
                    continue
                hm = _header_map(cells_text)
                if hm:
                    col_map = hm
                    continue
                if section is None or not norm(joined):
                    continue
                if col_map is None:
                    continue
                cells = {}
                for i, key_name in col_map.items():
                    if i < len(cells_text):
                        cells[key_name] = cells_text[i]
                n_chars = len(chars_in_row)
                struck = 0
                if n_chars:
                    sset = {(round(c["x0"], 1), round(c["top"], 1)) for c in struck_chars}
                    struck = sum(1 for c in chars_in_row if (round(c["x0"], 1), round(c["top"], 1)) in sset)
                rows.append(Row(section, subsection, cells, struck / n_chars if n_chars else 0.0, pno, cells_text))

    if not any(r.section in ("gap", "eul") for r in rows) and not any(r.section == "title" for r in rows):
        raise RegistryReadError("등기부 표(표제부·갑구·을구)를 찾지 못했습니다")
    return RegistryDocument(rows, header_text, issued_text, page_count)
