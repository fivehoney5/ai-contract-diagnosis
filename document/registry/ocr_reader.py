"""등기부 스캔본(글자 층 없는 PDF)과 사진을 OCR로 읽어 pdf_reader와 같은 RegistryDocument로 바꾼다.

OCR 엔진은 document/contract/reader.py의 RapidOCR(PaddleOCR 한국어 PP-OCRv5) 설정을 그대로 쓴다.
엔진은 그림(PIL.Image)을 받아 [(글자, 네 꼭짓점, 점수), ...]를 돌려주는 호출 가능한 객체라 테스트에서 바꿔 끼울 수 있다.

표 칸 나누기: 머리글 줄("순위번호 등기목적 접수 등기원인 권리자 및 기타사항")의 글자 위치로 칸 경계를 잡고,
글자 상자를 가로 위치로 칸에 넣는다. 두 칸에 걸친 상자는 글자 폭 비율로 자른다.
순위번호 칸에 글자가 있는 줄에서 새 행을 시작하고, 없는 줄은 앞 행에 이어 붙인다.

취소선: OCR은 선을 읽지 못하므로 그림에서 글자 상자 가운데(높이 25-80%)를 거의 끝까지 지나는 가로선을 찾는다.
못 찾더라도 "N번…말소" 등기가 있으면 parser가 말소로 본다.

신뢰도: 금액이 든 상자의 점수가 AMOUNT_MIN_SCORE보다 낮으면 금액을 지워 "금액 미확인"이 되게 한다
(잘못 읽은 금액으로 선순위 합계를 내지 않기 위함). 쪽 평균 점수는 analysis_result가 판단보류 기준으로 쓴다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .pdf_reader import (
    STOP_MARKERS,
    STRIKE_BAND,
    RegistryDocument,
    RegistryReadError,
    Row,
    _header_map,
    _match_title,
    norm,
)

PDF_RENDER_DPI = 216  # 스캔 PDF를 그림으로 바꿀 때 해상도 (계약서 모듈과 같음)
AMOUNT_MIN_SCORE = 0.90  # 금액 상자 OCR 점수가 이보다 낮으면 금액을 믿지 않는다
STRIKE_MIN_COVER = 0.70  # 가로선이 상자 폭의 이 비율 이상을 지나면 취소선
STRIKE_GAP = 2  # 가로선이 이 픽셀 이하로 끊겨도 이어진 것으로 본다 (노이즈). 크게 하면 글자 사이가 이어져 오판한다
RULE_GRAY_MAX = 200  # 표 테두리 찾을 때 이보다 어두우면 선으로 본다 (흐린 사진에서 가는 선은 회색이 됨)
RULE_MIN_COVER = 0.80  # 첫 칸-마지막 칸 머리글 구간에서 이 비율 이상 이어지면 표 가로 테두리
RANK_RE = re.compile(r"^\d{1,3}(?:-\d{1,3})?(?:\(전\d+(?:-\d+)?\))?$")
AMOUNT_TEXT_RE = re.compile(r"금\s*[\d,.]+\s*원")

# 취소선이 그어진 글자에서 자주 나오는 잘못 읽기 [추측: 가상 등기부 렌더링에서 본 것만 넣음]
OCR_FIXES = (
    (re.compile(r"(저당|전세|소유|임차|질)귀"), r"\1권"),
    (re.compile(r"그저당"), "근저당"),
    (re.compile(r"말쇠"), "말소"),
    (re.compile(r"(권|등기)석정"), r"\1설정"),
    (re.compile(r"(?<=\d)\s*(?:m'|m2|m²|rf|㎡)"), "㎡"),  # 면적 단위
    (re.compile(r"(\d층)(제\d)"), r"\1 \2"),  # "제10층제1003호" -> "제10층 제1003호"
    # 띄어쓰기를 잃으면 parser가 권리자 이름을 못 찾으므로 역할 낱말 뒤와 등록번호 앞을 띄운다
    (re.compile(r"(근저당권자|저당권자|전세권자|임차권자|가등기권자|수탁자|소유자|공유자|채권자|채무자|권리자|질권자)(?=[^\s\d])"), r"\1 "),
    (re.compile(r"(?<=[^\d\s])(\d{6}\s*-\s*[\d*]{7})"), r" \1"),
)
# 쪽마다 되풀이되는 머리·꼬리 줄 (표 행으로 읽으면 안 됨)
SKIP_LINE_WORDS = ("[집합건물]", "[건물]", "열람일시", "발행일", "관할등기소")


@dataclass
class Box:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    score: float

    @property
    def mid(self) -> float:
        return (self.y0 + self.y1) / 2


def fix_text(text: str) -> str:
    for pat, rep in OCR_FIXES:
        text = pat.sub(rep, text)
    return text


OCR_SECTION_RE = re.compile(r"^[\[【(1lI|]?(표제부|갑구|을구)[\]】)1lI|]?")


def match_title(text: str):
    """OCR은 【】를 []나 1로 읽기도 하므로 줄 맨 앞의 구 이름으로도 맞춘다."""
    s, sub = _match_title(text)
    if not s:
        m = OCR_SECTION_RE.match(norm(text))
        if m:
            s = {"표제부": "title", "갑구": "gap", "을구": "eul"}[m.group(1)]
    return s, sub


def _to_boxes(items) -> list[Box]:
    out = []
    for text, pts, score in items:
        text = fix_text((text or "").strip())
        if not text:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        out.append(Box(text, min(xs), min(ys), max(xs), max(ys), float(score)))
    return out


def _group_lines(boxes: list[Box]) -> list[list[Box]]:
    if not boxes:
        return []
    heights = sorted(b.y1 - b.y0 for b in boxes)
    tol = max(heights[len(heights) // 2] * 0.5, 1.0)
    lines: list[list[Box]] = []
    for b in sorted(boxes, key=lambda b: b.mid):
        if lines:
            last = lines[-1]
            if abs(b.mid - sum(x.mid for x in last) / len(last)) <= tol:
                last.append(b)
                continue
        lines.append([b])
    for ln in lines:
        ln.sort(key=lambda b: b.x0)
    return lines


def _cls(ch: str) -> str:
    return "d" if ch.isdigit() or ch in ",." else ("s" if ch.isspace() else "h")


def _snap(text: str, k: int, start: int) -> int:
    """자르는 자리를 3글자 안의 공백으로, 없으면 글자 종류(한글/숫자)가 바뀌는 곳으로 옮긴다 ("말소|2023년")."""
    for d in (0, 1, -1, 2, -2, 3, -3):
        j = k + d
        if start < j < len(text) and text[j].isspace():
            return j
    for d in (0, 1, -1, 2, -2):
        j = k + d
        if start < j < len(text) and _cls(text[j - 1]) != _cls(text[j]):
            return j
    return k


def _split_box(b: Box, cuts: list[float]) -> list[Box]:
    """칸 경계(cuts)를 넘는 상자를 글자 폭 비율로 자른다."""
    if len(b.text) < 2:
        return [b]
    w = (b.x1 - b.x0) / len(b.text)
    # 경계를 1.5글자 미만으로 넘은 것은 칸 안 글자가 삐져나온 것으로 보고 자르지 않는다
    inside = [c for c in cuts if b.x0 + 1.5 * w < c < b.x1 - 1.5 * w]
    if not inside:
        return [b]
    parts, start, x = [], 0, b.x0
    for c in inside:
        k = max(start + 1, min(len(b.text) - 1, round((c - b.x0) / w)))
        k = _snap(b.text, k, start)
        if k <= start:
            continue
        parts.append(Box(b.text[start:k], b.x0 + start * w, b.y0, b.x0 + k * w, b.y1, b.score))
        start = k
    parts.append(Box(b.text[start:], b.x0 + start * w, b.y0, b.x1, b.y1, b.score))
    return [p for p in parts if p.text.strip()]


# ---------- 취소선 ----------

def _ink_mask(image, gray_max: int = 150):
    """검은 글자·빨간 선을 True로. numpy 배열 (높이, 너비). 표 테두리는 흐리게 찍혀 gray_max를 높여 쓴다."""
    import numpy as np

    a = np.asarray(image.convert("RGB")).astype(np.int32)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    gray = (r * 299 + g * 587 + b * 114) // 1000
    red = (r > 140) & (g < 120) & (b < 120)
    return (gray < gray_max) | red


def _longest_run(row, gap: int) -> int:
    best = cur = miss = 0
    for v in row:
        if v:
            cur += 1 + miss
            miss = 0
        elif cur:
            miss += 1
            if miss > gap:
                best = max(best, cur)
                cur = miss = 0
    return max(best, cur)


def is_struck(mask, b: Box) -> bool:
    if mask is None:
        return False
    h, w = mask.shape
    x0, x1 = max(int(b.x0), 0), min(int(b.x1), w)
    y0 = int(b.y0 + (b.y1 - b.y0) * STRIKE_BAND[0])
    y1 = int(b.y0 + (b.y1 - b.y0) * STRIKE_BAND[1]) + 1
    if x1 - x0 < 10 or y1 <= y0:
        return False
    need = (x1 - x0) * STRIKE_MIN_COVER
    for y in range(max(y0, 0), min(y1, h)):
        if _longest_run(mask[y, x0:x1], STRIKE_GAP) >= need:
            return True
    return False


# ---------- 쪽 읽기 ----------

def ocr_page(image, engine):
    """(그림, 글자 상자 목록). 엔진이 raw를 주면 기울기를 직접 바로잡아 취소선 검사에 같은 그림을 쓴다."""
    raw = getattr(engine, "raw", None)
    image = to_rgb(image)
    if raw is None:
        return image, _to_boxes(engine(image))
    import numpy as np
    from PIL import Image

    from ..contract.reader import DESKEW_MIN_DEGREES, estimate_skew

    image = to_rgb(image)
    items = raw(np.asarray(image))
    angle = estimate_skew(items)
    if abs(angle) >= DESKEW_MIN_DEGREES:
        image = image.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor="white")
        items = raw(np.asarray(image))
    return image, _to_boxes(items)


def _guard_amounts(text: str, score: float) -> str:
    if score < AMOUNT_MIN_SCORE:
        return AMOUNT_TEXT_RE.sub("금(판독불가)원", text)
    return text


def read_registry_images(images, engine=None) -> tuple[RegistryDocument, float | None]:
    """쪽 그림 목록을 읽어 (RegistryDocument, OCR 평균 점수)를 돌려준다. 예외: RegistryReadError."""
    if engine is None:
        from ..contract.reader import get_default_engine

        engine = get_default_engine()

    rows: list[Row] = []
    header_text, issued_text = "", None
    scores: list[float] = []
    section = subsection = None
    cols: list[tuple[float, str]] | None = None  # (칸 시작 x, 키)
    stopped = False
    for pno, image in enumerate(images, start=1):
        if stopped:
            break
        image, boxes = ocr_page(image, engine)
        scores.extend(b.score for b in boxes)
        try:
            mask = _ink_mask(image)
            light = _ink_mask(image, RULE_GRAY_MAX)
        except Exception:  # numpy 없음 등: 취소선·테두리 검사만 건너뛴다
            mask = light = None
        segment: list[dict] = []  # 머리글 다음부터 쌓은 줄 (칸별 글자, 순위번호 상자)
        head_y = [-1.0]  # 이 쪽 머리글 줄 높이 (머리글 없이 이어진 쪽이면 -1)

        def flush():
            rules = _rule_ys(light, cols) if light is not None and cols else []
            last = next((r.cells.get("rank") for r in reversed(rows) if r.section == section and r.cells.get("rank")), None)
            rows.extend(_segment_rows(segment, section, subsection, cols, pno, rules, head_y[0], last))
            segment.clear()

        for line in _group_lines(boxes):
            joined = " ".join(b.text for b in line)
            n = norm(joined)
            if any(w in n for w in SKIP_LINE_WORDS):
                if not header_text and ("[집합건물]" in n or "[건물]" in n):
                    header_text = joined
                if issued_text is None and ("열람일시" in n or "발행일" in n):
                    issued_text = joined
                continue
            if any(m in n for m in STOP_MARKERS):
                stopped = True
                break
            s, sub = match_title(joined)
            if s or sub:
                flush()
                if s:
                    section, subsection, cols = s, None, None
                if sub:
                    subsection, cols = sub, None
                continue
            hm = _header_map([b.text for b in line])
            if hm:
                flush()
                cols = sorted((line[i].x0, key) for i, key in hm.items())
                head_y[0] = sum(b.mid for b in line) / len(line)
                continue
            if section is None or cols is None:
                continue
            segment.append(_line_cells(line, cols, mask))
        flush()

    # 같은 구에 같은 순위번호가 두 번 나오면 구 제목(갑구·을구)을 놓친 것이다. 권리가 섞이면 위험하므로 읽지 않는다
    seen = set()
    for r in rows:
        rank = r.cells.get("rank")
        if r.section in ("gap", "eul") and rank:
            if (r.section, rank) in seen:
                raise RegistryReadError("스캔본·사진에서 갑구·을구 구분을 확실히 읽지 못했습니다. 더 선명하게 찍거나 PDF 원본을 올려 주세요.")
            seen.add((r.section, rank))
    # 순위번호는 구마다 1부터 빠짐없이 이어진다. 빠진 번호가 있으면 행을 놓친 것이므로 읽지 않는다
    for sec in ("gap", "eul"):
        mains = {_main_rank(r.cells.get("rank")) for r in rows if r.section == sec} - {None}
        if mains and mains != set(range(1, max(mains) + 1)):
            raise RegistryReadError("스캔본·사진에서 순위번호 일부를 읽지 못했습니다 (빠진 행이 있을 수 있음). "
                                    "더 선명하게 찍거나 PDF 원본을 올려 주세요.")
    if not any(r.section in ("gap", "eul", "title") for r in rows):
        raise RegistryReadError("스캔본·사진에서 등기부 표(표제부·갑구·을구)를 찾지 못했습니다. 더 밝고 반듯하게 찍어 주세요.")
    score = round(sum(scores) / len(scores), 4) if scores else None
    return RegistryDocument(rows, header_text, issued_text, len(images)), score


def _line_cells(line: list[Box], cols, mask) -> dict:
    """한 줄의 상자를 칸에 나눠 넣는다. 취소선이 그어진 글자 수도 센다."""
    cuts = [x - 8 for x, _ in cols[1:]]  # 다음 칸 머리글 시작보다 조금 앞
    cells: dict[str, str] = {}
    struck = chars = 0
    rank_box = None
    for p in (p for b in line for p in _split_box(b, cuts)):
        key = cols[sum(1 for c in cuts if (p.x0 + p.x1) / 2 >= c)][1]
        cells[key] = (cells.get(key, "") + " " + _guard_amounts(p.text, p.score)).strip()
        nc = len(norm(p.text))
        chars += nc
        if is_struck(mask, p):
            struck += nc
        if key == "rank" and rank_box is None:
            rank_box = p
    top = min(b.y0 for b in line)
    height = sorted(b.y1 - b.y0 for b in line)[len(line) // 2]
    return {"cells": cells, "struck": struck, "chars": chars, "rank_box": rank_box,
            "mid": sum(b.mid for b in line) / len(line), "top": top, "height": height}


def _rank_of(text: str, prev: str | None) -> str | None:
    """순위번호 칸 글자. 취소선 때문에 "×"처럼 읽힌 짧은 글자는 앞 번호 + 1로 본다 [추측]."""
    t = norm(text)
    if not t:
        return None
    if RANK_RE.match(t):
        return t
    if len(t) <= 3 and not re.search(r"[가-힣]", t):
        base = re.match(r"\d+", prev or "")
        return str(int(base.group()) + 1) if base else "1"
    return None


def _rule_ys(mask, cols) -> list[float]:
    """표의 가로 테두리 높이 목록. 첫 칸부터 마지막 칸 머리글까지 거의 끊김 없이 이어진 가로줄만 본다
    (취소선은 칸마다 따로 그어져 칸 경계에서 끊기므로 잡히지 않는다)."""
    import numpy as np

    h, w = mask.shape
    x0 = max(int(cols[0][0]) - 5, 0)
    x1 = min(int(cols[-1][0]) + 60, w)
    if x1 - x0 < 50:
        return []
    frac = mask[:, x0:x1].mean(axis=1)
    # 기울기 보정 뒤 조금 남은 기울기로 선이 2-3줄에 걸칠 수 있어 위아래 2픽셀을 같이 본다
    near = np.max(np.stack([np.roll(frac, d) for d in (-2, -1, 0, 1, 2)]), axis=0)
    hit = np.where(near >= RULE_MIN_COVER)[0]
    ys: list[float] = []
    for y in hit:
        if ys and y - ys[-1] <= 6:
            continue
        ys.append(float(y))
    return ys


def _main_rank(rank: str | None) -> int | None:
    m = re.match(r"\d+", rank or "")
    return int(m.group()) if m else None


def _band_groups(segment, rules, head_y, last_rank=None):
    """테두리 사이(칸 한 줄)마다 줄을 묶는다. 머리글과 같은 칸 띠에 있는 줄은 앞 행에서 이어진 것."""
    band = lambda y: sum(1 for r in rules if r <= y)  # noqa: E731
    head_band = band(head_y)
    bands: dict[int, list[dict]] = {}
    for ln in segment:
        bands.setdefault(band(ln["mid"]), []).append(ln)
    groups: list[tuple[str, list[dict]]] = []
    prev = last_rank
    for b in sorted(bands):
        lines = bands[b]
        rank = None
        for ln in lines:
            if ln["rank_box"] is not None:
                rank = _rank_of(ln["rank_box"].text, prev)
                if rank:
                    break
        new_row = b != head_band and any(ln["cells"].get("purpose") for ln in lines)
        chars = sum(ln["chars"] for ln in lines)
        struck = chars and sum(ln["struck"] for ln in lines) / chars >= 0.5
        expected = str((_main_rank(prev) or 0) + 1)
        if new_row and struck and rank != expected and not (rank or "").startswith(f"{_main_rank(prev)}-"):
            # 취소선 때문에 순위번호를 못 읽거나 잘못 읽은 행 [추측: 앞 번호 + 1. 틀리면 번호가 겹치거나 빠져 판단보류가 된다]
            rank = expected
        elif rank is None and new_row:
            rank = expected
        if rank is None:
            if groups:
                groups[-1][1].extend(lines)
            else:
                groups.append(("", list(lines)))
            continue
        groups.append((rank, list(lines)))
        prev = rank
    return groups


def _segment_rows(segment: list[dict], section, subsection, cols, page: int, rules=(), head_y=-1.0,
                  last_rank=None) -> list[Row]:
    """머리글 아래 줄들을 표 행으로 묶는다. 표 테두리가 보이면 테두리 사이를 한 행으로 본다.
    테두리가 없으면 순위번호 상자의 윗변보다 조금 위에서 행이 시작한다고 본다
    (순위번호 줄보다 살짝 위에 잡힌 날짜·금액 줄도 같은 행). 첫 순위번호 앞 줄은 앞 쪽에서 이어진 행."""
    if not segment or cols is None:
        return []
    if rules:
        return _rows_from_groups(_band_groups(segment, rules, head_y, last_rank), section, subsection, cols, page)
    starts = []  # (시작 y, 순위번호)
    prev = None
    for ln in segment:
        rb = ln["rank_box"]
        if rb is None:
            continue
        rank = _rank_of(rb.text, prev)
        if rank is None:
            continue
        starts.append((rb.y0 - ln["height"] * 0.6, rank))
        prev = rank
    groups: list[tuple[str, list[dict]]] = []
    if not starts or segment[0]["mid"] < starts[0][0]:
        groups.append(("", []))
    for y, rank in starts:
        groups.append((rank, []))
    lead = 1 if groups[0][0] == "" else 0  # 맨 앞 묶음이 이어진 행인지
    for ln in segment:
        idx = sum(1 for y, _ in starts if ln["mid"] >= y)  # 이 줄 위에서 시작한 행 수
        groups[max(idx - 1 + lead, 0)][1].append(ln)
    return _rows_from_groups(groups, section, subsection, cols, page)


def _rows_from_groups(groups, section, subsection, cols, page) -> list[Row]:
    out = []
    keys = [k for _, k in cols]
    for rank, lines in groups:
        if not lines:
            continue
        cells: dict[str, str] = {}
        for ln in lines:
            for k, v in ln["cells"].items():
                if k == "rank":
                    continue
                cells[k] = (cells.get(k, "") + "\n" + v).strip()
        cells["rank"] = rank
        chars = sum(ln["chars"] for ln in lines)
        struck = sum(ln["struck"] for ln in lines)
        out.append(Row(section, subsection, cells, struck / chars if chars else 0.0, page,
                       [cells.get(k, "") for k in keys]))
    return out


def render_pdf_pages(source) -> list:
    """글자 층 없는 PDF를 쪽 그림 목록으로."""
    import pdfplumber

    with pdfplumber.open(source) as pdf:
        return [to_rgb(p.to_image(resolution=PDF_RENDER_DPI).original) for p in pdf.pages]


def to_rgb(image):
    """투명 배경(RGBA, PNG 등)은 흰 바탕에 얹는다. 그냥 RGB로 바꾸면 배경이 검게 되어 취소선 검사가 틀린다."""
    if image.mode in ("RGBA", "LA", "P"):
        from PIL import Image

        image = image.convert("RGBA")
        bg = Image.new("RGB", image.size, "white")
        bg.paste(image, mask=image.getchannel("A"))
        return bg
    return image.convert("RGB")
