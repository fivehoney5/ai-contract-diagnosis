"""위험 등급 모듈. 부분 결과를 합쳐 등급·신호·데이터 상태를 만든다. 사용법은 README.md 참고."""

from .config import DEFAULT_CONFIG, RiskConfig
from .grader import (
    band_level,
    build_analysis_result,
    cap_low_confidence,
    decide_grade,
    merge_flags,
    ratio_flags,
    special_terms_part,
)

__all__ = [
    "DEFAULT_CONFIG",
    "RiskConfig",
    "band_level",
    "build_analysis_result",
    "cap_low_confidence",
    "decide_grade",
    "merge_flags",
    "ratio_flags",
    "special_terms_part",
]
