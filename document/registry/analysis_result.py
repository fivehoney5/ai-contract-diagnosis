"""등기부 분석 결과를 팀 분석 결과 형식(docs/analysis-result.md)의 조각으로 바꾼다.

돌려주는 조각:
    - data_status_item  : data_status.items[]의 registry 부분 상태
    - property          : 표제부에서 읽은 주소·전유 면적·구조
    - senior_amount_used: 선순위 합계(원). 시세 모듈 analyze_price(senior_amount_used=...)에 그대로 넣는다
    - registry_card     : 선순위 내역, 권리 종류별 건수, 소유권 이력(이름 마스킹), 열람일
    - flags             : 등기부 신호 (code, level, value, threshold, source). 규칙은 docs/risk-rules.md
    - detail            : 갑구·을구 항목 전체 (말소 여부와 근거 포함). 화면에는 쓰지 않고 확인용

선순위 부담률 신호(SENIOR_BURDEN_HIGH)는 시세가 있어야 하므로 여기서 내지 않는다 (시세 모듈·위험 점수 모듈 몫).
예외를 내지 않고 실패는 data_status_item의 PARSE_FAILED로 돌려준다.
스캔본(글자 층 없는 PDF)과 사진은 ocr_reader.py로 읽는다 (registry_card.read_method, ocr_score).
"""

from __future__ import annotations

import io
import os
from datetime import date

from .parser import build_entries, parse_date, parse_title, summarize
from ..contract.reader import IMAGE_EXTS, OcrUnavailableError
from .ocr_reader import read_registry_images, render_pdf_pages
from .pdf_reader import NoTextLayerError, RegistryReadError, read_registry_pdf

PARSE_FAILED = "PARSE_FAILED"

LEVEL_DANGER = "위험"
LEVEL_CAUTION = "주의"
LEVEL_CHECK = "확인필요"

# [초안] 팀 합의 전 값 (docs/risk-rules.md)
REGISTRY_MAX_AGE_DAYS = 7
TRUST_LEVEL = LEVEL_DANGER
# 스캔본·사진 OCR 평균 신뢰도가 이보다 낮으면 판단보류 [추측: 가상 등기부 사진 시험으로 정한 값, 팀 합의 필요]
OCR_MIN_SCORE = 0.85

SRC = "등기사항전부증명서 PDF"


def _flag(code, level, value, threshold, source) -> dict:
    return {"code": code, "level": level, "value": value, "threshold": threshold, "source": source}


