"""공공데이터포털(data.go.kr) Open API 클라이언트.

활용신청한 API는 PUBLIC_DATA_APIS에 이름과 경로를 등록하고,
client.call("이름", 파라미터...)로 호출합니다. serviceKey는 자동으로 붙습니다.
"""

from dataclasses import dataclass, field
from typing import Any

import httpx

from app.clients.base import ExternalApiError, parse_response
from app.core.config import Settings

SOURCE = "data.go.kr"


@dataclass(frozen=True)
class PublicDataApi:
    path: str  # apis.data.go.kr 뒤 경로, 예: /1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent
    description: str
    default_params: dict[str, Any] = field(default_factory=dict)


# 활용신청한 API를 여기에 등록합니다. 경로는 각 API 상세 페이지의 "요청주소"를 참고하세요.
PUBLIC_DATA_APIS: dict[str, PublicDataApi] = {
    "apt_rent": PublicDataApi(
        path="/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent",
        description="국토교통부 아파트 전월세 실거래가 (필수: LAWD_CD 지역코드 5자리, DEAL_YMD 계약년월 6자리)",
        default_params={"pageNo": 1, "numOfRows": 100},
    ),
    # "qna": PublicDataApi(path="/...", description="전세사기 예방 백문백답"),
}


class PublicDataClient:
    def __init__(
        self,
        settings: Settings,
        apis: dict[str, PublicDataApi] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._key = settings.public_data_api_key
        self._base_url = settings.public_data_base_url.rstrip("/")
        self._timeout = settings.external_api_timeout
        self._apis = PUBLIC_DATA_APIS if apis is None else apis
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self._key)

    @property
    def apis(self) -> dict[str, PublicDataApi]:
        return self._apis

    async def call(self, name: str, **params: Any) -> Any:
        api = self._apis.get(name)
        if api is None:
            raise ExternalApiError(SOURCE, f"등록되지 않은 API입니다: {name}", 404)
        return await self.get(api.path, **{**api.default_params, **params})

    async def get(self, path: str, **params: Any) -> Any:
        if not self.configured:
            raise ExternalApiError(SOURCE, "PUBLIC_DATA_API_KEY가 .env에 설정되지 않았습니다.")
        # Decoding 키를 넣으면 httpx가 한 번만 인코딩합니다.
        query = {"serviceKey": self._key, **params}
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                response = await client.get(f"{self._base_url}/{path.lstrip('/')}", params=query)
        except httpx.HTTPError as exc:
            raise ExternalApiError(SOURCE, f"요청 실패: {exc}") from exc
        if response.status_code != 200:
            raise ExternalApiError(SOURCE, response.text[:300], response.status_code)
        try:
            data = parse_response(response)
        except ValueError as exc:
            raise ExternalApiError(SOURCE, str(exc)) from exc
        _raise_on_error_body(data)
        return data


def _raise_on_error_body(data: Any) -> None:
    """data.go.kr은 키 오류 등을 HTTP 200 + 본문 오류 코드로 돌려주는 경우가 많습니다."""
    if not isinstance(data, dict):
        return
    # 일반 응답: {"response": {"header": {"resultCode": "00", ...}}}
    header = data.get("response", {}).get("header") if isinstance(data.get("response"), dict) else None
    if isinstance(header, dict):
        code = str(header.get("resultCode", ""))
        if code and code not in {"00", "000"}:
            raise ExternalApiError(SOURCE, f"{code} {header.get('resultMsg', '')}".strip())
    # 게이트웨이 오류: {"OpenAPI_ServiceResponse": {"cmmMsgHeader": {...}}}
    gateway = data.get("OpenAPI_ServiceResponse")
    if isinstance(gateway, dict):
        msg = gateway.get("cmmMsgHeader", {})
        raise ExternalApiError(
            SOURCE,
            f"{msg.get('returnReasonCode', '')} {msg.get('returnAuthMsg') or msg.get('errMsg', '')}".strip(),
        )
