"""사용자가 입력한 주소(도로명 또는 지번)를 팀 주소 키로 바꾼다.

주소 키: "법정동코드(10자리)-본번(4자리)-부번(4자리)", 예: "1168010100-0123-0000"
실패해도 예외를 던지지 않고 팀 실패 코드(ADDRESS_NOT_FOUND, API_UNAVAILABLE, PARSE_FAILED)를 돌려준다.
"""

from __future__ import annotations

import re

from .cache import AddressCache
from .juso_client import (
    JusoApiError,
    JusoKeywordError,
    JusoParseError,
    clean_keyword,
    search_juso,
)

ADDRESS_NOT_FOUND = "ADDRESS_NOT_FOUND"
API_UNAVAILABLE = "API_UNAVAILABLE"
PARSE_FAILED = "PARSE_FAILED"

SOURCE = "행정안전부 도로명주소 검색 API (juso.go.kr)"
MAX_CANDIDATES = 5

# 끝에 붙은 "101동 1203호", "B동 302호", "제1203호", "401호". 동은 숫자·영문이나 한 글자(가동)만 인정한다
# ("화곡동 401호"의 화곡동은 법정동 이름이라 건물 동으로 보지 않음).
_UNIT_RE = re.compile(
    r"(?:^|[\s,])(?:제?\s*(?P<dong>[A-Za-z0-9]+|[가-힣])\s*동\s*)?제?\s*(?P<ho>[A-Za-z]?\d+[A-Za-z]?)\s*호\s*$"
)
_FLOOR_RE = re.compile(r"(?:^|[\s,])(?:지하\s*)?\d+\s*층(?=\s|$)")
_PAREN_RE = re.compile(r"\([^)]*\)")
# 검색 결과가 0건이면 "...로 12-3" 또는 "...동 산 12-3"까지만 잘라서 한 번 더 찾는다 (뒤에 붙은 건물명 등 제거)
_CORE_RE = re.compile(r"^(.*?(?:로|길)\s*\d+(?:-\d+)?|.*?(?:동|리|가)\s*(?:산\s*)?\d+(?:-\d+)?)(?=\s|$)")


def split_unit(text: str) -> tuple[str, str | None, str | None]:
    """주소 끝의 동·호를 떼어 (나머지 주소, 동, 호)로 돌려준다. '동'·'호' 글자는 뺀다 (예: '101', 'B', '1203')."""
    m = _UNIT_RE.search(text)
    if not m:
        return text, None, None
    return text[: m.start()].rstrip(" ,"), m.group("dong"), m.group("ho")


def build_keyword(text: str) -> str:
    """API 검색어로 쓸 수 있게 괄호 내용, 층, 특수문자를 지운다."""
    text = _PAREN_RE.sub(" ", text)
    text = _FLOOR_RE.sub(" ", text)
    text = text.replace(",", " ")
    return clean_keyword(text)


def make_address_key(bjdong_cd: str, bun: str, ji: str) -> str:
    return f"{bjdong_cd}-{bun}-{ji}"


def _num4(value) -> str:
    return f"{int(str(value).strip() or 0):04d}"


def juso_to_address(j: dict) -> dict:
    """API juso 항목 하나를 팀 주소 정보로 바꾼다. 필수 값이 이상하면 ValueError."""
    bjdong_cd = str(j.get("admCd", "")).strip()
    if not (len(bjdong_cd) == 10 and bjdong_cd.isdigit()):
        raise ValueError(f"법정동코드(admCd)가 10자리 숫자가 아닙니다: {bjdong_cd!r}")
    mt = str(j.get("mtYn", "0")).strip()
    if mt not in ("0", "1"):
        raise ValueError(f"산 여부(mtYn)가 0/1이 아닙니다: {mt!r}")
    bun = _num4(j.get("lnbrMnnm", ""))
    ji = _num4(j.get("lnbrSlno", ""))
    if bun == "0000":
        raise ValueError("본번(lnbrMnnm)이 비어 있습니다")

    is_mountain = mt == "1"
    jibun = str(int(bun)) + (f"-{int(ji)}" if int(ji) else "")
    if is_mountain:
        jibun = f"산 {jibun}"
    return {
        # 산 지번은 지금 주소 키 형식에 표시할 칸이 없어서 null (팀 확인 필요). 나머지 칸은 채운다.
        "address_key": None if is_mountain else make_address_key(bjdong_cd, bun, ji),
        "bjdong_cd": bjdong_cd,
        "sigungu_cd": bjdong_cd[:5],
        "plat_gb": mt,  # 건축물대장 platGbCd: "0" 대지, "1" 산
        "is_mountain": is_mountain,
        "bun": bun,
        "ji": ji,
        "jibun": jibun,  # 시세 모듈 jibun 인자 형식 ("355-14", "산 12-3")
        "legal_dong_name": str(j.get("emdNm", "")).strip(),  # 법정 읍면동 이름 (실거래가 umdNm과 비교)
        "ri_name": str(j.get("liNm", "")).strip() or None,
        "road_address": str(j.get("roadAddr", "")).strip(),
        "jibun_address": str(j.get("jibunAddr", "")).strip(),
        "zip_code": str(j.get("zipNo", "")).strip() or None,
        "building_name": str(j.get("bdNm", "")).strip() or None,
        "building_mgmt_no": str(j.get("bdMgtSn", "")).strip() or None,
        "is_apartment_complex": str(j.get("bdKdcd", "")).strip() == "1",  # 공동주택 여부
    }


