"""부분 결과(주소·시세·등기부·특약)를 합쳐 팀 분석 결과(docs/analysis-result.md)를 만든다.

입력은 각 모듈이 돌려준 dict 그대로다. 다른 모듈을 import하지 않으므로 모듈이 아직 병합되지 않아도 쓸 수 있다.
    - address       : document/address resolve_address() 결과
    - price         : document/price analyze_price() 결과
    - registry      : document/registry analyze_registry() 결과
    - special_terms : 특약 구역 추출 결과 (작업 ⑥, 아래 special_terms_part 참고)

네트워크·LLM 호출 없음. 총점은 첫 시연 범위에서 빠졌으므로 만들지 않는다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .address_match import compare as compare_address
from .config import (
    DEFAULT_CONFIG,
    GRADE_DANGER,
    GRADE_HOLD,
    GRADE_SAFE,
    HIDDEN_SENIOR_CLAIM_CHECK_NEEDED,
    JEONSE_RATIO_HIGH,
    LEVEL_CAUTION,
    LEVEL_CHECK,
    LEVEL_DANGER,
    LEVEL_RANK,
    REGISTRY_ADDRESS_MISMATCH,
    SENIOR_BURDEN_HIGH,
    SPECIAL_TERMS_CHECK_NEEDED,
    RiskConfig,
    jeonse_source,
    senior_source,
)

PARTS = ("price", "registry", "special_terms")
PARSE_FAILED = "PARSE_FAILED"
KST = timezone(timedelta(hours=9))

PRICE_CARD_KEYS = (
    "deposit", "senior_amount_used", "estimated_price", "sample_count", "method", "method_label",
    "base_date", "trade_period", "confidence", "jeonse_ratio", "senior_burden_ratio",
)
SECTION_READ, SECTION_EMPTY, SECTION_FAILED = "read", "empty", "failed"  # 읽음 / 비어 있음 / 추출 실패
CAP_NOTE = " (시세 신뢰도 낮음: 주의까지만 반영)"
NO_CAP_NOTE = " (시세 신뢰도 낮음이지만 {pct} 이상이라 위험 유지, 깡통전세 기준(팀 확인 필요))"


def _flag(code, level, value, threshold, source) -> dict:
    return {"code": code, "level": level, "value": value, "threshold": threshold, "source": source}


def _status(part, status, reason_code=None, reason=None) -> dict:
    return {"part": part, "status": status, "reason_code": reason_code, "reason": reason}


# ---------- 비율 신호 ----------

def band_level(ratio: float | None, caution: float, danger: float) -> str | None:
    """caution 이상 주의, danger 초과 위험, 그 밖에는 None (신호 없음)."""
    if ratio is None:
        return None
    if ratio > danger:
        return LEVEL_DANGER
    if ratio >= caution:
        return LEVEL_CAUTION
    return None


def ratio_flags(price_card: dict, cfg: RiskConfig = DEFAULT_CONFIG) -> list[dict]:
    """가격 카드의 전세가율·선순위 부담률로 신호를 만든다. threshold에는 걸린 level의 경계값."""
    flags = []
    for code, key, caution, danger, source in (
        (JEONSE_RATIO_HIGH, "jeonse_ratio", cfg.jeonse_caution, cfg.jeonse_danger, jeonse_source(cfg)),
        (SENIOR_BURDEN_HIGH, "senior_burden_ratio", cfg.senior_caution, cfg.senior_danger, senior_source(cfg)),
    ):
        ratio = price_card.get(key)
        level = band_level(ratio, caution, danger)
        if level is not None:
            flags.append(_flag(code, level, ratio, danger if level == LEVEL_DANGER else caution, source))
    return flags


# ---------- 신호 합치기 ----------

def _rank(level: str) -> int:
    if level not in LEVEL_RANK:
        raise ValueError(f"알 수 없는 신호 level: {level!r}")
    return LEVEL_RANK[level]


def merge_flags(*groups: list[dict]) -> list[dict]:
    """같은 code는 하나만 남긴다 (level이 높은 쪽, 같으면 먼저 들어온 쪽). level 높은 순으로 정렬."""
    by_code: dict[str, dict] = {}
    order: list[str] = []
    for group in groups:
        for f in group or []:
            code = f["code"]
            if code not in by_code:
                order.append(code)
                by_code[code] = dict(f)
            elif _rank(f["level"]) > _rank(by_code[code]["level"]):
                by_code[code] = dict(f)
    flags = [by_code[c] for c in order]
    return sorted(flags, key=lambda f: -_rank(f["level"]))  # sorted는 안정 정렬이라 같은 level은 들어온 순서


def cap_low_confidence(flags: list[dict], confidence: str | None, cfg: RiskConfig = DEFAULT_CONFIG) -> list[dict]:
    """시세 신뢰도가 낮으면 시세 영역 신호의 위험을 주의로 낮춘다.

    단, 비율 신호 값이 cfg.no_cap_ratio(1.0) 이상이면 낮추지 않는다 (보증금·선순위가 시세 이상, 깡통전세).
    """
    if confidence != cfg.low_confidence:
        return flags
    out = []
    for f in flags:
        if f["code"] in cfg.price_area_codes and f["level"] == LEVEL_DANGER:
            v = f.get("value")
            if f["code"] in cfg.no_cap_codes and v is not None and v >= cfg.no_cap_ratio:
                note = NO_CAP_NOTE.format(pct=f"{round(cfg.no_cap_ratio * 100):g}%")
                f = dict(f, source=(f.get("source") or "") + note)
            else:
                f = dict(f, level=LEVEL_CAUTION, source=(f.get("source") or "") + CAP_NOTE)
        out.append(f)
    return out


# ---------- 등급 ----------

def decide_grade(flags: list[dict], items: list[dict], cfg: RiskConfig = DEFAULT_CONFIG,
                 price_card: dict | None = None) -> str:
    """등급 규칙 (docs/analysis-result.md 초안 + 팀 합의 대기 항목은 config).

    0. 입력 주소와 등기부 주소가 다르면(REGISTRY_ADDRESS_MISMATCH) 판단보류. 다른 집 등기부일 수 있어 위험보다 먼저 본다.
    1. 위험 신호가 하나라도 있으면 위험 (데이터 일부가 빠져도 이미 위험이 확인됨).
    2. 판단보류 대상 부분(cfg.hold_parts)이 ok가 아니면 판단보류.
    3. 선순위 부담률을 계산하지 못했으면 판단보류 (price_card를 넘긴 경우).
    3-1. 다가구 등(HIDDEN_SENIOR_CLAIM_CHECK_NEEDED)인데 다른 세대 보증금(price_card.other_tenant_deposits)을 모르면 판단보류.
    4. 그 밖에는 가장 높은 level. 확인필요는 반영하지 않고, 신호가 없으면 안전.
    5. cfg.grade_floor에 있는 신호가 있으면 그 등급보다 낮게 두지 않음 (기본은 비어 있음).
    """
    if cfg.address_mismatch_holds_grade and any(f["code"] == REGISTRY_ADDRESS_MISMATCH for f in flags):
        return GRADE_HOLD
    levels = [f["level"] for f in flags if f["level"] != LEVEL_CHECK]
    if LEVEL_DANGER in levels:
        return GRADE_DANGER
    hold = set(cfg.hold_parts)
    if cfg.special_terms_failure_holds_grade:
        hold.add("special_terms")
    if any(i["part"] in hold and i["status"] != "ok" for i in items):
        return GRADE_HOLD
    if cfg.hold_when_senior_ratio_missing and price_card is not None and price_card.get("senior_burden_ratio") is None:
        return GRADE_HOLD
    if (cfg.hold_when_hidden_senior_unknown and any(f["code"] == HIDDEN_SENIOR_CLAIM_CHECK_NEEDED for f in flags)
            and (price_card or {}).get("other_tenant_deposits") is None):
        return GRADE_HOLD
    grade = max(levels, key=_rank) if levels else GRADE_SAFE  # 안전·주의 level 이름이 등급 이름과 같음
    codes = {f["code"] for f in flags}
    floors = [g for c, g in cfg.grade_floor.items() if c in codes]
    if GRADE_HOLD in floors:
        return GRADE_HOLD
    for g in floors:
        if _rank(g) > _rank(grade):
            grade = g
    return grade


# ---------- 부분 결과 정리 ----------

def special_terms_part(st: dict | None) -> tuple[dict, dict | None]:
    """특약 추출 결과(작업 ⑥ 연결 지점) → (data_status 항목, special_terms 칸).

    st 모양: {"extraction_status": "ok"|"failed", "section_text": str|None, "page": int|None,
              "masked": bool, "reason_code": str(선택, 기본 PARSE_FAILED), "reason": str(선택),
              "section_status": {"base_terms": ..., "custom_terms": ...}(선택)}
    못 읽으면 특약 부분은 판단보류 (AI 모듈이 누락 대신 판단 보류로 처리).
    section_status는 구역별 read(읽음) / empty(비어 있음) / failed(추출 실패). 추출 실패를 "특약 없음"과 구분한다.
    """
    if st is None:
        return _status("special_terms", "not_provided"), None
    ok = st.get("extraction_status") == "ok" and bool(st.get("section_text"))
    block = {
        "extraction_status": "ok" if ok else "failed",
        "masked": bool(st.get("masked", False)),
        "page": st.get("page"),
        "section_text": st.get("section_text") if ok else None,
        "section_status": _section_status(st) if ok else {"base_terms": SECTION_FAILED, "custom_terms": SECTION_FAILED},
    }
    if ok:
        # 특약 추출 모듈(document/contract)이 주는 나눈 결과. AI 모듈이 직접 쓴 특약만 골라 볼 수 있게 넘긴다
        for key in ("form", "base_terms", "custom_terms", "custom_terms_text", "warnings"):
            if key in st:
                block[key] = st[key]
    if ok:
        return _status("special_terms", "ok"), block
    reason = st.get("reason") or "계약서에서 특약 구역을 읽지 못했습니다. 특약 누락 여부는 판단 보류합니다."
    return _status("special_terms", "failed", st.get("reason_code") or PARSE_FAILED, reason), block


def _section_status(st: dict) -> dict:
    """추출 모듈이 준 구역별 상태. 없으면(예전 입력) 텍스트가 있으니 직접 쓴 특약은 읽음으로 본다."""
    given = st.get("section_status") or {}
    return {
        "base_terms": given.get("base_terms") or (SECTION_READ if st.get("base_terms") else SECTION_EMPTY),
        "custom_terms": given.get("custom_terms") or SECTION_READ,
    }


def special_terms_flags(block: dict | None) -> list[dict]:
    """특약을 읽지 못했으면 전체 요약(신호 목록)에 "특약 확인 필요"를 넣는다. 확인필요라 등급에는 반영하지 않음."""
    if block is None:
        return []
    if block["extraction_status"] == "ok" and block["section_status"]["custom_terms"] != SECTION_FAILED:
        return []
    what = "특약 구역" if block["extraction_status"] != "ok" else "직접 쓴 특약(※ 기타)"
    return [_flag(SPECIAL_TERMS_CHECK_NEEDED, LEVEL_CHECK, None, None,
                  f"특약 확인 필요. 계약서에서 {what}을 읽지 못함 (특약이 없다는 뜻이 아님). "
                  "특약 누락 여부는 판단 보류, 계약서 원본의 특약사항 칸을 직접 확인")]


def registry_summary(registry: dict | None) -> dict | None:
    """선순위 합계 카드용 요약. 첫 시연은 합계 + "근저당 2건 · 전세권 1건" 한 줄 + 금액 못 읽은 건수."""
    if registry is None or registry["data_status_item"].get("status") != "ok":
        return None
    card = registry.get("registry_card") or {}
    counts = card.get("counts") or {}
    kinds = (("mortgage", "근저당"), ("hypothec", "저당권"), ("jeonse_right", "전세권"), ("lease_right", "임차권"))
    senior_counts = {k: int(counts.get(k) or 0) for k, _ in kinds}
    label = " · ".join(f"{name} {senior_counts[k]}건" for k, name in kinds if senior_counts[k])
    return {
        "senior_amount_total": card.get("senior_amount_total"),
        "senior_amount_complete": card.get("senior_amount_complete"),
        "senior_counts": senior_counts,
        "senior_amount_missing_count": card.get("senior_amount_missing_count") or 0,
        "summary_label": label or "선순위 등기 없음",
    }


def _price_status(price: dict | None, address: dict | None) -> dict:
    if price is not None:
        return dict(price["data_status_item"])
    if address is not None and address.get("status") != "ok":
        # 주소를 못 찾아 시세 조회를 못 한 경우: 주소 실패 코드를 그대로 쓴다
        return _status("price", "failed", address.get("reason_code"), address.get("reason"))
    return _status("price", "not_provided")


def _price_card(price: dict | None, registry: dict | None, other_tenant_deposits: int | None = None,
                cfg: RiskConfig = DEFAULT_CONFIG) -> dict:
    card = dict(price["price_card"]) if price is not None else {k: None for k in PRICE_CARD_KEYS}
    reg_senior = registry.get("senior_amount_used") if registry is not None else None
    recompute = False
    if card.get("senior_amount_used") is None and reg_senior is not None:
        # analyze_price에 선순위를 안 넣었으면 등기부 값으로 채우고 선순위 부담률을 다시 계산
        card["senior_amount_used"] = int(reg_senior)
        recompute = True
    card["other_tenant_deposits"] = other_tenant_deposits
    if other_tenant_deposits is not None and card.get("senior_amount_used") is not None:
        # 다가구: 사용자가 입력한 다른 세대 보증금 합계를 선순위에 더한다
        card["senior_amount_used"] = int(card["senior_amount_used"]) + int(other_tenant_deposits)
        recompute = True
    if recompute and card.get("estimated_price") and card.get("deposit") is not None:
        card["senior_burden_ratio"] = round((card["senior_amount_used"] + card["deposit"]) / card["estimated_price"], 4)
    card["confidence_label"] = cfg.low_confidence_label if card.get("confidence") == cfg.low_confidence else None
    return card


def _property(price: dict | None, registry: dict | None, address: dict | None) -> dict:
    p = (price or {}).get("property") or {}
    r = (registry or {}).get("property") or {}
    a = (address or {}).get("address") or {}
    return {
        "address_key": p.get("address_key") or a.get("address_key"),
        "address_display": a.get("jibun_address") or a.get("road_address") or r.get("address_display"),
        "housing_type": p.get("housing_type"),
        "exclusive_area_m2": p.get("exclusive_area_m2") if p.get("exclusive_area_m2") is not None
        else r.get("exclusive_area_m2"),
        "build_year": p.get("build_year"),
    }


def address_flags(address: dict | None, registry: dict | None) -> list[dict]:
    """입력 주소와 등기부 표제부 주소가 다르면 확인필요 신호. 비교할 수 없으면 신호 없음."""
    cmp = compare_address(address, registry)
    if cmp is None or cmp["match"]:
        return []
    what = "·".join(cmp["diff"])
    return [_flag(REGISTRY_ADDRESS_MISMATCH, LEVEL_CHECK, None, None,
                  f"주소 모듈 결과와 등기사항전부증명서 표제부의 {what}가 다름 (다른 집 등기부일 수 있어 등급 판단보류)")]


def build_analysis_result(
    *,
    price: dict | None = None,
    registry: dict | None = None,
    address: dict | None = None,
    special_terms: dict | None = None,
    other_tenant_deposits: int | None = None,
    analysis_id: str | None = None,
    analyzed_at: str | None = None,
    config: RiskConfig = DEFAULT_CONFIG,
) -> dict:
    """부분 결과를 합쳐 팀 분석 결과 전체를 만든다. 빠진 부분은 None으로 넘기면 not_provided.

    other_tenant_deposits: 다가구 등에서 사용자가 입력한 다른 세대 보증금 합계(원). 넣으면 선순위에 더한다.
    """
    st_item, st_block = special_terms_part(special_terms)
    items = [
        _price_status(price, address),
        dict(registry["data_status_item"]) if registry is not None else _status("registry", "not_provided"),
        st_item,
    ]
    card = _price_card(price, registry, other_tenant_deposits, config)
    flags = merge_flags(
        ratio_flags(card, config),
        (price or {}).get("flags"),
        (registry or {}).get("flags"),
        address_flags(address, registry),
        special_terms_flags(st_block),
    )
    flags = cap_low_confidence(flags, card.get("confidence"), config)
    flags = sorted(flags, key=lambda f: -_rank(f["level"]))

    return {
        "analysis_id": analysis_id,
        "analyzed_at": analyzed_at or datetime.now(KST).isoformat(timespec="seconds"),
        "grade": decide_grade(flags, items, config, card),
        "data_status": {
            "overall": "complete" if all(i["status"] == "ok" for i in items) else "incomplete",
            "items": items,
        },
        "property": _property(price, registry, address),
        "price_card": card,
        "registry_summary": registry_summary(registry),
        "flags": flags,
        "special_terms": st_block,
    }
