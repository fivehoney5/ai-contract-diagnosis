import xml.etree.ElementTree as ET
from typing import Any

import httpx


class ExternalApiError(Exception):
    """외부 API 호출 실패. 키 미설정, 네트워크 오류, 오류 응답을 모두 이 예외로 올립니다."""

    def __init__(self, source: str, message: str, status_code: int | None = None):
        super().__init__(f"[{source}] {message}")
        self.source = source
        self.message = message
        self.status_code = status_code


def _xml_to_dict(element: ET.Element) -> Any:
    children = list(element)
    if not children:
        return (element.text or "").strip()
    result: dict[str, Any] = {}
    for child in children:
        value = _xml_to_dict(child)
        if child.tag in result:
            if not isinstance(result[child.tag], list):
                result[child.tag] = [result[child.tag]]
            result[child.tag].append(value)
        else:
            result[child.tag] = value
    return result


def parse_response(response: httpx.Response) -> Any:
    """JSON이면 JSON으로, 아니면 XML로 읽어 dict로 돌려줍니다."""
    try:
        return response.json()
    except ValueError:
        pass
    try:
        root = ET.fromstring(response.text)
    except ET.ParseError as exc:
        raise ValueError(f"JSON도 XML도 아닌 응답입니다: {response.text[:200]}") from exc
    return {root.tag: _xml_to_dict(root)}