def _lot_id(addr: dict) -> tuple:
    return addr["bjdong_cd"], addr["plat_gb"], addr["bun"], addr["ji"]


def _candidate(addr: dict) -> dict:
    keys = ("address_key", "road_address", "jibun_address", "building_name", "is_mountain")
    return {k: addr[k] for k in keys}


def _result(status, reason_code=None, reason=None, address=None, candidates=None, notes=None, input_text=""):
    return {
        "status": status,  # "ok" 또는 "failed"
        "reason_code": reason_code,
        "reason": reason,
        "input": input_text,
        "address": address,
        "candidates": candidates or [],
        "notes": notes or [],
        "source": SOURCE,
    }


def _search(keyword, api_key, session, cache):
    if cache is not None:
        hit = cache.get(keyword)
        if hit is not None:
            return hit
    total, juso = search_juso(keyword, api_key=api_key, session=session)
    if cache is not None:
        cache.save(keyword, total, juso)
    return total, juso


def resolve_address(
    text: str,
    *,
    dong_nm: str | None = None,
    ho_nm: str | None = None,
    api_key: str | None = None,
    session=None,
    cache: AddressCache | None = None,
) -> dict:
    """주소 문자열을 주소 키와 법정동코드·지번·동·호로 바꾼다. 예외를 던지지 않는다.

    dong_nm, ho_nm을 넣으면 주소 끝에서 읽은 동·호보다 우선한다.
    결과 모양은 README.md 참고.
    """
    original = text or ""
    rest, parsed_dong, parsed_ho = split_unit(original.strip())
    keyword = build_keyword(rest)
    notes: list[str] = []

    if len(keyword) < 2:
        return _result("failed", ADDRESS_NOT_FOUND, "주소를 입력하세요 (예: 서울 강남구 테헤란로 152)", input_text=original)

    try:
        total, juso = _search(keyword, api_key, session, cache)
        if total == 0:
            m = _CORE_RE.match(keyword)
            core = m.group(1).strip() if m else ""
            if core and core != keyword:
                total, juso = _search(core, api_key, session, cache)
                if total:
                    notes.append(f"'{keyword}'로 찾지 못해 '{core}'로 다시 찾음")
    except JusoKeywordError as e:
        return _result("failed", ADDRESS_NOT_FOUND, f"주소 검색어 오류: {e.message} ({e.code})", input_text=original)
    except JusoParseError as e:
        return _result("failed", PARSE_FAILED, str(e), input_text=original)
    except JusoApiError as e:
        return _result("failed", API_UNAVAILABLE, str(e), input_text=original)

    if total == 0 or not juso:
        return _result("failed", ADDRESS_NOT_FOUND, "일치하는 주소가 없습니다 (도로명+건물번호 또는 동+지번으로 입력)", input_text=original)

    try:
        addrs = [juso_to_address(j) for j in juso]
    except (ValueError, TypeError) as e:
        return _result("failed", PARSE_FAILED, f"도로명주소 API 응답 값이 이상합니다: {e}", input_text=original)

    lots: dict[tuple, list[dict]] = {}
    for a in addrs:
        lots.setdefault(_lot_id(a), []).append(a)

    if len(lots) > 1 or total > len(juso):
        firsts = [group[0] for group in lots.values()][:MAX_CANDIDATES]
        return _result(
            "failed",
            ADDRESS_NOT_FOUND,
            f"주소 후보가 {total}건이라 하나로 정할 수 없습니다 (건물번호나 지번까지 입력)",
            candidates=[_candidate(a) for a in firsts],
            input_text=original,
        )

    group = next(iter(lots.values()))
    address = dict(group[0])
    if len(group) > 1:
        names = sorted({a["building_name"] or a["road_address"] for a in group})
        notes.append(f"같은 지번에 건물이 {len(group)}개 있음: {', '.join(names)}")
    if address["is_mountain"]:
        notes.append("산 지번이라 주소 키를 만들지 않음 (팀 형식 확인 필요)")
    # 시세 모듈(건축물대장) 형식에 맞춤: 동은 "101동"/"A동", 호는 "1203"
    address["dong_nm"] = dong_nm or (f"{parsed_dong}동" if parsed_dong else None)
    address["ho_nm"] = ho_nm or parsed_ho
    return _result("ok", address=address, notes=notes, input_text=original)


def to_price_args(address: dict) -> dict:
    """resolve_address 결과의 address를 시세 모듈 analyze_price 키워드 인자로 바꾼다.

    analyze_price(property_type, area=..., deposit=..., **to_price_args(addr))
    building에는 지번을 넣는다 (시세 모듈은 지번으로 같은 건물을 먼저 찾음).
    """
    return {
        "lawd_cd": address["sigungu_cd"],
        "dong": address["legal_dong_name"],
        "building": address["jibun"],
        "bjdong_cd": address["bjdong_cd"],
        "jibun": address["jibun"],
        "dong_nm": address.get("dong_nm"),
        "ho_nm": address.get("ho_nm"),
    }
