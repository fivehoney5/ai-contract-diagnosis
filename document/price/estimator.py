"""매매 실거래가로 시세를 추정하고 전세가율을 계산한다.

추정 순서 (처음 성립하는 단계를 사용):
    1. same_building_similar_area : 같은 건물 + 비슷한 면적  -> 거래금액 중앙값 (1건 이상)
    2. same_building_any_area     : 같은 건물, 면적 무관     -> ㎡당 단가 중앙값 × 면적 (3건 이상)
    3. same_dong_similar_area     : 같은 동 + 비슷한 면적    -> 거래금액 중앙값 (3건 이상)
    4. same_dong_any_area         : 같은 동, 면적 무관       -> ㎡당 단가 중앙값 × 면적 (3건 이상)
    모두 실패하면 status="no_price"와 이유(reason_code, reason)를 돌려준다.

    같은 건물 거래가 0건이면
    - 신축(준공 3년 이내): 같은 동 거래로 대신 추정하지 않고
      reason_code="NO_BUILDING_TRADES", reason="신축 등으로 시세 확인 불가: ..."를 돌려준다.
    - 구축: 3·4단계(같은 동·비슷한 연식)로 추정한다.
    - 건축년도를 모르면: reason_code="BUILD_YEAR_UNKNOWN" (build_year를 넣으면 해결).

    3·4단계(같은 동)는 건축년도가 비슷한 거래(기본 ±5년)만 쓴다. 기준 건축년도는
    build_year로 직접 넣을 수 있고(나중에 건축물대장 연동), 없으면 같은 건물 거래의 건축년도를 쓴다.

    2~4단계는 다른 면적이나 다른 건물로 추정하는 단계라서, 거래 1~2건으로는 정하지 않는다
    (min_samples_weak, 기본 3건).

같은 건물 찾기:
    - 지번(예: "316", "236-8")을 넣으면 지번이 같은 거래
    - 건물명을 넣으면, 공백·괄호를 무시하고 이름이 정확히 같은 거래를 먼저 찾는다
    - 정확히 같은 이름이 없으면 부분 일치를 보는데, 건물이 딱 하나만 걸릴 때만 인정한다
    - 여러 건물이 걸리면(예: "강남" -> "강남역 쉐르빌", "강남역 와이즈 플레이스" ...)
      같은 건물 단계(1·2)는 건너뛰고 building_match="ambiguous"와 후보 이름을 결과에 남긴다

일괄거래 제외:
    API에 일괄거래 표시 필드가 없어서 다음 조건으로 추정해 시세 계산에서 뺀다.
    - 같은 동·같은 건물(건물명+지번)·같은 계약일 거래가 bulk_min_count(기본 3)건 이상이고
      그중 직거래이거나 매수·매도인 중 법인이 있는 거래가 하나라도 있는 경우 그 묶음 전체
    - 직거래이면서 매수인과 매도인이 모두 법인인 거래는 1건이어도 제외
      (여러 호실을 한 건으로 신고한 경우가 있어서. 예: 폴스타인 논현 38.33㎡ 20억)
    결과의 bulk_excluded_count(사용한 기준 범위 안에서 뺀 건수)와
    bulk_excluded_total(시군구 전체에서 뺀 건수)로 몇 건 뺐는지 알려준다.

신뢰도(confidence):
    - high   : 같은 건물·비슷한 면적 거래가 2건 이상 (신축은 3건 이상)
    - medium : 같은 건물 거래로 추정했지만 1번 조건에 못 미침 (㎡당 단가 환산),
               또는 준공 3년 이내 건물인데 같은 건물 거래가 1~2건
    - low    : 같은 동의 다른 건물 거래로 추정했거나, 근거 거래가 1건뿐 (신축 제외)

신축 부풀림 경고:
    준공 3년 이내 건물을 같은 건물 거래로 추정했으면(거래 수와 관계없이), ㎡당 가격 중앙값을
    같은 동·비슷한 면적(±10%)·비슷한 연식(±3년)(같은 건물 제외, 3건 이상) 거래의 ㎡당 중앙값과 비교한다.
    근거 거래가 모두 공공기관 매수면 비교하지 않는다. 기준(INFLATION_THRESHOLD)을 넘게 높으면
    warnings에 "PRICE_INFLATION_SUSPECTED", warning_messages에 "매매가 부풀림 의심: ..."을 넣는다.

공공기관 매수:
    매수자가 공공기관(LH 등)인 거래는 일괄거래 필터에서 빼지 않고 시세에 넣는다.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from statistics import median
from typing import Callable

from .building_register import (
    CHECK_VIOLATION,
    CHECK_VIOLATION_MESSAGE,
    BuildingInfo,
    BuildingRegisterError,
    fetch_building_info,
)
from .rtms_client import RTMSApiError, Trade, fetch_recent_trades, normalize_type, recent_months, type_label

BASIS_LABELS = {
    "same_building_similar_area": "같은 건물·비슷한 면적 거래 중앙값",
    "same_building_any_area": "같은 건물 ㎡당 단가 중앙값 × 전용면적",
    "same_dong_similar_area": "같은 동·비슷한 면적 거래 중앙값",
    "same_dong_any_area": "같은 동 ㎡당 단가 중앙값 × 전용면적",
}

CONFIDENCE_LABELS = {"high": "높음", "medium": "중간", "low": "낮음"}

# 같은 건물 찾기 결과
MATCH_JIBUN = "jibun"  # 지번으로 찾음
MATCH_EXACT = "exact"  # 건물명이 정확히 같음
MATCH_PARTIAL = "partial"  # 부분 일치, 건물 하나만 걸림
MATCH_AMBIGUOUS = "ambiguous"  # 부분 일치로 여러 건물이 걸림 -> 같은 건물 단계 건너뜀
MATCH_NOT_FOUND = "not_found"  # 같은 동에 해당 건물 거래가 없음

# 시세 없음 이유 코드
NO_TRADES_IN_REGION = "NO_TRADES_IN_REGION"
NO_TRADES_IN_DONG = "NO_TRADES_IN_DONG"
INSUFFICIENT_SAMPLES = "INSUFFICIENT_SAMPLES"
ONLY_BULK_TRADES = "ONLY_BULK_TRADES"
NO_BUILDING_TRADES = "NO_BUILDING_TRADES"  # 신축(3년 이내)인데 같은 건물 거래 0건 -> 리스크 점수 "주의"
BUILDING_NOT_IDENTIFIED = "BUILDING_NOT_IDENTIFIED"
BUILD_YEAR_UNKNOWN = "BUILD_YEAR_UNKNOWN"  # 같은 건물 거래 0건이고 건축년도도 몰라 신축 여부 판단 불가  # 건물명이 여러 건물에 걸리고 건축년도도 모름

PUBLIC_BUYER = "공공기관"
NEW_BUILDING_YEARS = 3  # 준공 후 이 햇수 이내면 신축으로 본다
INFLATION_THRESHOLD = 0.30  # 같은 동 비슷한 연식 시세보다 이만큼 넘게 높으면 경고
INFLATION_YEAR_TOL = 3  # 부풀림 비교에 쓰는 같은 동 거래의 건축년도 범위 (±년)
INFLATION_WARNING = "PRICE_INFLATION_SUSPECTED"

_JIBUN_RE = re.compile(r"^(산\s*)?\d+(-\d+)?$")


@dataclass
class PriceEstimate:
    status: str  # "estimated" | "no_price"
    price: int | None  # 추정 시세(원)
    basis: str | None  # 추정 기준 코드 (BASIS_LABELS 키)
    basis_label: str | None
    reason_code: str | None  # status="no_price"일 때만
    reason: str | None
    sample_count: int
    period_start: str
    period_end: str
    samples: list[Trade] = field(default_factory=list)
    bulk_excluded_count: int = 0  # 사용한 기준 범위(시세 없음이면 해당 동) 안에서 뺀 일괄거래 건수
    bulk_excluded_total: int = 0  # 시군구 전체에서 뺀 일괄거래 건수
    confidence: str | None = None  # "high" | "medium" | "low" (시세 없음이면 None)
    building_match: str | None = None  # MATCH_* 중 하나
    building_candidates: list[str] = field(default_factory=list)  # 애매할 때 걸린 건물 이름들
    notes: list[str] = field(default_factory=list)  # 사람이 읽을 참고 문구
    build_year: int | None = None  # 같은 동 거래를 고를 때 쓴 기준 건축년도
    is_new_building: bool = False  # 준공 NEW_BUILDING_YEARS년 이내
    warnings: list[str] = field(default_factory=list)  # 경고 코드 (예: PRICE_INFLATION_SUSPECTED)
    warning_messages: list[str] = field(default_factory=list)
    dong_reference_price: int | None = None  # 비교용: 같은 동·비슷한 면적·비슷한 연식 중앙값 (같은 건물 제외)
    dong_reference_count: int = 0
    price_per_m2: int | None = None  # 부풀림 비교에 쓴 이 건물 ㎡당 가격(원)
    dong_reference_price_per_m2: int | None = None  # 비교 대상 ㎡당 중앙값(원)
    building_info: BuildingInfo | None = None  # 건축물대장 조회 결과 (bjdong_cd를 넣었을 때)
    build_year_source: str | None = None  # "input" | "building_register" | "trades"

    @property
    def building_flags(self) -> list[str]:
        """건물 영역 리스크 플래그 (NON_RESIDENTIAL 등). 건축물대장을 조회하지 않았으면 빈 목록."""
        return list(self.building_info.flags) if self.building_info else []

    @property
    def checks_needed(self) -> list[str]:
        """사람이 확인해야 할 항목. 위반건축물 여부는 API로 알 수 없어 항상 들어간다."""
        return list(self.building_info.checks_needed) if self.building_info else [CHECK_VIOLATION]

    @property
    def check_messages(self) -> list[str]:
        return [CHECK_VIOLATION_MESSAGE for c in self.checks_needed if c == CHECK_VIOLATION]

    @property
    def confidence_label(self) -> str | None:
        return CONFIDENCE_LABELS.get(self.confidence) if self.confidence else None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "price": self.price,
            "basis": self.basis,
            "basis_label": self.basis_label,
            "confidence": self.confidence,
            "confidence_label": self.confidence_label,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "sample_count": self.sample_count,
            "bulk_excluded_count": self.bulk_excluded_count,
            "bulk_excluded_total": self.bulk_excluded_total,
            "building_match": self.building_match,
            "building_candidates": self.building_candidates,
            "notes": self.notes,
            "build_year": self.build_year,
            "is_new_building": self.is_new_building,
            "warnings": self.warnings,
            "warning_messages": self.warning_messages,
            "dong_reference_price": self.dong_reference_price,
            "dong_reference_count": self.dong_reference_count,
            "building_info": self.building_info.to_dict() if self.building_info else None,
            "building_flags": self.building_flags,
            "checks_needed": self.checks_needed,
            "check_messages": self.check_messages,
            "build_year_source": self.build_year_source,
            "price_per_m2": self.price_per_m2,
            "dong_reference_price_per_m2": self.dong_reference_price_per_m2,
            "period": {"start": self.period_start, "end": self.period_end},
            "samples": [t.to_dict() for t in self.samples],
        }


def _norm(s: str) -> str:
    return re.sub(r"[\s()\[\]·.,\-]", "", s).lower()


def _norm_jibun(s: str) -> str:
    return re.sub(r"\s", "", s)


def is_jibun(text: str) -> bool:
    return bool(_JIBUN_RE.match(text.strip()))


def same_dong(trade_dong: str, dong: str) -> bool:
    a, b = _norm(trade_dong), _norm(dong)
    return a == b or a.removesuffix("동") == b.removesuffix("동")


def same_building(trade: Trade, building: str) -> bool:
    """건물명 또는 지번이 일치하는지 (거래 한 건 기준, 부분 일치 허용).

    시세 추정에서는 여러 건물이 섞이지 않도록 find_building_trades를 쓴다.
    """
    building = building.strip()
    if not building:
        return False
    if is_jibun(building):
        return _norm_jibun(trade.jibun) == _norm_jibun(building)
    q, name = _norm(building), _norm(trade.building_name)
    if not name or len(q) < 2:
        return False
    return q == name or q in name or name in q


def _building_key(t: Trade) -> tuple[str, str]:
    return _norm(t.building_name), _norm_jibun(t.jibun)


def find_building_trades(trades: list[Trade], building: str) -> tuple[list[Trade], str, list[str]]:
    """같은 동 거래 중 입력한 건물의 거래를 찾는다.

    돌려주는 값: (그 건물 거래 목록, 찾은 방식 MATCH_*, 애매할 때 후보 건물 이름들)
    """
    building = building.strip()
    if not building:
        return [], MATCH_NOT_FOUND, []
    if is_jibun(building):
        found = [t for t in trades if _norm_jibun(t.jibun) == _norm_jibun(building)]
        return found, (MATCH_JIBUN if found else MATCH_NOT_FOUND), []

    q = _norm(building)
    def candidates(found: list[Trade]) -> list[str]:
        names: list[str] = []
        for t in found:
            label = f"{t.building_name} (지번 {t.jibun}" + (f", {t.build_year}년" if t.build_year else "") + ")"
            if label not in names:
                names.append(label)
        return names

    exact = [t for t in trades if _norm(t.building_name) == q and q]
    if exact:
        # 빌라는 같은 이름의 다른 건물(지번이 다름)이 흔하다. 예: 화곡동 '위하우스' 163-7(2026년), 355-14(2015년)
        if len({_norm_jibun(t.jibun) for t in exact}) > 1:
            return [], MATCH_AMBIGUOUS, candidates(exact)
        return exact, MATCH_EXACT, []

    partial = [t for t in trades if same_building(t, building)]
    keys = {_building_key(t) for t in partial}
    if len(keys) == 1:
        return partial, MATCH_PARTIAL, []
    if len(keys) > 1:
        return [], MATCH_AMBIGUOUS, candidates(partial)
    return [], MATCH_NOT_FOUND, []


def _similar_area(trade: Trade, area: float, tol: float) -> bool:
    return abs(trade.area - area) / area <= tol


def _bulk_like(trade: Trade) -> bool:
    return trade.dealing_gbn == "직거래" or "법인" in (trade.buyer_gbn, trade.seller_gbn)


def _corp_to_corp_direct(trade: Trade) -> bool:
    return trade.dealing_gbn == "직거래" and trade.buyer_gbn == "법인" and trade.seller_gbn == "법인"


def split_bulk_trades(trades: list[Trade], min_count: int | None = 3) -> tuple[list[Trade], list[Trade]]:
    """(일반 거래, 일괄거래로 판단한 거래)로 나눈다. min_count가 None/0이면 나누지 않는다."""
    if not min_count:
        return list(trades), []
    groups: dict[tuple, list[Trade]] = defaultdict(list)
    normal: list[Trade] = []
    bulk: list[Trade] = []
    for t in trades:
        if t.buyer_gbn == PUBLIC_BUYER:  # LH 등 공공기관 매입은 일괄거래로 빼지 않고 시세에 넣는다
            normal.append(t)
            continue
        groups[(_norm(t.dong), _norm(t.building_name), _norm_jibun(t.jibun), t.deal_date)].append(t)
    for group in groups.values():
        if len(group) >= min_count and any(_bulk_like(t) for t in group):
            bulk.extend(group)
            continue
        for t in group:
            (bulk if _corp_to_corp_direct(t) else normal).append(t)
    return normal, bulk


def _confidence(basis: str, sample_count: int, is_new: bool = False) -> str:
    if is_new and basis.startswith("same_building") and sample_count < 3:
        return "medium"  # 신축은 거래가 적은 게 자연스러워서 1~2건이어도 "중간"
    if sample_count <= 1 or basis.startswith("same_dong"):
        return "low"
    if basis == "same_building_similar_area":
        return "high"
    return "medium"


def estimate_from_trades(
    trades: list[Trade],
    dong: str,
    building: str,
    area: float,
    *,
    building_area_tol: float = 0.05,
    dong_area_tol: float = 0.10,
    min_samples: int = 1,
    min_samples_weak: int = 3,
    build_year: int | None = None,
    build_year_tol: int = 5,
    inflation_year_tol: int = INFLATION_YEAR_TOL,
    inflation_threshold: float = INFLATION_THRESHOLD,
    bulk_min_count: int | None = 3,
    period: tuple[str, str] = ("", ""),
    region_desc: str = "조회 지역",
) -> PriceEstimate:
    """이미 받아온 거래 목록으로 시세를 추정한다 (네트워크 호출 없음).

    min_samples      : 1단계(같은 건물·비슷한 면적)에 필요한 최소 거래 수
    min_samples_weak : 2~4단계(㎡당 단가 환산, 같은 동)에 필요한 최소 거래 수
    build_year       : 대상 건물 건축년도 (없으면 같은 건물 거래에서 가져옴)
    build_year_tol   : 같은 동 단계에서 허용하는 건축년도 차이 (년)
    inflation_year_tol, inflation_threshold : 신축 부풀림 비교의 건축년도 범위와 경고 기준
    """
    if area <= 0:
        raise ValueError(f"전용면적은 0보다 커야 합니다: {area}")
    if min_samples < 1:
        raise ValueError("min_samples는 1 이상이어야 합니다")
    weak_min = max(min_samples, min_samples_weak)

    start, end = period
    trades, bulk = split_bulk_trades(trades, bulk_min_count)
    bulk_in_dong = [t for t in bulk if same_dong(t.dong, dong)]

    def no_price(code: str, reason: str, **extra) -> PriceEstimate:
        return PriceEstimate(
            "no_price", None, None, None, code, reason, 0, start, end,
            bulk_excluded_count=len(bulk_in_dong), bulk_excluded_total=len(bulk), **extra,
        )

    in_dong = [t for t in trades if same_dong(t.dong, dong)]
    if not in_dong and bulk_in_dong:
        return no_price(
            ONLY_BULK_TRADES,
            f"'{dong}' 거래 {len(bulk_in_dong)}건이 모두 일괄거래로 판단돼 제외됐습니다 "
            "(같은 건물·같은 계약일 다건이면서 직거래 또는 법인 거래, 또는 법인끼리 직거래).",
        )

    if not trades:
        bulk_note = f" (일괄거래로 판단한 {len(bulk)}건 제외)" if bulk else ""
        return no_price(
            NO_TRADES_IN_REGION,
            f"{region_desc}에 조회 기간({start} ~ {end}) 동안 매매 거래가 없습니다{bulk_note}.",
        )

    if not in_dong:
        return no_price(
            NO_TRADES_IN_DONG,
            f"{region_desc} 거래 {len(trades)}건 중 '{dong}' 거래가 없습니다. "
            "동 이름이 법정동 기준인지 확인하세요 (행정동 '역삼1동'이 아니라 법정동 '역삼동').",
        )

    # 어느 건물인지는 일괄거래로 뺀 거래까지 포함해서 정한다.
    # (신축 빌라는 분양·매입임대 거래가 일괄거래로 빠지는 경우가 많아서, 빼고 찾으면
    #  같은 이름의 오래된 다른 건물로 잘못 잡힐 수 있다)
    normal_ids = {id(t) for t in in_dong}
    bld_all, match, candidates = find_building_trades(in_dong + bulk_in_dong, building)
    bld_trades = [t for t in bld_all if id(t) in normal_ids]
    notes: list[str] = []

    # 기준 건축년도: 직접 넣은 값이 우선, 없으면 같은 건물 거래(일괄거래로 뺀 것 포함)의 건축년도
    target_year = build_year
    if target_year is None:
        years = [t.build_year for t in bld_all if t.build_year]
        target_year = int(median(years)) if years else None
    ref_year = int(end[:4]) if end[:4].isdigit() else date.today().year
    is_new = target_year is not None and ref_year - target_year <= NEW_BUILDING_YEARS

    # 같은 건물 거래가 0건일 때
    #   - 신축(준공 3년 이내)  -> 시세 확인 불가 (NO_BUILDING_TRADES)
    #   - 구축                 -> 아래 3·4단계(같은 동·비슷한 연식)로 추정
    #   - 건축년도 모름        -> 신축인지 알 수 없어 확인 불가 (BUILD_YEAR_UNKNOWN)
    if match == MATCH_NOT_FOUND or (match != MATCH_AMBIGUOUS and not bld_trades):
        if bld_all:
            why = f"'{building}' 거래 {len(bld_all)}건이 모두 일괄거래로 판단돼 제외됐습니다"
        elif building.strip():
            why = f"조회 기간({start} ~ {end}) 동안 '{dong}'에 '{building}' 매매 거래가 없습니다"
        else:
            why = "건물명이나 지번이 입력되지 않았습니다"
        if target_year is None:
            return no_price(
                BUILD_YEAR_UNKNOWN,
                f"시세 확인 불가: {why}. 건축년도도 몰라서 신축인지 판단할 수 없습니다 "
                "(build_year에 건축물대장의 건축년도를 넣으면 다시 추정할 수 있습니다).",
                building_match=match,
            )
        if is_new:
            return no_price(
                NO_BUILDING_TRADES,
                f"신축 등으로 시세 확인 불가: {why}. 준공 {NEW_BUILDING_YEARS}년 이내({target_year}년) 건물이라 "
                "같은 동 거래로 대신 추정하지 않습니다.",
                building_match=match,
                build_year=target_year,
                is_new_building=True,
            )
        notes.append(f"{why}. 같은 동 비슷한 연식({target_year}±{build_year_tol}년) 거래로 추정했습니다.")

    if match == MATCH_AMBIGUOUS:
        notes.append(
            f"건물명 '{building}'에 해당하는 건물이 {len(candidates)}곳이라 같은 건물 기준은 쓰지 않았습니다. "
            "정확한 건물명이나 지번을 넣으면 더 정확해집니다."
        )
        if target_year is None:
            return no_price(
                BUILDING_NOT_IDENTIFIED,
                f"건물명 '{building}'에 해당하는 건물이 {len(candidates)}곳이라 어느 건물인지 알 수 없고, "
                "건축년도도 몰라서 같은 동 거래로 추정할 수 없습니다. 정확한 건물명이나 지번을 넣으세요.",
                building_match=match,
                building_candidates=candidates,
                notes=notes,
            )

    def similar_year(t: Trade) -> bool:
        if target_year is None:
            return False
        return t.build_year is not None and abs(t.build_year - target_year) <= build_year_tol

    bld_ids = {id(t) for t in bld_trades}
    bld_all_ids = {id(t) for t in bld_all}

    def building_sim(t: Trade) -> bool:
        return id(t) in bld_ids and _similar_area(t, area, building_area_tol)

    def in_bld(t: Trade) -> bool:
        return id(t) in bld_ids

    def dong_sim(t: Trade) -> bool:
        return similar_year(t) and _similar_area(t, area, dong_area_tol)

    def any_trade(t: Trade) -> bool:
        return similar_year(t)

    # (기준, 거래 조건, ㎡당 단가 사용 여부, 최소 거래 수)
    tiers = [
        ("same_building_similar_area", building_sim, False, min_samples),
        ("same_building_any_area", in_bld, True, weak_min),
        ("same_dong_similar_area", dong_sim, False, weak_min),
        ("same_dong_any_area", any_trade, True, weak_min),
    ]

    # 일괄거래 건수를 셀 때 쓰는 같은 건물 판단 (제외된 거래는 bld_trades에 없으므로 따로)
    def bulk_in_tier(cond_name: str, t: Trade) -> bool:
        if cond_name.startswith("same_building"):
            if id(t) not in bld_all_ids:
                return False
            return cond_name == "same_building_any_area" or _similar_area(t, area, building_area_tol)
        if cond_name == "same_dong_similar_area":
            return similar_year(t) and _similar_area(t, area, dong_area_tol)
        return similar_year(t)

    if target_year is None and match != MATCH_AMBIGUOUS:
        notes.append("대상 건물의 건축년도를 몰라 같은 동 거래로는 추정하지 않았습니다.")

    for basis, cond, per_m2, need in tiers:
        pool = [t for t in in_dong if cond(t)]
        if len(pool) < need:
            if pool and basis == "same_building_any_area":
                notes.append(
                    f"같은 건물 거래가 {len(pool)}건뿐이라 면적이 다른 거래로 환산하지 않았습니다 (최소 {need}건)."
                )
            continue
        if per_m2:
            price = round(median(t.price_per_m2 for t in pool) * area)
        else:
            price = round(median(t.price for t in pool))
        conf = _confidence(basis, len(pool), is_new)
        if len(pool) == 1 and not is_new:
            notes.append("근거 거래가 1건뿐이라 결과를 그대로 믿기 어렵습니다.")

        # 신축이면 같은 건물 거래 수와 관계없이 같은 동 비슷한 면적·연식 시세와 ㎡당 가격으로 비교
        warnings: list[str] = []
        warning_messages: list[str] = []
        ref_price, ref_count, ref_unit, own_unit = None, 0, None, None
        if is_new and basis.startswith("same_building"):
            if all(t.buyer_gbn == PUBLIC_BUYER for t in pool):
                notes.append("근거 거래가 모두 공공기관 매수라 부풀림 비교는 하지 않았습니다.")
            else:
                ref_pool = [
                    t for t in in_dong
                    if id(t) not in bld_all_ids
                    and _similar_area(t, area, dong_area_tol)
                    and t.build_year is not None
                    and abs(t.build_year - target_year) <= inflation_year_tol
                ]
                ref_count = len(ref_pool)
                if ref_count >= weak_min:
                    own_unit = median(t.price_per_m2 for t in pool)
                    ref_unit = median(t.price_per_m2 for t in ref_pool)
                    ref_price = int(round(ref_unit * area))
                    diff = own_unit / ref_unit - 1
                    if diff > inflation_threshold:
                        warnings.append(INFLATION_WARNING)
                        warning_messages.append(
                            f"매매가 부풀림 의심: 신축 건물 거래 {len(pool)}건의 ㎡당 가격 {own_unit:,.0f}원이 "
                            f"같은 동 비슷한 면적·연식({target_year}±{inflation_year_tol}년) 거래 {ref_count}건의 "
                            f"㎡당 중앙값 {ref_unit:,.0f}원보다 {diff * 100:.0f}% 높습니다."
                        )
                else:
                    notes.append(
                        f"비교할 같은 동 비슷한 면적·연식({target_year}±{inflation_year_tol}년) 거래가 "
                        f"{ref_count}건이라 부풀림 여부는 확인하지 못했습니다 (최소 {weak_min}건)."
                    )
        return PriceEstimate(
            status="estimated",
            price=int(price),
            basis=basis,
            basis_label=BASIS_LABELS[basis],
            reason_code=None,
            reason=None,
            sample_count=len(pool),
            period_start=start,
            period_end=end,
            samples=sorted(pool, key=lambda t: t.deal_date, reverse=True),
            bulk_excluded_count=sum(1 for t in bulk_in_dong if bulk_in_tier(basis, t)),
            bulk_excluded_total=len(bulk),
            confidence=conf,
            building_match=match,
            building_candidates=candidates,
            notes=notes,
            build_year=target_year,
            is_new_building=is_new,
            warnings=warnings,
            warning_messages=warning_messages,
            dong_reference_price=ref_price,
            dong_reference_count=ref_count,
            price_per_m2=None if own_unit is None else int(round(own_unit)),
            dong_reference_price_per_m2=None if ref_unit is None else int(round(ref_unit)),
        )

    return no_price(
        INSUFFICIENT_SAMPLES,
        f"'{dong}' 거래가 {len(in_dong)}건이라 추정에 쓸 거래가 부족합니다 "
        f"(같은 건물·비슷한 면적 {min_samples}건 이상, 그 외 기준은 {weak_min}건 이상 필요"
        + (f", 같은 동은 건축년도 {target_year}±{build_year_tol}년 거래만 사용" if target_year else "")
        + ").",
        building_match=match,
        building_candidates=candidates,
        notes=notes,
        build_year=target_year,
    )


def _period(months: int, today: date) -> tuple[str, str]:
    oldest = recent_months(months, today)[-1]
    return f"{oldest[:4]}-{oldest[4:]}-01", today.isoformat()


def estimate_price(
    property_type: str,
    lawd_cd: str,
    dong: str,
    building: str,
    area: float,
    *,
    months: int = 12,
    today: date | None = None,
    trades: list[Trade] | None = None,
    fetcher: Callable[..., list[Trade]] = fetch_recent_trades,
    bjdong_cd: str | None = None,
    jibun: str | None = None,
    dong_nm: str | None = None,
    ho_nm: str | None = None,
    building_fetcher: Callable[..., BuildingInfo] = fetch_building_info,
    **kwargs,
) -> PriceEstimate:
    """최근 N개월 매매 거래를 조회해 시세를 추정한다.

    trades를 넘기면 API를 호출하지 않고 그 목록을 쓴다 (테스트용).
    bjdong_cd(10자리 법정동코드, 예: '1150010300')를 넣으면 건축물대장도 조회해서
      - build_year가 없을 때 사용승인 연도로 채우고
      - 주용도가 주거용이 아니면 building_flags에 NON_RESIDENTIAL을 남긴다.
      지번은 jibun → building이 지번이면 그것 → 같은 건물 거래의 지번(하나일 때) 순으로 쓴다.
      dong_nm·ho_nm(예: 'A동', '401')을 넣으면 그 호의 전유부 용도도 확인한다.
    kwargs는 estimate_from_trades의 옵션
    (building_area_tol, dong_area_tol, min_samples, min_samples_weak, build_year, build_year_tol,
     inflation_year_tol, inflation_threshold, bulk_min_count).
    """
    ptype = normalize_type(property_type)
    today = today or date.today()
    if trades is None:
        trades = fetcher(ptype, lawd_cd, months=months, today=today)

    info: BuildingInfo | None = None
    register_note: str | None = None
    if bjdong_cd:
        jb = (jibun or "").strip() or (building.strip() if is_jibun(building) else "")
        if not jb:
            found, _, _ = find_building_trades([t for t in trades if same_dong(t.dong, dong)], building)
            jibuns = {_norm_jibun(t.jibun) for t in found if t.jibun}
            if len(jibuns) == 1:
                jb = found[0].jibun
            else:
                register_note = (
                    "지번을 알 수 없어 건축물대장을 조회하지 못했습니다 (jibun을 넣어 주세요)."
                    if not jibuns else
                    f"같은 이름 건물의 지번이 {len(jibuns)}개라 건축물대장을 조회하지 못했습니다 (jibun을 넣어 주세요)."
                )
        if jb:
            try:
                info = building_fetcher(bjdong_cd, jb, sigungu_cd=lawd_cd, dong_nm=dong_nm, ho_nm=ho_nm)
            except (BuildingRegisterError, RTMSApiError, ValueError) as e:
                register_note = f"건축물대장 조회 실패: {e}"

    source = "input" if kwargs.get("build_year") is not None else None
    if source is None and info and info.build_year:
        kwargs["build_year"] = info.build_year
        source = "building_register"

    est = estimate_from_trades(
        trades,
        dong,
        building,
        area,
        period=_period(months, today),
        region_desc=f"시군구 {lawd_cd}의 {type_label(ptype)}",
        **kwargs,
    )
    est.building_info = info
    est.build_year_source = source or ("trades" if est.build_year else None)
    if register_note:
        est.notes.append(register_note)
    if info:
        est.notes.extend(n for n in info.notes if n not in est.notes and n != CHECK_VIOLATION_MESSAGE)
    return est


def calc_jeonse_ratio(deposit: int | float, price: int | float | None) -> float | None:
    """전세가율 = 보증금 ÷ 시세. 시세가 없거나 0 이하면 None."""
    if price is None or price <= 0:
        return None
    return deposit / price


def assess_jeonse(
    property_type: str,
    lawd_cd: str,
    dong: str,
    building: str,
    area: float,
    deposit: int,
    **kwargs,
) -> dict:
    """시세를 추정하고 보증금(원)으로 전세가율을 계산한다. 전세가율은 0-1 소수."""
    if deposit <= 0:
        raise ValueError(f"보증금은 0보다 커야 합니다: {deposit}")
    est = estimate_price(property_type, lawd_cd, dong, building, area, **kwargs)
    ratio = calc_jeonse_ratio(deposit, est.price)
    return {
        "status": est.status,
        "deposit": deposit,
        "estimated_price": est.price,
        "jeonse_ratio": None if ratio is None else round(ratio, 4),
        "basis": est.basis,
        "basis_label": est.basis_label,
        "confidence": est.confidence,
        "confidence_label": est.confidence_label,
        "reason_code": est.reason_code,
        "reason": est.reason,
        "sample_count": est.sample_count,
        "bulk_excluded_count": est.bulk_excluded_count,
        "bulk_excluded_total": est.bulk_excluded_total,
        "notes": est.notes,
        "building_flags": est.building_flags,
        "checks_needed": est.checks_needed,
        "check_messages": est.check_messages,
        "is_new_building": est.is_new_building,
        "warnings": est.warnings,
        "warning_messages": est.warning_messages,
        "estimate": est.to_dict(),
    }
