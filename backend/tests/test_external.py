import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_law_client, get_public_data_client
from app.clients.law import LawApiClient
from app.clients.public_data import PublicDataApi, PublicDataClient
from app.core.config import Settings
from app.main import app

FAKE_APIS = {"sample": PublicDataApi(path="/123/Svc/getItems", description="테스트용", default_params={"numOfRows": 10})}


def _settings(**overrides) -> Settings:
    base = {"law_api_oc": "", "public_data_api_key": ""}
    return Settings(_env_file=None, **{**base, **overrides})


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def _use(law: LawApiClient | None = None, data: PublicDataClient | None = None) -> None:
    if law is not None:
        app.dependency_overrides[get_law_client] = lambda: law
    if data is not None:
        app.dependency_overrides[get_public_data_client] = lambda: data


def test_status_hides_key_values(client):
    _use(
        law=LawApiClient(_settings(law_api_oc="tester")),
        data=PublicDataClient(_settings(), apis=FAKE_APIS),
    )
    body = client.get("/api/external/status").json()
    assert body["law_api"] == {"configured": True}
    assert body["public_data_api"]["configured"] is False
    assert body["public_data_api"]["registered"] == {"sample": "테스트용"}
    assert "tester" not in str(body)


def test_law_search_sends_oc_and_returns_json(client):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = request.url
        return httpx.Response(200, json={"LawSearch": {"totalCnt": "1"}})

    _use(law=LawApiClient(_settings(law_api_oc="tester"), transport=httpx.MockTransport(handler)))
    response = client.get("/api/external/law/search", params={"query": "주택임대차보호법"})

    assert response.status_code == 200
    assert response.json() == {"LawSearch": {"totalCnt": "1"}}
    assert seen["url"].path == "/DRF/lawSearch.do"
    assert seen["url"].params["OC"] == "tester"
    assert seen["url"].params["type"] == "JSON"
    assert seen["url"].params["query"] == "주택임대차보호법"


def test_law_without_oc_returns_503(client):
    _use(law=LawApiClient(_settings()))
    response = client.get("/api/external/law/search", params={"query": "임대차"})
    assert response.status_code == 503


def test_public_data_adds_service_key_and_parses_xml(client):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = request.url
        xml = (
            "<response><header><resultCode>000</resultCode><resultMsg>OK</resultMsg></header>"
            "<body><items><item><deposit>30,000</deposit></item><item><deposit>25,000</deposit></item></items></body>"
            "</response>"
        )
        return httpx.Response(200, text=xml, headers={"content-type": "application/xml"})

    _use(data=PublicDataClient(_settings(public_data_api_key="a+b/c=="), apis=FAKE_APIS, transport=httpx.MockTransport(handler)))
    response = client.get("/api/external/public-data/sample", params={"LAWD_CD": "11110"})

    assert response.status_code == 200
    items = response.json()["response"]["body"]["items"]["item"]
    assert [i["deposit"] for i in items] == ["30,000", "25,000"]
    assert seen["url"].path == "/123/Svc/getItems"
    assert seen["url"].params["serviceKey"] == "a+b/c=="  # Decoding 키가 그대로 전달됨
    assert seen["url"].params["LAWD_CD"] == "11110"
    assert seen["url"].params["numOfRows"] == "10"


def test_public_data_error_body_becomes_502(client):
    def handler(request: httpx.Request) -> httpx.Response:
        xml = (
            "<OpenAPI_ServiceResponse><cmmMsgHeader><returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg>"
            "<returnReasonCode>30</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>"
        )
        return httpx.Response(200, text=xml)

    _use(data=PublicDataClient(_settings(public_data_api_key="k"), apis=FAKE_APIS, transport=httpx.MockTransport(handler)))
    response = client.get("/api/external/public-data/sample")

    assert response.status_code == 502
    assert "SERVICE_KEY_IS_NOT_REGISTERED_ERROR" in response.json()["detail"]


def test_unknown_public_data_api_returns_404(client):
    _use(data=PublicDataClient(_settings(public_data_api_key="k"), apis=FAKE_APIS))
    assert client.get("/api/external/public-data/nope").status_code == 404
