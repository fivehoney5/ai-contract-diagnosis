"""시세 추정 결과를 팀 분석 결과 형식(docs/analysis-result.md)의 조각으로 바꾼다.

돌려주는 조각:
    - data_status_item : data_status.items[]에 들어갈 price 부분 상태
    - property         : property에 들어갈 값 중 시세 모듈이 아는 것 (주소 키, 주택 유형, 면적, 건축년도)
    - price_card       : 가격 카드 (보증금, 선순위 사용액, 시세, 표본수, 방식, 기준일, 비율 등)
    - flags            : 시세·건물에서 나온 신호 (code, level, value, threshold, source)
    - detail           : 내부 추정 결과 전체 (세부 이유 코드, 근거 거래, notes). 화면에는 쓰지 않고 확인용

금액은 원 단위 정수, 비율은 0-1 소수(소수점 4자리)이고, 계산할 수 없으면 None(JSON null)이다.
등급(grade)과 선순위 비율 신호(SENIOR_BURDEN_HIGH 등)는 위험 점수 모듈에서 정한다.
"""

from __future__ import annotations

from datetime import date

from .building_register import CHECK_UNIT_PURPOSE, CHECK_VIOLATION, FLAG_NON_RESIDENTIAL, parse_jibun
from .estimator import (
    BUILD_YEAR_UNKNOWN,
    BUILDING_NOT_IDENTIFIED,
    INFLATION_THRESHOLD,
    INFLATION_WARNING,
    INSUFFICIENT_SAMPLES,
    NO_BUILDING_TRADES,
    NO_TRADES_IN_DONG,
    NO_TRADES_IN_REGION,
    ONLY_BULK_TRADES,
    PriceEstimate,
    _period,
    calc_jeonse_ratio,
    estimate_price,
    is_jibun,
)
from ..api_cache import summarize_events, track_cache_usage
from .rtms_client import RTMSApiError, RTMSParseError, normalize_type, type_label

# 팀 공통 실패 코드 (docs/analysis-result.md의 data_status.items[].reason_code)
ADDRESS_NOT_FOUND = "ADDRESS_NOT_FOUND"
NO_TRADES = "NO_TRADES"
API_UNAVAILABLE = "API_UNAVAILABLE"
PARSE_FAILED = "PARSE_FAILED"

# 시세 모듈 세부 이유 코드 -> 팀 공통 실패 코드 (임시, 팀 확인 필요)
REASON_CODE_MAP = {
    NO_TRADES_IN_REGION: NO_TRADES,
    NO_TRADES_IN_DONG: NO_TRADES,
    ONLY_BULK_TRADES: NO_TRADES,
    INSUFFICIENT_SAMPLES: NO_TRADES,
    NO_BUILDING_TRADES: NO_TRADES,
    BUILD_YEAR_UNKNOWN: NO_TRADES,
    BUILDING_NOT_IDENTIFIED: ADDRESS_NOT_FOUND,
}

CONFIDENCE_KO = {"high": "높음", "medium": "중간", "low": "낮음"}

# 신호 level (임시, 팀 확인 필요: NON_RESIDENTIAL, PRICE_INFLATION_SUSPECTED)
LEVEL_CAUTION = "주의"
LEVEL_CHECK = "확인필요"

VIOLATION_SOURCE = "공공데이터 건축물대장 API에 위반건축물 항목 없음, 건축물대장 열람본 확인 필요"


def map_reason_code(detail_code: str | None) -> str | None:
    """세부 이유 코드를 팀 공통 실패 코드로 바꾼다. 모르는 코드는 NO_TRADES로 본다."""
    if detail_code is None:
        return None
    return REASON_CODE_MAP.get(detail_code, NO_TRADES)


def make_address_key(bjdong_cd: str | None, jibun: str | None) -> str | None:
    """'법정동코드(10자리)-본번(4자리)-부번(4자리)'. 값이 없거나 산 지번이면 None.

    산 지번은 지금 주소 키 형식에 표시할 칸이 없어서 만들지 않는다 (팀 확인 필요).
    """
    if not bjdong_cd or not jibun:
        return None
    code = bjdong_cd.strip()
    if not (len(code) == 10 and code.isdigit()):
        return None
    try:
        plat_gb, bun, ji = parse_jibun(jibun)
    except ValueError:
        return None
    if plat_gb != "0":
        return None
    return f"{code}-{bun}-{ji}"


