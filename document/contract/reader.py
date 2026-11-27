"""계약서(PDF·사진)를 읽어 쪽마다 위에서 아래 순서의 줄 목록으로 바꾼다.

- 글자 층이 있는 PDF: pdfplumber로 글자를 바로 읽는다 (OCR 없음).
- 글자 층이 없는 PDF(스캔): pypdfium2로 쪽을 그림으로 바꾼 뒤 OCR.
- 사진(jpg, png 등): OCR. 여러 장이면 넘긴 순서대로 1쪽, 2쪽...

OCR 엔진은 바꿔 끼울 수 있다. 엔진은 그림(PIL.Image)을 받아 [(글자, 네 꼭짓점 좌표, 점수), ...]를 돌려주는
호출 가능한 객체다. 기본 엔진은 RapidOCR(PaddleOCR 한국어 모델을 onnxruntime으로 돌림)이고,
설치되어 있지 않으면 OcrUnavailableError를 낸다.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
PDF_RENDER_SCALE = 3.0  # 스캔 PDF를 그림으로 바꿀 때 배율 (72dpi x 3 = 216dpi)
MIN_TEXT_CHARS = 20
DESKEW_MIN_DEGREES = 0.5  # 이보다 기울면 돌려서 다시 읽는다  # 쪽 전체 글자 수가 이보다 적으면 글자 층이 없다고 본다


class ContractReadError(Exception):
    """파일을 열 수 없거나 형식을 알 수 없음."""


class OcrUnavailableError(ContractReadError):
    """OCR 엔진이 설치되어 있지 않음."""


@dataclass
class Line:
    text: str
    page: int  # 1부터
    top: float  # 쪽 안에서 위쪽 좌표 (정렬용)
    score: float | None = None  # OCR 신뢰도 0-1. 글자 층이면 None


@dataclass
class ContractPages:
    lines: list[Line]
    page_count: int
    source: str  # "text_layer" | "ocr" | "mixed"

    def ocr_score(self) -> float | None:
        scores = [ln.score for ln in self.lines if ln.score is not None]
        return round(sum(scores) / len(scores), 4) if scores else None


# ---------- OCR ----------

_default_engine = None


def rapidocr_engine():
    """RapidOCR 한국어(PP-OCRv5) 엔진. 처음 부를 때 모델을 내려받는다 (약 20MB)."""
    try:
        from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR
    except ImportError as e:
        raise OcrUnavailableError(
            "OCR 엔진(rapidocr, onnxruntime)이 설치되어 있지 않습니다 (pip install -r document/contract/requirements.txt)"
        ) from e
    eng = RapidOCR(params={
        "Rec.lang_type": LangRec.KOREAN,
        "Rec.ocr_version": OCRVersion.PPOCRV5,
        "Rec.model_type": ModelType.MOBILE,
        "Global.log_level": "warning",
        # 글자 방향 분류기를 끄면 기울어진 사진에서 줄을 거꾸로 읽어 "을", "o" 같은 조각이 나오는 문제가 사라진다
        "Global.use_cls": False,
        # 기본값(736)은 휴대폰 사진을 너무 줄여서 촘촘한 줄이 붙어 버린다
        "Det.limit_side_len": 2000,
        "Det.limit_type": "max",
    })

    def ocr(arr):
        res = eng(arr)
        if res is None or res.txts is None:
            return []
        return [(t, [tuple(p) for p in b.tolist()], float(s)) for t, b, s in zip(res.txts, res.boxes, res.scores)]

    def run(image):
        import numpy as np

        image = image.convert("RGB")
        items = ocr(np.asarray(image))
        angle = estimate_skew(items)
        if abs(angle) >= DESKEW_MIN_DEGREES:
            # 사진이 기울어 있으면 반듯하게 돌린 뒤 다시 읽는다
            from PIL import Image

            image = image.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor="white")
            items = ocr(np.asarray(image))
        return items

    run.raw = ocr  # 기울기 보정 없이 한 번만 읽기 (등기부 모듈이 보정한 그림을 직접 쓰려고 씀)
    return run


def estimate_skew(items) -> float:
    """긴 글자 상자들의 윗변 기울기 중앙값(도). 그림 좌표는 아래로 갈수록 y가 커지므로 오른쪽이 올라가면 음수."""
    import math

    angles = []
    for _t, pts, _s in items:
        dx, dy = pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]
        if dx >= 200:
            angles.append(math.degrees(math.atan2(dy, dx)))
    if len(angles) < 3:
        return 0.0
    angles.sort()
    return angles[len(angles) // 2]


def get_default_engine():
    global _default_engine
    if _default_engine is None:
        _default_engine = rapidocr_engine()
    return _default_engine


def group_ocr_lines(items, page: int) -> list[Line]:
    """OCR 조각(글자, 꼭짓점, 점수)을 같은 높이끼리 묶어 줄로 만든다. 사진이 조금 기울어도 되도록 세로 중심으로 묶는다."""
    boxes = []
    for text, pts, score in items:
        text = (text or "").strip()
        if not text:
            continue
        ys = [p[1] for p in pts]
        xs = [p[0] for p in pts]
        boxes.append({"text": text, "top": min(ys), "bottom": max(ys), "left": min(xs), "score": score})
    if not boxes:
        return []
    heights = sorted(b["bottom"] - b["top"] for b in boxes)
    tol = max(heights[len(heights) // 2] * 0.5, 1.0)
    boxes.sort(key=lambda b: (b["top"] + b["bottom"]) / 2)
    rows: list[list[dict]] = []
    for b in boxes:
        mid = (b["top"] + b["bottom"]) / 2
        if rows:
            last = rows[-1]
            last_mid = sum((x["top"] + x["bottom"]) / 2 for x in last) / len(last)
            if abs(mid - last_mid) <= tol:
                last.append(b)
                continue
        rows.append([b])
    lines = []
    for row in rows:
        row.sort(key=lambda b: b["left"])
        lines.append(Line(
            text=" ".join(b["text"] for b in row),
            page=page,
            top=min(b["top"] for b in row),
            score=round(sum(b["score"] for b in row) / len(row), 4),
        ))
    return lines


def ocr_image(image, page: int, engine=None) -> list[Line]:
    engine = engine or get_default_engine()
    return group_ocr_lines(engine(image), page)


# ---------- PDF ----------

def _pdf_text_lines(page, page_no: int) -> list[Line]:
    words = page.extract_words(keep_blank_chars=False, use_text_flow=False, x_tolerance=1.5, y_tolerance=3)
    rows: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if rows and abs(w["top"] - rows[-1][0]["top"]) <= 3:
            rows[-1].append(w)
        else:
            rows.append([w])
    return [Line(" ".join(x["text"] for x in sorted(r, key=lambda w: w["x0"])), page_no, r[0]["top"]) for r in rows]


def read_pdf(source, engine=None) -> ContractPages:
    try:
        import pdfplumber
    except ImportError as e:
        raise ContractReadError("pdfplumber가 설치되어 있지 않습니다 (pip install -r document/contract/requirements.txt)") from e
    try:
        pdf = pdfplumber.open(source)
    except Exception as e:
        raise ContractReadError("PDF를 열 수 없습니다 (손상되었거나 암호가 걸린 파일)") from e
    lines: list[Line] = []
    kinds = set()
    with pdf:
        for i, page in enumerate(pdf.pages, start=1):
            page_lines = _pdf_text_lines(page, i)
            if sum(len(ln.text) for ln in page_lines) >= MIN_TEXT_CHARS:
                lines.extend(page_lines)
                kinds.add("text_layer")
                continue
            # 글자 층이 없는 쪽: 그림으로 바꿔 OCR
            image = page.to_image(resolution=int(72 * PDF_RENDER_SCALE)).original
            lines.extend(ocr_image(image, i, engine))
            kinds.add("ocr")
        count = len(pdf.pages)
    return ContractPages(lines, count, "mixed" if len(kinds) > 1 else (kinds.pop() if kinds else "text_layer"))


# ---------- 입구 ----------

def _open_image(src):
    try:
        from PIL import Image, ImageOps
    except ImportError as e:
        raise ContractReadError("Pillow가 설치되어 있지 않습니다") from e
    try:
        img = Image.open(io.BytesIO(src) if isinstance(src, (bytes, bytearray)) else src)
        return ImageOps.exif_transpose(img)  # 휴대폰 사진의 회전 정보 반영
    except Exception as e:
        raise ContractReadError("그림 파일을 열 수 없습니다") from e


def _kind(src) -> str:
    if isinstance(src, (bytes, bytearray)):
        return "pdf" if bytes(src[:5]) == b"%PDF-" else "image"
    if isinstance(src, (str, os.PathLike)):
        ext = os.path.splitext(str(src))[1].lower()
        if ext == ".pdf":
            return "pdf"
        if ext in IMAGE_EXTS:
            return "image"
        raise ContractReadError(f"지원하지 않는 파일 형식입니다 ({ext or '확장자 없음'}). PDF 또는 사진을 올려 주세요.")
    head = src.read(5)
    src.seek(0)
    return "pdf" if head == b"%PDF-" else "image"


def read_contract(sources, engine=None) -> ContractPages:
    """계약서 파일 하나 또는 여러 개(사진 여러 장)를 읽는다. 경로, bytes, 파일 객체 모두 가능."""
    if not isinstance(sources, (list, tuple)):
        sources = [sources]
    if not sources:
        raise ContractReadError("파일이 없습니다")
    lines: list[Line] = []
    kinds = set()
    page_no = 0
    for src in sources:
        if _kind(src) == "pdf":
            doc = read_pdf(io.BytesIO(src) if isinstance(src, (bytes, bytearray)) else src, engine)
            for ln in doc.lines:
                ln.page += page_no
            lines.extend(doc.lines)
            page_no += doc.page_count
            kinds.add(doc.source)
        else:
            page_no += 1
            lines.extend(ocr_image(_open_image(src), page_no, engine))
            kinds.add("ocr")
    source = "mixed" if len(kinds) > 1 or "mixed" in kinds else kinds.pop()
    return ContractPages(lines, page_no, source)
