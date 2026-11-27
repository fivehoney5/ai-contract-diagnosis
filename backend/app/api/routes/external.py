"""외부 API 연결 확인용 라우트. Swagger(/docs)에서 키가 제대로 들어갔는지 바로 시험할 수 있습니다."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.deps import get_law_client, get_public_data_client
from app.clients.base import ExternalApiError
from app.clients.law import LawApiClient
from app.clients.public_data import PublicDataClient

router = APIRouter(prefix="/external", tags=["external"])

LawClient = Annotated[LawApiClient, Depends(get_law_client)]
DataClient = Annotated[PublicDataClient, Depends(get_public_data_client)]


def _to_http_error(exc: ExternalApiError) -> HTTPException:
    if exc.status_code == 404:
        return HTTPException(status_code=404, detail=exc.message)
    if "설정되지 않았습니다" in exc.message:
        return HTTPException(status_code=503, detail=exc.message)
    return HTTPException(status_code=502, detail=f"[{exc.source}] {exc.message}")


@router.get("/status")
def status(law: LawClient, data: DataClient) -> dict[str, Any]:
    """각 외부 API 키가 .env에 들어 있는지 확인합니다. 키 값은 노출하지 않습니다."""
    return {
        "law_api": {"configured": law.configured},
        "public_data_api": {
            "configured": data.configured,
            "registered": {name: api.description for name, api in data.apis.items()},
        },
    }


@router.get("/law/search")
async def law_search(
    law: LawClient,
    query: str = Query(..., description="검색어, 예: 주택임대차보호법"),
    target: str = Query("law", description="law(법령), prec(판례), expc(법령해석례) 등"),
    page: int = Query(1, ge=1),
    display: int = Query(20, ge=1, le=100),
) -> Any:
    try:
        return await law.search(query, target=target, page=page, display=display)
    except ExternalApiError as exc:
        raise _to_http_error(exc) from exc


@router.get("/law/{item_id}")
async def law_detail(
    law: LawClient,
    item_id: str,
    target: str = Query("law", description="law(법령), prec(판례) 등"),
) -> Any:
    try:
        return await law.detail(item_id, target=target)
    except ExternalApiError as exc:
        raise _to_http_error(exc) from exc


@router.get("/public-data/{name}")
async def public_data(name: str, request: Request, data: DataClient) -> Any:
    """등록된 공공데이터 API를 호출합니다. 쿼리 파라미터는 그대로 전달됩니다.

    예: /api/external/public-data/qna?pageNo=1
    """
    try:
        return await data.call(name, **dict(request.query_params))
    except ExternalApiError as exc:
        raise _to_http_error(exc) from exc
