from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_analysis_engine, get_analysis_store
from app.main import app
from app.services.analysis_engine import AnalysisEngine, AnalysisInput
from app.services.analysis_store import AnalysisStore

ADDRESS_OK = {"status": "ok", "reason_code": None, "reason": None, "address": {"address_key": "1168010100-0123-0000"}}
REGISTRY_OK = {
    "data_status_item": {"part": "registry", "status": "ok", "reason_code": None, "reason": None},
    "property": {"exclusive_area_m2": 84.97},
    "senior_amount_used": 120_000_000,
}


class Calls:
    def __init__(self):
        self.price_kwargs = None
        self.result_kwargs = None
        self.contract_arg = None
        self.registry_arg = None


def fake_engine(calls: Calls, *, address=ADDRESS_OK) -> AnalysisEngine:
    def analyze_price(property_type, **kwargs):
        calls.price_kwargs = {"property_type": property_type, **kwargs}
        return {"data_status_item": {"part": "price", "status": "ok"}}

    def build(**kwargs):
        calls.result_kwargs = kwargs
        return {"analysis_id": kwargs["analysis_id"], "grade": "주의", "flags": []}

    def contract(files):
        calls.contract_arg = files
        return {"extraction_status": "ok"}

    def normalize(t):
        if t not in {"아파트", "오피스텔", "연립다세대"}:
            raise ValueError(f"지원하지 않는 유형: {t!r}")
        return t

    return AnalysisEngine(
        resolve_address=lambda text, **kw: address,
        to_price_args=lambda a: {"lawd_cd": "11680", "dong": "역삼동", "building": "123"},
        analyze_price=analyze_price,
        analyze_registry=lambda src: setattr(calls, "registry_arg", src) or REGISTRY_OK,
        build_analysis_result=build,
        normalize_type=normalize,
        analyze_contract=contract,
    )


def test_engine_uses_registry_area_and_senior_amount():
    calls = Calls()
    out = fake_engine(calls).run(AnalysisInput("서울 강남구 테헤란로 152", "아파트", 300_000_000, registry_files=[b"%PDF"]), "id1")

    assert calls.registry_arg == b"%PDF"  # 한 장이면 bytes 그대로
    assert calls.price_kwargs["area"] == 84.97
    assert calls.price_kwargs["senior_amount_used"] == 120_000_000
    assert calls.price_kwargs["deposit"] == 300_000_000
    assert calls.price_kwargs["lawd_cd"] == "11680"
    assert calls.result_kwargs["registry"] is REGISTRY_OK
    assert calls.result_kwargs["special_terms"] is None
    assert any("등기부 값" in n for n in out.notes)


def test_engine_skips_price_without_area_or_address():
    calls = Calls()
    out = fake_engine(calls).run(AnalysisInput("주소", "아파트", 1), "id2")
    assert calls.price_kwargs is None and calls.result_kwargs["price"] is None
    assert any("전용면적" in n for n in out.notes)

    calls = Calls()
    failed = {"status": "failed", "reason_code": "ADDRESS_NOT_FOUND", "address": None}
    fake_engine(calls, address=failed).run(AnalysisInput("주소", "아파트", 1, area_m2=59.0), "id3")
    assert calls.price_kwargs is None
    assert calls.result_kwargs["address"] is failed


def test_engine_passes_registry_photos_as_list():
    calls = Calls()
    fake_engine(calls).run(AnalysisInput("주소", "아파트", 1, registry_files=[b"p1", b"p2"]), "id6")
    assert calls.registry_arg == [b"p1", b"p2"]


def test_engine_passes_contract_pages():
    calls = Calls()
    fake_engine(calls).run(AnalysisInput("주소", "아파트", 1, contract_files=[b"a", b"b"]), "id4")
    assert calls.contract_arg == [b"a", b"b"]
    assert calls.result_kwargs["special_terms"] == {"extraction_status": "ok"}

    calls = Calls()
    fake_engine(calls).run(AnalysisInput("주소", "아파트", 1), "id5")
    assert calls.contract_arg is None and calls.result_kwargs["special_terms"] is None


def test_real_risk_module_holds_grade_when_address_fails():
    real = AnalysisEngine.from_document_modules()
    failed = {"status": "failed", "reason_code": "ADDRESS_NOT_FOUND", "reason": "일치하는 주소가 없습니다", "address": None}
    engine = replace(real, resolve_address=lambda text, **kw: failed)  # 네트워크 없이 실제 등급 모듈만 확인

    result = engine.run(AnalysisInput("없는 주소", "아파트", 100_000_000), "real-1").result

    assert result["analysis_id"] == "real-1"
    assert result["grade"] == "판단보류"
    parts = {i["part"]: i for i in result["data_status"]["items"]}
    assert parts["price"]["reason_code"] == "ADDRESS_NOT_FOUND"
    assert parts["registry"]["status"] == "not_provided"


@pytest.fixture
def client():
    calls = Calls()
    store = AnalysisStore(":memory:")
    app.dependency_overrides[get_analysis_engine] = lambda: fake_engine(calls)
    app.dependency_overrides[get_analysis_store] = lambda: store
    yield TestClient(app), calls
    app.dependency_overrides.clear()


def test_create_then_get_analysis(client):
    http, calls = client
    response = http.post(
        "/api/analyses",
        data={"address": "서울 강남구 테헤란로 152", "property_type": "아파트", "deposit": "300000000"},
        files=[
            ("registry_file", ("등기부1.jpg", b"reg1", "image/jpeg")),
            ("registry_file", ("등기부2.png", b"reg2", "image/png")),
            ("contract_files", ("1.jpg", b"img1", "image/jpeg")),
            ("contract_files", ("2.jpg", b"img2", "image/jpeg")),
        ],
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["result"]["grade"] == "주의"
    assert body["input"]["registry_uploaded"] is True
    assert body["input"]["registry_pages"] == 2
    assert calls.registry_arg == [b"reg1", b"reg2"]
    assert body["input"]["contract_pages"] == 2
    assert calls.contract_arg == [b"img1", b"img2"]

    got = http.get(f"/api/analyses/{body['analysis_id']}").json()
    assert got["result"] == body["result"]
    assert got["notes"] == body["notes"]
    listed = http.get("/api/analyses").json()
    assert listed[0]["analysis_id"] == body["analysis_id"] and listed[0]["grade"] == "주의"


def test_create_rejects_bad_input(client):
    http, _ = client
    base = {"address": "주소", "property_type": "아파트", "deposit": "1"}
    assert http.post("/api/analyses", data={**base, "property_type": "상가"}).status_code == 422
    assert http.post("/api/analyses", data={**base, "deposit": "0"}).status_code == 422
    wrong = http.post("/api/analyses", data=base, files={"registry_file": ("a.txt", b"hi", "text/plain")})
    assert wrong.status_code == 415
    heic = http.post("/api/analyses", data=base, files={"registry_file": ("a.heic", b"x", "image/heic")})
    assert heic.status_code == 415 and "JPG" in heic.json()["detail"]
    single_pdf = http.post("/api/analyses", data=base, files={"registry_file": ("a.pdf", b"%PDF", "application/pdf")})
    assert single_pdf.status_code == 201 and single_pdf.json()["input"]["registry_pages"] == 1
    assert http.get("/api/analyses/nope").status_code == 404