def _ratio(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def _flag(code, level, value, threshold, source) -> dict:
    return {"code": code, "level": level, "value": value, "threshold": threshold, "source": source}


def price_flags(
    est: PriceEstimate | None,
    property_type: str,
    *,
    inflation_threshold: float = INFLATION_THRESHOLD,
) -> list[dict]:
    """시세·건물에서 나온 신호 목록. 위반건축물 확인 안내는 항상 들어간다."""
    label = type_label(property_type)
    flags: list[dict] = []
    if est is not None:
        if est.reason_code == NO_BUILDING_TRADES:
            flags.append(_flag(
                NO_BUILDING_TRADES, LEVEL_CAUTION, 0, 1,
                f"국토교통부 {label} 매매 실거래가 (같은 건물 거래 건수, 준공 3년 이내)",
            ))
        if INFLATION_WARNING in est.warnings and est.price_per_m2 and est.dong_reference_price_per_m2:
            flags.append(_flag(
                INFLATION_WARNING, LEVEL_CAUTION,
                _ratio(est.price_per_m2 / est.dong_reference_price_per_m2 - 1), inflation_threshold,
                f"국토교통부 {label} 매매 실거래가 (신축 ㎡당 가격과 같은 동 비슷한 면적·연식 거래의 ㎡당 중앙값 비교)",
            ))
        if FLAG_NON_RESIDENTIAL in est.building_flags:
            flags.append(_flag(
                FLAG_NON_RESIDENTIAL, LEVEL_CAUTION, None, None,
                "공공데이터 건축물대장 API (주용도 또는 해당 호 전유부 용도가 주거용이 아님)",
            ))
    checks = est.checks_needed if est is not None else [CHECK_VIOLATION]
    if CHECK_UNIT_PURPOSE in checks:
        flags.append(_flag(
            CHECK_UNIT_PURPOSE, LEVEL_CHECK, None, None,
            "공공데이터 건축물대장 API 전유부 (같은 호수가 여러 건이고 용도가 달라 동 확인 필요)",
        ))
    if CHECK_VIOLATION in checks:
        flags.append(_flag(CHECK_VIOLATION, LEVEL_CHECK, None, None, VIOLATION_SOURCE))
    return flags


def build_price_result(
    est: PriceEstimate | None,
    *,
    property_type: str,
    area: float,
    deposit: int,
    senior_amount_used: int | None = None,
    base_date: date,
    period: tuple[str, str],
    bjdong_cd: str | None = None,
    jibun: str | None = None,
    failure: tuple[str, str] | None = None,
    inflation_threshold: float = INFLATION_THRESHOLD,
    data_source: str | None = None,
    cache_note: str | None = None,
) -> dict:
    """추정 결과(est)를 팀 형식 조각으로 바꾼다 (네트워크 호출 없음).

    failure     : API 호출 자체가 실패했을 때 (팀 실패 코드, 이유). 이때 est는 None.
    data_source : 공공 API 응답을 어디서 받았는지 (api / cache / stale_cache). 모르면 None
    cache_note  : stale_cache일 때 안내 문구. 성공이면 reason에 넣는다
    """
    price = est.price if est is not None and est.status == "estimated" else None

    if failure is not None:
        status_item = {"part": "price", "status": "failed", "reason_code": failure[0], "reason": failure[1]}
    elif price is None:
        status_item = {
            "part": "price", "status": "failed",
            "reason_code": map_reason_code(est.reason_code if est else None),
            "reason": est.reason if est else None,
        }
    else:
        status_item = {"part": "price", "status": "ok", "reason_code": None, "reason": cache_note}
    status_item["data_source"] = data_source

    senior_ratio = None
    if senior_amount_used is not None:
        senior_ratio = calc_jeonse_ratio(senior_amount_used + deposit, price)

    price_card = {
        "deposit": int(deposit),
        "senior_amount_used": None if senior_amount_used is None else int(senior_amount_used),
        "estimated_price": price,
        "sample_count": est.sample_count if price is not None else 0,
        "method": est.basis if price is not None else None,
        "method_label": est.basis_label if price is not None else None,
        "base_date": base_date.isoformat(),
        "trade_period": {"from": period[0], "to": period[1]},
        "confidence": CONFIDENCE_KO.get(est.confidence) if price is not None and est.confidence else None,
        "jeonse_ratio": _ratio(calc_jeonse_ratio(deposit, price)),
        "senior_burden_ratio": _ratio(senior_ratio),
    }

    jb = (jibun or "").strip()
    if not jb and est is not None and est.building_info is not None:
        jb = est.building_info.jibun
    prop = {
        "address_key": make_address_key(bjdong_cd, jb),
        "housing_type": type_label(property_type),
        "exclusive_area_m2": area,
        "build_year": est.build_year if est is not None else None,
    }

    return {
        "data_status_item": status_item,
        "property": prop,
        "price_card": price_card,
        "flags": price_flags(est, property_type, inflation_threshold=inflation_threshold),
        "detail": est.to_dict() if est is not None else None,
    }


def analyze_price(
    property_type: str,
    lawd_cd: str,
    dong: str,
    building: str,
    area: float,
    deposit: int,
    *,
    senior_amount_used: int | None = None,
    months: int = 12,
    today: date | None = None,
    bjdong_cd: str | None = None,
    jibun: str | None = None,
    **kwargs,
) -> dict:
    """시세를 추정해서 팀 형식 조각(build_price_result 참고)으로 돌려준다.

    API 오류는 예외 대신 data_status_item의 실패 코드로 돌려준다.
        - 시군구코드(lawd_cd)가 5자리 숫자가 아님    -> ADDRESS_NOT_FOUND
        - API 응답이 XML이 아님                       -> PARSE_FAILED
        - 연결 실패, 서버 오류, 인증키 오류, 키 없음  -> API_UNAVAILABLE
    kwargs는 estimate_price 옵션 (trades, fetcher, building_fetcher, dong_nm, ho_nm, build_year 등).
    """
    if deposit <= 0:
        raise ValueError(f"보증금은 0보다 커야 합니다: {deposit}")
    ptype = normalize_type(property_type)
    today = today or date.today()
    period = _period(months, today)
    common = dict(
        property_type=ptype, area=area, deposit=deposit, senior_amount_used=senior_amount_used,
        base_date=today, period=period, bjdong_cd=bjdong_cd,
        jibun=jibun or (building.strip() if is_jibun(building) else None),
        inflation_threshold=kwargs.get("inflation_threshold", INFLATION_THRESHOLD),
    )

    if not (len(lawd_cd) == 5 and lawd_cd.isdigit()):
        return build_price_result(
            None, failure=(ADDRESS_NOT_FOUND, f"시군구코드(법정동코드 앞 5자리)가 올바르지 않습니다: {lawd_cd!r}"), **common
        )
    error: RuntimeError | None = None
    with track_cache_usage() as events:  # 캐시를 썼는지 모아서 data_source에 쓴다
        try:
            est = estimate_price(
                ptype, lawd_cd, dong, building, area, months=months, today=today,
                bjdong_cd=bjdong_cd, jibun=jibun, **kwargs,
            )
        except RuntimeError as e:  # RTMSApiError, .env에 키가 없음
            est, error = None, e
    common["data_source"], common["cache_note"] = summarize_events(events)

    if isinstance(error, RTMSParseError):
        return build_price_result(None, failure=(PARSE_FAILED, f"실거래가 응답을 읽지 못했습니다: {error}"), **common)
    if isinstance(error, RTMSApiError):
        return build_price_result(None, failure=(API_UNAVAILABLE, f"실거래가 조회 실패: {error}"), **common)
    if error is not None:
        return build_price_result(None, failure=(API_UNAVAILABLE, str(error)), **common)
    return build_price_result(est, **common)