def registry_flags(summary: dict, title: dict, *, is_collective: bool, issued: date | None, today: date | None,
                   max_age_days: int = REGISTRY_MAX_AGE_DAYS, trust_level: str = TRUST_LEVEL, entries=()) -> list[dict]:
    c = summary["counts"]
    flags = []
    if c["restriction"]:
        flags.append(_flag("OWNERSHIP_RESTRICTED", LEVEL_DANGER, c["restriction"], 1,
                           f"{SRC} 갑구 (말소되지 않은 압류·가압류·가처분·경매개시결정 건수), 안심 전세계약 체크리스트 1쪽"))
    if c["provisional_registration"]:
        flags.append(_flag("PROVISIONAL_REGISTRATION", LEVEL_DANGER, c["provisional_registration"], 1,
                           f"{SRC} 갑구 (말소되지 않은 가등기 건수), HUG 등기부 확인 안내"))
    if c["trust"]:
        flags.append(_flag("TRUST_REGISTERED", trust_level, c["trust"], 1,
                           f"{SRC} 갑구 (말소되지 않은 신탁 등기), 체크리스트 1쪽 \"신탁등기는 전문가와 함께 확인\""))
    if c["lease_right"]:
        flags.append(_flag("LEASE_RIGHT_REGISTERED", LEVEL_DANGER, c["lease_right"], 1,
                           f"{SRC} 을구 (말소되지 않은 주택임차권등기, 이전 세입자 보증금 미반환 신호)"))
    if c["jeonse_right"]:
        flags.append(_flag("JEONSE_RIGHT_EXISTS", LEVEL_CAUTION, c["jeonse_right"], 1,
                           f"{SRC} 을구 (말소되지 않은 전세권 건수), HUG 등기부 확인 안내"))
    if summary["senior_amount_missing_ranks"]:
        flags.append(_flag("SENIOR_AMOUNT_UNREADABLE", LEVEL_CHECK, len(summary["senior_amount_missing_ranks"]), 1,
                           f"{SRC} 을구 (말소되지 않은 근저당권·전세권·임차권 중 금액을 읽지 못한 건수, 선순위 합계가 실제보다 적을 수 있음)"))
    if is_collective and (not title["has_land_right"] or title["separate_land_registration"]):
        flags.append(_flag("LAND_RIGHT_CHECK_NEEDED", LEVEL_CHECK, None, None,
                           f"{SRC} 표제부 (집합건물인데 대지권 표시 없음 또는 \"별도등기 있음\" 문구), HUG 등기부 확인 안내"))
    if not is_collective:
        flags.append(_flag("HIDDEN_SENIOR_CLAIM_CHECK_NEEDED", LEVEL_CHECK, None, None,
                           f"다른 세대의 선순위 보증금 확인 필요. {SRC} 표제부 (집합건물이 아님: 다가구 등은 다른 세입자 보증금이 등기부에 나오지 않아 "
                           "선순위 합계가 실제보다 적을 수 있음. 확정일자 부여현황·전입세대로 선순위 보증금 확인), "
                           "체크리스트 1쪽 (안내서 p.25-26)"))
    unconfirmed = [e for e in entries if e.status == "active" and "strike_unconfirmed" in e.cancel_basis]
    if unconfirmed:
        flags.append(_flag("STRIKE_WITHOUT_CANCEL_ENTRY", LEVEL_CHECK, len(unconfirmed), 1,
                           "스캔본·사진 등기부 (취소선처럼 보이지만 말소 등기가 없어 살아 있는 것으로 계산한 등기 건수. "
                           "선이 잘못 잡혔을 수 있으니 원본 등기부에서 말소 여부 확인)"))
    if issued is not None and today is not None:
        age = (today - issued).days
        if age >= max_age_days:
            flags.append(_flag("REGISTRY_OUTDATED", LEVEL_CAUTION, age, max_age_days,
                               f"{SRC} 열람일시 (분석일 기준 경과 일수), 체크리스트 2쪽 잔금 전 재확인"))
    return flags


def senior_amount_for_price(summary: dict) -> int | None:
    """시세 모듈에 넘길 선순위 금액. 금액을 못 읽은 선순위 등기가 하나라도 있으면 None.

    읽은 금액만 더하면 선순위 부담률이 실제보다 낮게 나와 위험을 놓치므로 판단보류가 되게 한다.
    읽은 금액까지의 합계는 registry_card.senior_amount_total에 남긴다.
    """
    if summary["senior_amount_missing_ranks"]:
        return None
    return summary["senior_amount_total"]


def _failed(reason: str) -> dict:
    return {
        "data_status_item": {"part": "registry", "status": "failed", "reason_code": PARSE_FAILED, "reason": reason},
        "property": None,
        "senior_amount_used": None,
        "registry_card": None,
        "flags": [],
        "detail": None,
    }


def _is_image(src) -> bool:
    if isinstance(src, (bytes, bytearray)):
        return bytes(src[:5]) != b"%PDF-"
    if isinstance(src, (str, os.PathLike)):
        return os.path.splitext(str(src))[1].lower() in IMAGE_EXTS
    if hasattr(src, "read") and hasattr(src, "seek"):
        head = src.read(5)
        src.seek(0)
        return head != b"%PDF-"
    return hasattr(src, "convert")  # PIL.Image


def _open_image(src):
    if hasattr(src, "convert"):
        return src
    try:
        from PIL import Image, ImageOps
    except ImportError as e:
        raise RegistryReadError("사진을 읽으려면 Pillow가 필요합니다. PDF 원본을 올려 주세요.") from e
    try:
        img = Image.open(io.BytesIO(src) if isinstance(src, (bytes, bytearray)) else src)
        return ImageOps.exif_transpose(img)  # 휴대폰 사진의 회전 정보 반영
    except Exception as e:
        raise RegistryReadError("PDF나 사진 파일로 열 수 없습니다") from e


