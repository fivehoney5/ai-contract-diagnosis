"""국토교통부 건축HUB 건축물대장정보 서비스(공공데이터포털) 클라이언트.

주소(시군구코드 5자리 + 법정동코드 5자리 + 지번)로 다음을 가져온다.
    - 건축년도 (사용승인일 useAprDay의 연도)
    - 주용도 (mainPurpsCdNm, etcPurps) -> 주거용인지 판단
    - 동·호를 넣으면 그 호의 전유부 용도 (근린생활시설로 등록된 호 찾기)

쓰는 기능:
    - 표제부       : BldRgstHubService/getBrTitleInfo
    - 전유공용면적 : BldRgstHubService/getBrExposPubuseAreaInfo

위반건축물 여부:
    공공데이터포털 건축물대장 API(표제부, 총괄표제부, 기본개요, 전유부 등)에는 위반건축물 표시 항목이 없다
    (2026-11-25 확인). 위반건축물은 정부24·세움터에서 발급하는 건축물대장 열람본에만 표시되므로
    violation_building은 항상 None("알 수 없음")으로 두고, 나중에 대장 PDF/OCR 결과로 채운다.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict

import requests

from .rtms_client import RTMSApiError, SUCCESS_CODES, _get_with_retry, load_service_key

BASE_URL = "https://apis.data.go.kr/1613000/BldRgstHubService"
TITLE_OP = "getBrTitleInfo"
EXPOS_OP = "getBrExposPubuseAreaInfo"

# 주용도 코드 앞 2자리: 01 단독주택, 02 공동주택. 오피스텔은 업무시설(14)이지만 주거용으로 본다.
RESIDENTIAL_PURPOSE_PREFIXES = ("01", "02")

FLAG_NON_RESIDENTIAL = "NON_RESIDENTIAL"  # 주용도(또는 해당 호 용도)가 주거용이 아님 (근린생활시설 등)
FLAG_VIOLATION_BUILDING = "VIOLATION_BUILDING"  # 위반건축물 (지금 API로는 알 수 없음, 나중에 채움)
CHECK_VIOLATION = "VIOLATION_BUILDING_CHECK_NEEDED"  # 위반건축물 여부를 사람이 확인해야 함
CHECK_VIOLATION_MESSAGE = "위반건축물 여부 확인 필요: 정부24·세움터에서 건축물대장을 열람해 '위반건축물' 표시가 있는지 확인하세요."
CHECK_UNIT_PURPOSE = "UNIT_PURPOSE_CHECK_NEEDED"  # 같은 호가 여러 건이고 용도가 달라 어느 호인지 사람이 확인해야 함
CHECK_UNIT_PURPOSE_MESSAGE = "호 용도 확인 필요: 같은 호수가 여러 동에 있고 용도가 달라 판정하지 않았습니다. 계약서의 동을 넣어 다시 조회하세요."
CHECK_MESSAGES = {CHECK_VIOLATION: CHECK_VIOLATION_MESSAGE, CHECK_UNIT_PURPOSE: CHECK_UNIT_PURPOSE_MESSAGE}

_JIBUN_PARSE_RE = re.compile(r"^(산\s*)?(\d+)(?:-(\d+))?$")


class BuildingRegisterError(RTMSApiError):
    """건축물대장 API 오류."""


@dataclass
class BuildingInfo:
    sigungu_cd: str
    bjdong_cd: str
    jibun: str
    found: bool  # 건축물대장에 해당 지번 건물이 있는지
    building_name: str = ""
    address: str = ""  # 대장상 지번 주소 (platPlc)
    use_approval_date: str = ""  # 사용승인일 YYYYMMDD
    build_year: int | None = None
    main_purpose: str = ""  # 주용도 (예: 공동주택, 제2종근린생활시설)
    etc_purpose: str = ""  # 기타용도 (예: 다세대주택, 오피스텔)
    is_residential: bool | None = None  # 건물 주용도 기준
    unit_dong: str = ""
    unit_ho: str = ""
    unit_purpose: str = ""  # 해당 호 전유부 용도
    unit_is_residential: bool | None = None
    violation_building: bool | None = None  # None = 알 수 없음 (API에서 제공하지 않음)
    flags: list[str] = field(default_factory=list)
    checks_needed: list[str] = field(default_factory=lambda: [CHECK_VIOLATION])  # 사람이 확인해야 할 항목
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def parse_jibun(jibun: str) -> tuple[str, str, str]:
    """'355-14' -> ('0', '0355', '0014'), '산 12' -> ('1', '0012', '0000')."""
    m = _JIBUN_PARSE_RE.match(jibun.strip())
    if not m:
        raise ValueError(f"지번 형식이 아닙니다: {jibun!r} (예: '355-14', '316', '산 12-3')")
    plat_gb = "1" if m.group(1) else "0"
    return plat_gb, f"{int(m.group(2)):04d}", f"{int(m.group(3) or 0):04d}"


def split_bjdong_code(code: str, sigungu_cd: str | None = None) -> tuple[str, str]:
    """10자리 법정동코드('1150010300') 또는 (시군구 5자리, 법정동 5자리)를 나눈다."""
    code = code.strip()
    if len(code) == 10 and code.isdigit():
        return code[:5], code[5:]
    if len(code) == 5 and code.isdigit() and sigungu_cd:
        return sigungu_cd, code
    raise ValueError(f"법정동코드는 10자리(예: 1150010300)이거나 시군구코드와 함께 5자리여야 합니다: {code!r}")


def is_residential_purpose(purpose_cd: str, purpose_nm: str, etc_purpose: str) -> bool:
    if purpose_cd[:2] in RESIDENTIAL_PURPOSE_PREFIXES:
        return True
    text = f"{purpose_nm} {etc_purpose}"
    if "오피스텔" in text:
        return True
    return any(w in purpose_nm for w in ("주택", "공동주택", "다세대", "연립", "아파트"))


def _items(xml_text: str) -> list[ET.Element]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise BuildingRegisterError(f"건축물대장 응답을 해석할 수 없습니다: {xml_text[:200]!r}") from e
    if root.tag == "OpenAPI_ServiceResponse":
        msg = " / ".join(
            x for x in ((root.findtext(".//errMsg") or "").strip(), (root.findtext(".//returnAuthMsg") or "").strip()) if x
        )
        if "SERVICE_KEY_IS_NOT_REGISTERED" in msg:
            msg += " — 공공데이터포털에서 건축물대장정보 서비스 활용신청이 승인됐는지 확인하세요"
        raise BuildingRegisterError(f"건축물대장 API 오류: {msg or '알 수 없는 오류'}")
    code = (root.findtext("./header/resultCode") or "").strip()
    if code not in SUCCESS_CODES:
        raise BuildingRegisterError(f"건축물대장 API 오류 [{code}] {root.findtext('./header/resultMsg') or ''}")
    return list(root.iterfind("./body/items/item"))


def _t(item: ET.Element, tag: str) -> str:
    return (item.findtext(tag) or "").strip()


def _call(http, op: str, params: dict, timeout: float) -> list[ET.Element]:
    resp = _get_with_retry(http, f"{BASE_URL}/{op}", params, timeout, "건축물대장")
    if resp.status_code != 200:
        try:
            _items(resp.text)
        except BuildingRegisterError as e:
            raise BuildingRegisterError(f"HTTP {resp.status_code}: {e}") from None
        raise BuildingRegisterError(f"건축물대장 HTTP {resp.status_code}: {resp.text[:200]!r}")
    return _items(resp.text)


def fetch_building_info(
    bjdong_code: str,
    jibun: str,
    *,
    sigungu_cd: str | None = None,
    dong_nm: str | None = None,
    ho_nm: str | None = None,
    service_key: str | None = None,
    session: requests.Session | None = None,
    timeout: float = 10.0,
) -> BuildingInfo:
    """주소로 건축년도·주용도(와 호를 넣으면 그 호의 용도)를 가져온다.

    bjdong_code : 10자리 법정동코드 (예: '1150010300' = 서울 강서구 화곡동)
                  또는 5자리 법정동 부분 + sigungu_cd
    jibun       : '355-14' 같은 지번
    dong_nm     : 대장상 동 이름 (예: 'A동'). 여러 동이 있는 건물에서 정확히 고를 때
    ho_nm       : 호 (예: '401'). 넣으면 그 호의 전유부 용도도 확인
    """
    sgg, bjd = split_bjdong_code(bjdong_code, sigungu_cd)
    plat_gb, bun, ji = parse_jibun(jibun)
    key = service_key or load_service_key()
    http = session or requests.Session()
    base = {
        "serviceKey": key, "sigunguCd": sgg, "bjdongCd": bjd,
        "platGbCd": plat_gb, "bun": bun, "ji": ji, "numOfRows": 100, "pageNo": 1,
    }
    info = BuildingInfo(sigungu_cd=sgg, bjdong_cd=bjd, jibun=jibun.strip(), found=False)
    info.notes.append(CHECK_VIOLATION_MESSAGE)

    titles = _call(http, TITLE_OP, base, timeout)
    if not titles:
        info.notes.append("건축물대장 표제부에서 이 지번의 건물을 찾지 못했습니다 (법정동코드·지번 확인).")
        return info

    # 주건축물(부속건축물 제외)만, 동 이름을 넣었으면 그 동을 우선
    main = [t for t in titles if _t(t, "mainAtchGbCd") in ("0", "")] or titles
    if dong_nm:
        picked = [t for t in main if _t(t, "dongNm").replace(" ", "") == dong_nm.replace(" ", "")]
        if picked:
            main = picked
        else:
            info.notes.append(f"대장에 '{dong_nm}' 동이 없어 지번의 대표 건물로 확인했습니다.")
    first = main[0]

    info.found = True
    info.building_name = _t(first, "bldNm")
    info.address = _t(first, "platPlc")
    days = sorted({_t(t, "useAprDay") for t in main if _t(t, "useAprDay").isdigit()})
    if days:
        info.use_approval_date = days[-1]  # 동마다 다르면 가장 늦은 날짜 (신축 여부를 보수적으로 판단)
        info.build_year = int(days[-1][:4])
        if len(days) > 1:
            info.notes.append(f"동마다 사용승인일이 달라({', '.join(days)}) 가장 늦은 날짜를 썼습니다.")
    else:
        info.notes.append("건축물대장에 사용승인일이 없습니다.")

    info.main_purpose = _t(first, "mainPurpsCdNm")
    info.etc_purpose = _t(first, "etcPurps")
    residential = [is_residential_purpose(_t(t, "mainPurpsCd"), _t(t, "mainPurpsCdNm"), _t(t, "etcPurps")) for t in main]
    info.is_residential = all(residential)
    if not info.is_residential:
        info.flags.append(FLAG_NON_RESIDENTIAL)
        names = sorted({_t(t, "mainPurpsCdNm") for t in main})
        info.notes.append(f"건물 주용도가 주거용이 아닙니다: {', '.join(names)}")

    if ho_nm:
        info.unit_dong, info.unit_ho = dong_nm or "", ho_nm
        params = dict(base, hoNm=ho_nm)
        if dong_nm:
            params["dongNm"] = dong_nm
        units = [u for u in _call(http, EXPOS_OP, params, timeout) if _t(u, "exposPubuseGbCdNm") == "전유"]
        units = [u for u in units if _t(u, "hoNm") == ho_nm and (not dong_nm or _t(u, "dongNm") == dong_nm)]
        judged = [
            (u, is_residential_purpose(_t(u, "mainPurpsCd"), _t(u, "mainPurpsCdNm"), _t(u, "etcPurps")))
            for u in units
        ]
        if len({res for _, res in judged}) > 1:
            # 같은 호수가 여러 건(보통 동이 다름)이고 주거용 여부가 갈리면 첫 결과로 정하지 않는다
            dongs = sorted({_t(u, "dongNm") or "(동 없음)" for u in units})
            info.checks_needed.append(CHECK_UNIT_PURPOSE)
            info.notes.append(
                f"{ho_nm}호가 {len(units)}건({', '.join(dongs)})이고 용도가 달라 호 용도를 판정하지 않았습니다 "
                "(dong_nm에 계약서의 동을 넣어 주세요)."
            )
        elif units:
            u, res = judged[0]  # 후보가 여러 건이어도 주거용 여부가 모두 같으면 그대로 판정
            info.unit_purpose = _t(u, "mainPurpsCdNm") or _t(u, "etcPurps")
            info.unit_is_residential = res
            if not info.unit_is_residential and FLAG_NON_RESIDENTIAL not in info.flags:
                info.flags.append(FLAG_NON_RESIDENTIAL)
                info.notes.append(f"{ho_nm}호의 전유부 용도가 주거용이 아닙니다: {info.unit_purpose}")
        else:
            info.notes.append(f"전유부에서 {dong_nm + ' ' if dong_nm else ''}{ho_nm}호를 찾지 못했습니다.")
    return info
