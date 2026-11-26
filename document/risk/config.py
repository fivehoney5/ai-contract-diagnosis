"""위험 등급 모듈의 기준값. 팀 합의 전 값([초안])은 모두 여기에서만 바꾼다.

docs/risk-rules.md 규칙표와 맞춘다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 등급(grade)과 신호 level 값 (docs/analysis-result.md, [초안])
GRADE_SAFE = "안전"
GRADE_CAUTION = "주의"
GRADE_DANGER = "위험"
GRADE_HOLD = "판단보류"

LEVEL_SAFE = "안전"
LEVEL_CAUTION = "주의"
LEVEL_DANGER = "위험"
LEVEL_CHECK = "확인필요"

# level 높낮이. 확인필요는 등급에 반영하지 않으므로 가장 낮게 둔다.
LEVEL_RANK = {LEVEL_CHECK: 0, LEVEL_SAFE: 1, LEVEL_CAUTION: 2, LEVEL_DANGER: 3}

# 신호 코드
JEONSE_RATIO_HIGH = "JEONSE_RATIO_HIGH"
SENIOR_BURDEN_HIGH = "SENIOR_BURDEN_HIGH"
NO_BUILDING_TRADES = "NO_BUILDING_TRADES"
REGISTRY_ADDRESS_MISMATCH = "REGISTRY_ADDRESS_MISMATCH"
PRICE_INFLATION_SUSPECTED = "PRICE_INFLATION_SUSPECTED"
HIDDEN_SENIOR_CLAIM_CHECK_NEEDED = "HIDDEN_SENIOR_CLAIM_CHECK_NEEDED"


@dataclass(frozen=True)
class RiskConfig:
    # 전세가율(보증금/시세): caution 이상 주의, danger 초과 위험 (정현 2026-11-26, 70% 구간은 팀 답변 대기)
    jeonse_caution: float = 0.7
    jeonse_danger: float = 0.8
    # 선순위 부담률((선순위+보증금)/시세): 같은 구간 (기준표 초안 0.6/0.7과 다름, 팀 안건)
    senior_caution: float = 0.7
    senior_danger: float = 0.8

    # 시세 신뢰도가 이 값이면 시세 영역 신호는 주의까지만 반영
    low_confidence: str = "낮음"
    price_area_codes: frozenset = field(default_factory=lambda: frozenset({
        JEONSE_RATIO_HIGH, SENIOR_BURDEN_HIGH, NO_BUILDING_TRADES, PRICE_INFLATION_SUSPECTED,
    }))

    # 판단보류: 이 부분이 실패(또는 미제출)했고 위험 신호가 없으면 등급을 판단보류로 둔다 [초안]
    #   price    : 시세를 못 구해 비율 계산 불가 (analysis-result.md 초안 규칙)
    #   registry : 등기부를 못 읽음 (선순위·권리 제한을 알 수 없음)
    hold_parts: frozenset = field(default_factory=lambda: frozenset({"price", "registry"}))
    # 특약 추출 실패는 특약 부분만 판단보류로 두고 전체 등급에는 반영하지 않음 [초안]
    special_terms_failure_holds_grade: bool = False
    # 시세·등기부가 ok여도 선순위 부담률을 계산하지 못하면(선순위 금액을 못 읽음 등) 판단보류
    hold_when_senior_ratio_missing: bool = True

    # 비율이 이 값 이상이면 시세 신뢰도가 낮아도 위험을 낮추지 않음 (깡통전세 기준, 팀 확인 필요)
    no_cap_ratio: float = 1.0
    no_cap_codes: frozenset = field(default_factory=lambda: frozenset({JEONSE_RATIO_HIGH, SENIOR_BURDEN_HIGH}))

    # 입력 주소와 등기부 주소가 다르면 위험 신호가 있어도 판단보류 (다른 집 등기부일 수 있음) [초안]
    address_mismatch_holds_grade: bool = True

    # 등급 하한: 이 신호가 있으면 등급이 안전이어도 이 등급까지 올린다 [초안, 팀 결정]
    #   다가구 등 비집합건물: 다른 세입자 보증금이 등기부에 없어 선순위가 실제보다 적을 수 있음 (#8)
    #   판단보류로 두면 다가구는 항상 판정이 안 나오므로 기본은 "최소 주의". "판단보류"로 바꿀 수도 있음
    grade_floor: dict = field(default_factory=lambda: {HIDDEN_SENIOR_CLAIM_CHECK_NEEDED: GRADE_CAUTION})


DEFAULT_CONFIG = RiskConfig()


def _pct(x: float) -> str:
    return f"{round(x * 100):g}%"


def jeonse_source(cfg: RiskConfig) -> str:
    return (f"국토교통부 실거래가 기반 전세가율 보증금/추정 시세, {_pct(cfg.jeonse_caution)} 이상 주의 / "
            f"{_pct(cfg.jeonse_danger)} 초과 위험 (팀 구간제 초안)")


def senior_source(cfg: RiskConfig) -> str:
    # docs/examples/analysis-result-ok.json 문구와 같음. 출처 문구 변경은 risk-rules.md 팀 안건 6번
    return (f"HUG 전세보증금반환보증 기준 (선순위+보증금)/주택가격, {_pct(cfg.senior_caution)} 이상 주의 / "
            f"{_pct(cfg.senior_danger)} 초과 위험 (팀 구간제 초안)")
