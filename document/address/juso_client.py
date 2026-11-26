"""행정안전부 도로명주소 검색 API(juso.go.kr) 클라이언트.

요청주소: https://business.juso.go.kr/addrlink/addrLinkApi.do (resultType=json)
키: 저장소 루트 .env의 JUSO_API_KEY (승인키, confmKey)
"""

from __future__ import annotations

import os
import re
import time

import requests
from dotenv import load_dotenv

API_URL = "https://business.juso.go.kr/addrlink/addrLinkApi.do"
KEY_ENV = "JUSO_API_KEY"
COUNT_PER_PAGE = 20  # 후보로 보여줄 만큼만 받는다 (API 최대 100)
TIMEOUT = 10  # 초
RETRIES = 1  # 연결 실패·서버 오류면 한 번 더 시도
RETRY_WAIT = 1.0  # 다시 시도하기 전 기다리는 시간(초)

# 승인키·서버 문제 (사용자가 주소를 고쳐도 해결 안 됨) -> API_UNAVAILABLE
#   -999 시스템 에러, E0001 승인되지 않은 키, E0014 개발 승인키 기간 만료
# 그 밖의 E0005-E0015는 검색어 문제 (검색어 없음, 시도명만 입력, 한 글자, 특수문자 등) -> ADDRESS_NOT_FOUND
SERVICE_ERROR_CODES = {"-999", "E0001", "E0014"}

# API가 거부하는 특수문자·SQL 예약어 (오류 E0012, E0013). 검색 전에 지운다.
_FORBIDDEN_CHARS_RE = re.compile(r"[%=><\[\]{}'\";]")
_SQL_WORDS_RE = re.compile(
    r"\b(OR|SELECT|INSERT|DELETE|UPDATE|CREATE|DROP|EXEC|UNION|FETCH|DECLARE|TRUNCATE)\b",
    re.IGNORECASE,
)


class JusoApiError(RuntimeError):
    """연결 실패, 서버 오류, 승인키 오류 (분석 결과의 API_UNAVAILABLE)."""


class JusoParseError(JusoApiError):
    """응답을 JSON으로 읽지 못하거나 모양이 예상과 다를 때 (PARSE_FAILED)."""


class JusoKeywordError(ValueError):
    """API가 검색어 문제로 거절했을 때 (ADDRESS_NOT_FOUND). code는 API 오류 코드."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def get_api_key() -> str:
    load_dotenv()
    key = os.getenv(KEY_ENV, "").strip()
    if not key:
        raise JusoApiError(f".env에 {KEY_ENV}가 없습니다 (도로명주소 검색 API 승인키를 넣으세요)")
    return key


def clean_keyword(keyword: str) -> str:
    """API가 거부하는 특수문자·SQL 예약어를 지우고 공백을 정리한다."""
    text = _FORBIDDEN_CHARS_RE.sub(" ", keyword)
    text = _SQL_WORDS_RE.sub(" ", text)
    return " ".join(text.split())


def search_juso(
    keyword: str,
    *,
    api_key: str | None = None,
    session: requests.Session | None = None,
    count_per_page: int = COUNT_PER_PAGE,
) -> tuple[int, list[dict]]:
    """검색어로 주소를 찾아 (전체 건수, 첫 페이지 주소 목록)을 돌려준다.

    주소 목록의 각 항목은 API의 juso 원본 dict (admCd, mtYn, lnbrMnnm, lnbrSlno, emdNm, bdNm ...).
    실패하면 JusoApiError / JusoParseError / JusoKeywordError를 던진다.
    """
    key = api_key or get_api_key()
    http = session or requests
    params = {
        "confmKey": key,
        "currentPage": 1,
        "countPerPage": count_per_page,
        "keyword": keyword,
        "resultType": "json",
    }

    last_error: Exception | None = None
    for attempt in range(RETRIES + 1):
        if attempt:
            time.sleep(RETRY_WAIT)
        try:
            resp = http.get(API_URL, params=params, timeout=TIMEOUT)
        except requests.RequestException as e:
            # 오류 문구에 승인키가 든 URL이 섞일 수 있어서 종류만 남긴다
            last_error = JusoApiError(f"도로명주소 API 연결 실패 ({type(e).__name__})")
            continue
        if resp.status_code >= 500:
            last_error = JusoApiError(f"도로명주소 API 서버 오류 (HTTP {resp.status_code})")
            continue
        if resp.status_code != 200:
            raise JusoApiError(f"도로명주소 API 요청 실패 (HTTP {resp.status_code})")
        return _parse_response(resp)
    raise last_error  # type: ignore[misc]


def _parse_response(resp) -> tuple[int, list[dict]]:
    try:
        data = resp.json()
    except ValueError as e:
        raise JusoParseError("도로명주소 API 응답을 JSON으로 읽지 못했습니다") from e
    try:
        results = data["results"]
        common = results["common"]
        code = str(common.get("errorCode", "")).strip()
        message = str(common.get("errorMessage", "")).strip()
    except (KeyError, TypeError, AttributeError) as e:
        raise JusoParseError("도로명주소 API 응답에 results.common이 없습니다") from e

    if code != "0":
        if code in SERVICE_ERROR_CODES or not code.startswith("E"):
            raise JusoApiError(f"도로명주소 API 오류 {code}: {message}")
        raise JusoKeywordError(code, message)

    juso = results.get("juso") or []
    if not isinstance(juso, list) or not all(isinstance(j, dict) for j in juso):
        raise JusoParseError("도로명주소 API 응답의 juso 목록 모양이 예상과 다릅니다")
    try:
        total = int(common.get("totalCount") or len(juso))
    except (TypeError, ValueError):
        total = len(juso)
    return total, juso
