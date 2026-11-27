"""국가법령정보 공동활용 Open API 클라이언트.

가이드: https://open.law.go.kr/LSO/openApi/guideList.do
- 목록 조회: {base}/lawSearch.do?OC=...&target=law&type=JSON&query=...
- 본문 조회: {base}/lawService.do?OC=...&target=law&type=JSON&ID=...
target 값: law(법령), prec(판례), expc(법령해석례) 등
"""

from typing import Any

import httpx

from app.clients.base import ExternalApiError, parse_response
from app.core.config import Settings

SOURCE = "law.go.kr"


class LawApiClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._oc = settings.law_api_oc
        self._base_url = settings.law_api_base_url.rstrip("/")
        self._timeout = settings.external_api_timeout
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self._oc)

    async def _get(self, endpoint: str, params: dict[str, Any]) -> Any:
        if not self.configured:
            raise ExternalApiError(SOURCE, "LAW_API_OC가 .env에 설정되지 않았습니다.")
        query = {"OC": self._oc, "type": "JSON", **params}
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                response = await client.get(f"{self._base_url}/{endpoint}", params=query)
        except httpx.HTTPError as exc:
            raise ExternalApiError(SOURCE, f"요청 실패: {exc}") from exc
        if response.status_code != 200:
            raise ExternalApiError(SOURCE, response.text[:300], response.status_code)
        try:
            return parse_response(response)
        except ValueError as exc:
            raise ExternalApiError(SOURCE, str(exc)) from exc

    async def search(self, query: str, target: str = "law", page: int = 1, display: int = 20) -> Any:
        """법령·판례 등 목록 검색."""
        return await self._get(
            "lawSearch.do",
            {"target": target, "query": query, "page": page, "display": display},
        )

    async def detail(self, item_id: str, target: str = "law") -> Any:
        """법령·판례 등 본문 조회. item_id는 목록 결과의 ID(법령ID, 판례일련번호 등)."""
        return await self._get("lawService.do", {"target": target, "ID": item_id})
