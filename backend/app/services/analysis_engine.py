"""document/ 분석 모듈을 순서대로 불러 팀 분석 결과 하나를 만듭니다.

주소 → 등기부 → 시세(등기부의 선순위 금액, 전용면적 사용) → 특약 → 위험 등급
각 모듈은 실패해도 예외 대신 실패 상태를 돌려주므로, 여기서는 순서와 값 전달만 맡습니다.
"""

import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class AnalysisInput:
    address: str
    property_type: str  # 아파트 / 오피스텔 / 연립다세대
    deposit: int  # 원
    area_m2: float | None = None  # 없으면 등기부의 전용면적을 씀
    dong_nm: str | None = None
    ho_nm: str | None = None
    registry_files: list[bytes] = field(default_factory=list)  # PDF 하나 또는 사진 여러 장(쪽 순서대로)
    contract_files: list[bytes] = field(default_factory=list)


@dataclass
class AnalysisOutput:
    result: dict
    notes: list[str]


@dataclass
class AnalysisEngine:
    resolve_address: Callable[..., dict]
    to_price_args: Callable[[dict], dict]
    analyze_price: Callable[..., dict]
    analyze_registry: Callable[..., dict]
    build_analysis_result: Callable[..., dict]
    normalize_type: Callable[[str], str]
    analyze_contract: Callable[..., dict]
    enrich_report: Callable[[dict], dict] | None = None

    @classmethod
    def from_document_modules(cls) -> "AnalysisEngine":
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        from ai.report_cards import enrich_analysis_result
        from document.address import resolve_address, to_price_args
        from document.price import analyze_price
        from document.price.rtms_client import normalize_type
        from document.registry import analyze_registry
        from document.risk import build_analysis_result

        from document.contract import analyze_contract

        return cls(
            resolve_address=resolve_address,
            to_price_args=to_price_args,
            analyze_price=analyze_price,
            analyze_registry=analyze_registry,
            build_analysis_result=build_analysis_result,
            normalize_type=normalize_type,
            analyze_contract=analyze_contract,
            enrich_report=enrich_analysis_result,
        )

    def check_property_type(self, property_type: str) -> None:
        """지원하지 않는 유형이면 ValueError."""
        self.normalize_type(property_type)

    def run(self, data: AnalysisInput, analysis_id: str) -> AnalysisOutput:
        notes: list[str] = []

        address = self.resolve_address(data.address, dong_nm=data.dong_nm, ho_nm=data.ho_nm)

        registry: dict | None = None
        if data.registry_files:
            registry = self.analyze_registry(_one_or_list(data.registry_files))
        else:
            notes.append("등기부가 없어 선순위 권리를 확인하지 않았습니다.")

        area = data.area_m2
        if area is None and registry and registry.get("data_status_item", {}).get("status") == "ok":
            area = (registry.get("property") or {}).get("exclusive_area_m2")
            if area is not None:
                notes.append(f"전용면적은 등기부 값({area}㎡)을 썼습니다.")

        price: dict | None = None
        if address.get("status") == "ok":
            if area:
                senior = registry.get("senior_amount_used") if registry else None
                price = self.analyze_price(
                    data.property_type,
                    area=float(area),
                    deposit=data.deposit,
                    senior_amount_used=senior,
                    **self.to_price_args(address["address"]),
                )
            else:
                notes.append("전용면적을 알 수 없어 시세를 계산하지 않았습니다. 면적을 입력하거나 등기부를 올려 주세요.")

        special_terms: dict | None = None
        if data.contract_files:
            special_terms = self.analyze_contract(_one_or_list(data.contract_files))

        result = self.build_analysis_result(
            address=address,
            price=price,
            registry=registry,
            special_terms=special_terms,
            analysis_id=analysis_id,
        )
        if self.enrich_report is not None:
            result = self.enrich_report(result)
        return AnalysisOutput(result=result, notes=notes)


def _one_or_list(files: list[bytes]) -> Any:
    """분석 모듈은 파일 하나면 그대로, 여러 장이면 쪽 순서대로 된 목록을 받습니다."""
    return files[0] if len(files) == 1 else files
