"""입력 주소(주소 모듈)와 업로드한 등기부(표제부)가 같은 집인지 비교한다.

비교하는 것:
    - 지번: 법정동 이름 + 본번-부번 (산 지번이면 산 여부도)
    - 호수: 양쪽 다 있을 때만
한쪽 값이 없으면 비교하지 않는다 (None을 돌려줌). 도로명주소는 표기 차이가 커서 비교하지 않는다.
"""

from __future__ import annotations

import re

# "화곡동 123-4", "가상동 산 12-3", "오남읍 양지리 5"처럼 동·리·가 이름 뒤에 지번
_LOT_RE = re.compile(r"(\S+(?:동|리|가)\d*)\s+(산\s*)?(\d+)(?:\s*-\s*(\d+))?(?=\s|$|[^\d-])")
_HO_RE = re.compile(r"(\d+)\s*호")


def parse_lot(text: str | None) -> tuple[str, bool, int, int] | None:
    """주소 문자열에서 (법정동 이름, 산 여부, 본번, 부번)을 꺼낸다. 못 찾으면 None."""
    if not text:
        return None
    m = _LOT_RE.search(text)
    if not m:
        return None
    return m.group(1), bool(m.group(2)), int(m.group(3)), int(m.group(4) or 0)


def parse_ho(text: str | None) -> int | None:
    """'제2층 제201호', '201호', '201'에서 호수 숫자. 못 찾으면 None."""
    if not text:
        return None
    text = str(text)
    hits = _HO_RE.findall(text)
    if hits:
        return int(hits[-1])
    return int(text) if text.strip().isdigit() else None


def _address_lot(a: dict) -> tuple[str, bool, int, int] | None:
    # 읍·면 지역은 legal_dong_name이 "오남읍"이고 등기부 지번 앞은 리 이름("양지리")이라 리 이름을 우선
    dong = a.get("ri_name") or a.get("legal_dong_name")
    if dong and a.get("bun"):
        try:
            return dong, bool(a.get("is_mountain")), int(a["bun"]), int(a.get("ji") or 0)
        except ValueError:
            pass
    return parse_lot(a.get("jibun_address"))


def compare(address: dict | None, registry: dict | None) -> dict | None:
    """같은 집이면 {"match": True}, 다르면 {"match": False, "diff": [...]}, 비교할 수 없으면 None."""
    a = (address or {}).get("address") if (address or {}).get("status") == "ok" else None
    r = (registry or {}).get("property")
    if not a or not r:
        return None
    a_lot = _address_lot(a)
    r_lot = parse_lot(r.get("address_display"))
    if a_lot is None or r_lot is None:
        return None
    diff = []
    if a_lot != r_lot:
        diff.append("지번")
    a_ho = parse_ho(a.get("ho_nm"))
    r_ho = parse_ho(r.get("unit_no")) or parse_ho(r.get("address_display"))
    if a_ho is not None and r_ho is not None and a_ho != r_ho:
        diff.append("호수")
    return {"match": not diff, "diff": diff}
