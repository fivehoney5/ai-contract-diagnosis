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
"""

from __future__ import annotations

import io
from datetime import date

from .parser import build_entries, parse_date, parse_title, summarize
from .pdf_reader import NoTextLayerError, RegistryReadError, read_registry_pdf

PARSE_FAILED = "PARSE_FAILED"

LEVEL_DANGER = "위험"
LEVEL_CAUTION = "주의"
LEVEL_CHECK = "확인필요"

# [초안] 팀 합의 전 값 (docs/risk-rules.md)
REGISTRY_MAX_AGE_DAYS = 7
TRUST_LEVEL = LEVEL_DANGER

SRC = "등기사항전부증명서 PDF"


def _flag(code, level, value, threshold, source) -> dict:
    return {"code": code, "level": level, "value": value, "threshold": threshold, "source": source}


def registry_flags(summary: dict, title: dict, *, is_collective: bool, issued: date | None, today: date | None,
                   max_age_days: int = REGISTRY_MAX_AGE_DAYS, trust_level: str = TRUST_LEVEL) -> list[dict]:
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
    if issued is not None and today is not None:
        age = (today - issued).days
        if age >= max_age_days:
            flags.append(_flag("REGISTRY_OUTDATED", LEVEL_CAUTION, age, max_age_days,
                               f"{SRC} 열람일시 (분석일 기준 경과 일수), 체크리스트 2쪽 잔금 전 재확인"))
    return flags


def _failed(reason: str) -> dict:
    return {
        "data_status_item": {"part": "registry", "status": "failed", "reason_code": PARSE_FAILED, "reason": reason},
        "property": None,
        "senior_amount_used": None,
        "registry_card": None,
        "flags": [],
        "detail": None,
    }


def analyze_registry(source, *, today: date | None = None, max_age_days: int = REGISTRY_MAX_AGE_DAYS,
                     trust_level: str = TRUST_LEVEL) -> dict:
    """등기부 PDF(경로, bytes, 파일 객체)를 읽어 팀 형식 조각으로 돌려준다. 예외를 내지 않는다."""
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    try:
        doc = read_registry_pdf(source)
    except NoTextLayerError:
        return _failed("등기부 PDF에 글자 층이 없습니다 (스캔 이미지로 보임). OCR 연동 전이라 읽지 못합니다. "
                       "인터넷등기소에서 발급한 PDF 원본을 올려 주세요.")
    except RegistryReadError as e:
        return _failed(f"등기부를 읽지 못했습니다: {e}")
    except Exception as e:  # 예상하지 못한 PDF 구조
        return _failed(f"등기부를 읽는 중 오류가 났습니다: {type(e).__name__}")

    try:
        entries = build_entries(doc.rows)
        title = parse_title(doc.rows, doc.header_text)
        summary = summarize(entries)
    except Exception as e:
        return _failed(f"등기부 항목을 해석하지 못했습니다: {type(e).__name__}")

    if not entries and not title["has_title_section"]:
        return _failed("갑구·을구 항목을 찾지 못했습니다")

    issued = parse_date(doc.issued_text)
    is_collective = "[집합건물]" in doc.header_text.replace(" ", "")
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
        "senior_amount_used": summary["senior_amount_total"],
        "registry_card": {
            "senior_amount_total": summary["senior_amount_total"],
            "senior_breakdown": summary["senior_breakdown"],
            "counts": summary["counts"],
            "earliest_security_date": summary["earliest_security_date"],
            "issued_date": issued.isoformat() if issued else None,
            "is_collective_building": is_collective,
            "ownership_history": summary["ownership_history"],
            "page_count": doc.page_count,
        },
        "flags": registry_flags(summary, title, is_collective=is_collective, issued=issued, today=today,
                                max_age_days=max_age_days, trust_level=trust_level),
        "detail": {"entries": [e.to_dict() for e in entries]},
    }
