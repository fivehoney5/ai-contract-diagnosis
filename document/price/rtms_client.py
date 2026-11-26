"""국토교통부 매매 실거래가 API(공공데이터포털) 클라이언트.

지원 유형:
    - 아파트       : RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade
    - 오피스텔     : RTMSDataSvcOffiTrade/getRTMSDataSvcOffiTrade
    - 연립다세대   : RTMSDataSvcRHTrade2/getRTMSDataSvcRHTrade2 (houseType: 연립/다세대)
"""

from __future__ import annotations

import os
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from datetime import date
from typing import Iterable

import requests
from dotenv import load_dotenv

BASE_URL = "https://apis.data.go.kr/1613000"

# 유형 코드 -> (엔드포인트 경로, 건물명 필드, 표시 이름)
ENDPOINTS: dict[str, tuple[str, str, str]] = {
    "apt": ("RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade", "aptNm", "아파트"),
    "officetel": ("RTMSDataSvcOffiTrade/getRTMSDataSvcOffiTrade", "offiNm", "오피스텔"),
    "rowhouse": ("RTMSDataSvcRHTrade2/getRTMSDataSvcRHTrade2", "mhouseNm", "연립다세대"),
}

# 한글 별칭도 허용
TYPE_ALIASES = {
    "아파트": "apt",
    "오피스텔": "officetel",
    "연립다세대": "rowhouse",
    "연립": "rowhouse",
    "다세대": "rowhouse",
    "빌라": "rowhouse",
}

SUCCESS_CODES = {"00", "000"}
MANWON = 10_000  # API 거래금액은 만원 단위라서 원으로 바꿀 때 곱하는 값
PAGE_SIZE = 1000
RETRIES = 1  # 실패하면 한 번 더 시도
RETRY_WAIT = 1.0  # 다시 시도하기 전 기다리는 시간(초)


class RTMSApiError(RuntimeError):
    """API가 오류 코드를 돌려줬거나 응답을 해석할 수 없을 때."""


@dataclass(frozen=True)
class Trade:
    property_type: str  # apt / officetel / rowhouse
    building_name: str
    dong: str  # 법정동 이름 (umdNm)
    jibun: str
    area: float  # 전용면적(㎡)
    price: int  # 거래금액(원)
    deal_date: date
    floor: str
    house_type: str = ""  # 연립다세대만: "연립" / "다세대" (houseType)
    dealing_gbn: str = ""  # 거래유형: "중개거래" / "직거래" (dealingGbn)
    buyer_gbn: str = ""  # 매수자: "개인" / "법인" / ... (buyerGbn)
    seller_gbn: str = ""  # 매도자: "개인" / "법인" / ... (slerGbn)
    build_year: int | None = None  # 건축년도 (buildYear), 비어 있으면 None

    @property
    def price_per_m2(self) -> float:
        """㎡당 가격(원)."""
        return self.price / self.area

    def to_dict(self) -> dict:
        d = asdict(self)
        d["deal_date"] = self.deal_date.isoformat()
        return d


def normalize_type(property_type: str) -> str:
    key = TYPE_ALIASES.get(property_type.strip(), property_type.strip().lower())
    if key not in ENDPOINTS:
        raise ValueError(
            f"지원하지 않는 유형: {property_type!r} (apt/officetel/rowhouse 또는 아파트/오피스텔/연립다세대)"
        )
    return key


def type_label(property_type: str) -> str:
    return ENDPOINTS[normalize_type(property_type)][2]


def parse_amount(value: str | None) -> int:
    """API의 '63,400' 같은 만원 단위 문자열을 원 단위 정수로 바꾼다 (63,400만원 -> 634,000,000원)."""
    if value is None:
        raise ValueError("거래금액이 비어 있습니다")
    cleaned = value.replace(",", "").strip()
    if not cleaned:
        raise ValueError("거래금액이 비어 있습니다")
    return int(cleaned) * MANWON


def load_service_key() -> str:
    load_dotenv()
    key = os.getenv("PUBLIC_DATA_API_KEY", "").strip()
    if not key:
        raise RuntimeError(".env에 PUBLIC_DATA_API_KEY가 없습니다 (공공데이터포털 Decoding 키를 넣으세요)")
    return key


def _text(item: ET.Element, tag: str) -> str:
    el = item.find(tag)
    return (el.text or "").strip() if el is not None else ""


def _year(text: str) -> int | None:
    return int(text) if text.isdigit() and len(text) == 4 else None


