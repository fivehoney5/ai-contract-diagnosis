"""계약서 특약 구역 추출 결과를 팀 분석 결과 형식(docs/analysis-result.md)의 special_terms 조각으로 만든다.

document/risk의 grade(special_terms=...)에 그대로 넘긴다. 예외를 내지 않고 실패는 PARSE_FAILED로 돌려준다.
"""

from __future__ import annotations

from .masking import mask_special_terms
from .reader import ContractReadError, OcrUnavailableError, read_contract
from .special_terms import PARSE_FAILED, extract_special_terms


def _failed(reason: str, *, source: str | None = None, page_count: int | None = None) -> dict:
    return {
        "extraction_status": "failed",
        "reason_code": PARSE_FAILED,
        "reason": reason,
        "section_text": None,
        "page": None,
        "pages": [],
        "masked": False,
        "masking": None,
        "form": None,
        "base_terms": [],
        "custom_marker_found": False,
        "custom_terms": [],
        "custom_terms_text": None,
        "source": source,
        "page_count": page_count,
        "ocr_score": None,
        "warnings": [],
    }


def analyze_contract(sources, *, engine=None, mask: bool = True) -> dict:
    """계약서 PDF 또는 사진(여러 장이면 리스트, 쪽 순서대로)을 읽어 특약 구역을 돌려준다.

    sources: 경로, bytes, 파일 객체 또는 그 리스트. engine: OCR 엔진(생략하면 RapidOCR).
    mask: 개인정보(주민번호·전화·계좌·전자우편·당사자 이름)를 가린다. 끄는 것은 테스트·확인용.
    """
    try:
        doc = read_contract(sources, engine=engine)
    except OcrUnavailableError as e:
        return _failed(f"사진을 읽을 OCR 엔진이 없습니다: {e}")
    except ContractReadError as e:
        return _failed(f"계약서를 읽지 못했습니다: {e}")
    except Exception as e:  # 예상하지 못한 파일 구조
        return _failed(f"계약서를 읽는 중 오류가 났습니다: {type(e).__name__}")

    if not doc.lines:
        return _failed("계약서에서 글자를 읽지 못했습니다. 밝은 곳에서 문서 전체가 나오게 다시 찍어 주세요.",
                       source=doc.source, page_count=doc.page_count)
    try:
        res = extract_special_terms(doc.lines)
    except Exception as e:
        return _failed(f"특약 구역을 나누는 중 오류가 났습니다: {type(e).__name__}", source=doc.source,
                       page_count=doc.page_count)
    if res is None:
        return _failed("계약서에서 특약사항 칸을 찾지 못했습니다. 특약사항이 있는 쪽을 포함해 올려 주세요. "
                       "특약 누락 여부는 판단 보류합니다.", source=doc.source, page_count=doc.page_count)
    if not res["section_text"].strip():
        return _failed("특약사항 칸은 찾았지만 내용을 읽지 못했습니다. 특약 누락 여부는 판단 보류합니다.",
                       source=doc.source, page_count=doc.page_count)
    out = {
        "extraction_status": "ok",
        "reason_code": None,
        "reason": None,
        **res,
        "masked": False,
        "masking": None,
        "source": doc.source,
        "page_count": doc.page_count,
    }
    return mask_special_terms(out, [ln.text for ln in doc.lines]) if mask else out