def _read(source, engine):
    """(RegistryDocument, OCR 점수 또는 None). 글자 층 PDF는 그대로, 스캔 PDF·사진(여러 장 가능)은 OCR."""
    sources = list(source) if isinstance(source, (list, tuple)) else [source]
    if not sources:
        raise RegistryReadError("파일이 없습니다")
    if len(sources) == 1 and not _is_image(sources[0]):
        src = io.BytesIO(sources[0]) if isinstance(sources[0], (bytes, bytearray)) else sources[0]
        try:
            return read_registry_pdf(src), None
        except NoTextLayerError:
            if hasattr(src, "seek"):
                src.seek(0)
            return read_registry_images(render_pdf_pages(src), engine)
    images = []
    for s in sources:
        if not _is_image(s):
            raise RegistryReadError("PDF와 사진을 섞어 올릴 수 없습니다. 사진만 여러 장 올리거나 PDF 하나를 올려 주세요.")
        images.append(_open_image(s))
    return read_registry_images(images, engine)


def analyze_registry(source, *, today: date | None = None, max_age_days: int = REGISTRY_MAX_AGE_DAYS,
                     trust_level: str = TRUST_LEVEL, engine=None) -> dict:
    """등기부(PDF, 스캔 PDF, 사진 또는 사진 여러 장의 목록. 경로, bytes, 파일 객체)를 읽어 팀 형식 조각으로 돌려준다.
    스캔본·사진은 OCR로 읽고, OCR 평균 신뢰도가 OCR_MIN_SCORE보다 낮으면 판단보류(PARSE_FAILED)로 돌려준다.
    engine은 OCR 엔진을 바꿔 끼울 때만 넘긴다 (테스트용). 예외를 내지 않는다."""
    ocr_score = None
    try:
        doc, ocr_score = _read(source, engine)
    except OcrUnavailableError:
        return _failed("등기부가 스캔본·사진인데 OCR 엔진(rapidocr)이 설치되어 있지 않아 읽지 못합니다. "
                       "인터넷등기소에서 발급한 PDF 원본을 올려 주세요.")
    except RegistryReadError as e:
        return _failed(f"등기부를 읽지 못했습니다: {e}")
    except Exception as e:  # 예상하지 못한 PDF 구조
        return _failed(f"등기부를 읽는 중 오류가 났습니다: {type(e).__name__}")
    if ocr_score is not None and ocr_score < OCR_MIN_SCORE:
        return _failed(f"스캔본·사진의 글자를 충분히 읽지 못했습니다 (OCR 신뢰도 {ocr_score:.2f}). "
                       "더 밝고 반듯하게 찍거나 인터넷등기소 PDF 원본을 올려 주세요.")

    try:
        entries = build_entries(doc.rows, trust_strike=ocr_score is None)
        title = parse_title(doc.rows, doc.header_text)
        summary = summarize(entries)
    except Exception as e:
        return _failed(f"등기부 항목을 해석하지 못했습니다: {type(e).__name__}")

    if not entries and not title["has_title_section"]:
        return _failed("갑구·을구 항목을 찾지 못했습니다")

    issued = parse_date(doc.issued_text)
    # 쪽 머리 [집합건물] 줄이 없어도 전유부분 표제부가 있으면 집합건물로 본다
    is_collective = "[집합건물]" in doc.header_text.replace(" ", "") or title["has_unit_section"]
    today = today or date.today()
    return {
        "data_status_item": {"part": "registry", "status": "ok", "reason_code": None, "reason": None},
        "property": {
            "address_display": title["address_display"],
            "road_address": title["road_address"],
            "unit_no": title["unit_no"],
            "exclusive_area_m2": title["exclusive_area_m2"],
            "structure": title["structure"],
        },
        "senior_amount_used": senior_amount_for_price(summary),
        "registry_card": {
            "senior_amount_total": summary["senior_amount_total"],
            "senior_amount_complete": not summary["senior_amount_missing_ranks"],
            "senior_amount_missing_count": len(summary["senior_amount_missing_ranks"]),
            "senior_breakdown": summary["senior_breakdown"],
            "counts": summary["counts"],
            "earliest_security_date": summary["earliest_security_date"],
            "issued_date": issued.isoformat() if issued else None,
            "is_collective_building": is_collective,
            "ownership_history": summary["ownership_history"],
            "page_count": doc.page_count,
            "read_method": "ocr" if ocr_score is not None else "text_layer",
            "ocr_score": ocr_score,
        },
        "flags": registry_flags(summary, title, is_collective=is_collective, issued=issued, today=today,
                                max_age_days=max_age_days, trust_level=trust_level, entries=entries),
        "detail": {"entries": [e.to_dict() for e in entries]},
    }