def parse_response(xml_text: str, property_type: str) -> tuple[list[Trade], int]:
    """XML 응답을 (거래 목록, totalCount)로 바꾼다. 해제된 거래는 제외한다."""
    ptype = normalize_type(property_type)
    name_field = ENDPOINTS[ptype][1]

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise RTMSApiError(f"XML 응답을 해석할 수 없습니다: {xml_text[:200]!r}") from e

    # 게이트웨이 오류 형식 (인증키 오류 등)
    if root.tag == "OpenAPI_ServiceResponse":
        err = (root.findtext(".//errMsg") or "").strip()
        auth = (root.findtext(".//returnAuthMsg") or "").strip()
        code = (root.findtext(".//returnReasonCode") or "?").strip()
        msg = " / ".join(x for x in (err, auth) if x) or "알 수 없는 오류"
        if "SERVICE_KEY_IS_NOT_REGISTERED" in msg:
            msg += " — 공공데이터포털에서 이 API의 활용신청이 승인됐는지 확인하세요 (API별로 따로 신청, 승인 후 반영까지 시간이 걸릴 수 있음)"
        raise RTMSApiError(f"API 오류 [{code}] {msg}")

    code = (root.findtext("./header/resultCode") or "").strip()
    if code not in SUCCESS_CODES:
        msg = root.findtext("./header/resultMsg") or ""
        raise RTMSApiError(f"API 오류 [{code}] {msg}")

    total = int((root.findtext("./body/totalCount") or "0").strip() or 0)

    trades: list[Trade] = []
    for item in root.iterfind("./body/items/item"):
        if _text(item, "cdealType") == "O":  # 해제된 거래
            continue
        try:
            trades.append(
                Trade(
                    property_type=ptype,
                    building_name=_text(item, name_field),
                    dong=_text(item, "umdNm"),
                    jibun=_text(item, "jibun"),
                    area=float(_text(item, "excluUseAr")),
                    price=parse_amount(_text(item, "dealAmount")),
                    deal_date=date(
                        int(_text(item, "dealYear")),
                        int(_text(item, "dealMonth")),
                        int(_text(item, "dealDay")),
                    ),
                    floor=_text(item, "floor"),
                    house_type=_text(item, "houseType"),
                    dealing_gbn=_text(item, "dealingGbn"),
                    buyer_gbn=_text(item, "buyerGbn"),
                    seller_gbn=_text(item, "slerGbn"),
                    build_year=_year(_text(item, "buildYear")),
                )
            )
        except ValueError:
            # 면적·금액·날짜가 깨진 행은 건너뛴다
            continue
    return trades, total


def _get_with_retry(http, url: str, params: dict, timeout: float, what: str):
    """요청이 네트워크 오류나 서버 오류(5xx)로 실패하면 RETRIES번 더 시도한다."""
    last_error = ""
    for attempt in range(RETRIES + 1):
        if attempt:
            time.sleep(RETRY_WAIT)
        try:
            resp = http.get(url, params=params, timeout=timeout)
        except requests.Timeout:
            last_error = f"{timeout:g}초 안에 응답이 없었습니다"
            continue
        except requests.RequestException as e:
            last_error = f"인터넷 연결 또는 서버 연결에 실패했습니다 ({e.__class__.__name__})"
            continue
        if resp.status_code >= 500 and attempt < RETRIES:
            continue  # 마지막 시도면 응답을 그대로 돌려줘서 오류 내용을 보여준다
        return resp
    raise RTMSApiError(
        f"{what} 조회 실패: {last_error}. {RETRIES + 1}번 시도했습니다. 잠시 후 다시 실행해 보세요."
    )


def fetch_trades(
    property_type: str,
    lawd_cd: str,
    deal_ymd: str,
    service_key: str | None = None,
    session: requests.Session | None = None,
    timeout: float = 10.0,
) -> list[Trade]:
    """한 달(deal_ymd='YYYYMM')치 거래를 모든 페이지에 걸쳐 가져온다."""
    ptype = normalize_type(property_type)
    if not (len(lawd_cd) == 5 and lawd_cd.isdigit()):
        raise ValueError(f"법정동코드 앞 5자리가 아닙니다: {lawd_cd!r}")
    key = service_key or load_service_key()
    http = session or requests.Session()
    url = f"{BASE_URL}/{ENDPOINTS[ptype][0]}"

    results: list[Trade] = []
    page = 1
    while True:
        params = {
            "serviceKey": key,
            "LAWD_CD": lawd_cd,
            "DEAL_YMD": deal_ymd,
            "pageNo": page,
            "numOfRows": PAGE_SIZE,
        }
        resp = _get_with_retry(http, url, params, timeout, f"{ENDPOINTS[ptype][2]} {deal_ymd} 거래")
        if resp.status_code != 200:
            # 게이트웨이 오류 XML이면 그 메시지를 쓴다
            try:
                parse_response(resp.text, ptype)
            except RTMSApiError as e:
                raise RTMSApiError(f"HTTP {resp.status_code} ({ENDPOINTS[ptype][2]}): {e}") from None
            raise RTMSApiError(f"HTTP {resp.status_code}: {resp.text[:200]!r}")
        trades, total = parse_response(resp.text, ptype)
        results.extend(trades)
        if page * PAGE_SIZE >= total:
            break
        page += 1
    return results


def recent_months(months: int = 12, today: date | None = None) -> list[str]:
    """이번 달부터 거슬러 올라간 'YYYYMM' 목록 (최신순)."""
    today = today or date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(months):
        out.append(f"{y:04d}{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def fetch_recent_trades(
    property_type: str,
    lawd_cd: str,
    months: int = 12,
    today: date | None = None,
    service_key: str | None = None,
    session: requests.Session | None = None,
) -> list[Trade]:
    """최근 N개월 거래를 월별로 호출해 합친다."""
    key = service_key or load_service_key()
    http = session or requests.Session()
    out: list[Trade] = []
    for ymd in recent_months(months, today):
        out.extend(fetch_trades(property_type, lawd_cd, ymd, service_key=key, session=http))
    return out


def trades_to_dicts(trades: Iterable[Trade]) -> list[dict]:
    return [t.to_dict() for t in trades]
