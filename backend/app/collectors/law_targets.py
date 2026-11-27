"""지식베이스에 모을 법령 목록. 법령을 추가하려면 여기에 한 줄 넣고 수집을 다시 돌립니다.

name은 국가법령정보센터의 정식 법령명과 정확히 같아야 합니다.
articles를 주면 그 조문 번호 범위만 모읍니다 (민법처럼 큰 법령에서 필요한 부분만).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class LawTarget:
    name: str
    reason: str
    articles: tuple[tuple[int, int], ...] | None = None  # (시작 조, 끝 조), 양 끝 포함


LAW_TARGETS: tuple[LawTarget, ...] = (
    LawTarget("주택임대차보호법", "대항력, 우선변제, 임대차기간, 계약갱신, 임대인 정보 제시 의무"),
    LawTarget("주택임대차보호법 시행령", "최우선변제 소액임차인 범위와 금액, 확정일자 정보 제공"),
    LawTarget(
        "민법",
        "전세권(제303-319조)과 임대차(제618-654조) 일반 규정",
        articles=((303, 319), (618, 654)),
    ),
    LawTarget("전세사기피해자 지원 및 주거안정에 관한 특별법", "전세사기 피해자 요건과 지원 절차"),
    LawTarget("공인중개사법", "중개대상물 확인·설명 의무, 중개사 책임"),
)
