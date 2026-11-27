"""분석 요청 API. 업로드한 문서와 입력값으로 document/ 모듈을 돌려 결과를 저장하고 돌려줍니다."""

import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from app.api.deps import get_analysis_engine, get_analysis_store
from app.core.config import get_settings
from app.services.analysis_engine import AnalysisEngine, AnalysisInput
from app.services.analysis_store import AnalysisStore

router = APIRouter(prefix="/analyses", tags=["analyses"])

Engine = Annotated[AnalysisEngine, Depends(get_analysis_engine)]
Store = Annotated[AnalysisStore, Depends(get_analysis_store)]

# 사진은 OCR 모듈(PIL)이 열 수 있는 형식만 받습니다. HEIC는 PIL이 열지 못해 받지 않습니다.
DOCUMENT_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/webp"}


def _read_upload(upload: UploadFile, label: str, allowed: set[str] = DOCUMENT_TYPES) -> bytes:
    if upload.content_type not in allowed:
        hint = " 아이폰 HEIC 사진은 JPG로 바꿔서 올려 주세요." if upload.content_type in {"image/heic", "image/heif"} else ""
        raise HTTPException(415, f"{label}: 지원하지 않는 파일 형식입니다 ({upload.content_type}). PDF, JPG, PNG, WEBP만 받습니다.{hint}")
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = upload.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"{label}: 파일이 {get_settings().max_upload_mb}MB를 넘습니다")
    if not data:
        raise HTTPException(400, f"{label}: 빈 파일입니다")
    return data


# async가 아닌 def라서 FastAPI가 스레드에서 돌립니다 (PDF 읽기·외부 API 호출이 이벤트 루프를 막지 않음).
@router.post("", status_code=201)
def create_analysis(
    engine: Engine,
    store: Store,
    address: Annotated[str, Form(description="주소. 예: 서울 강남구 테헤란로 152 101동 1203호")],
    property_type: Annotated[str, Form(description="아파트 / 오피스텔 / 연립다세대")],
    deposit: Annotated[int, Form(gt=0, description="보증금(원)")],
    area_m2: Annotated[float | None, Form(gt=0, description="전용면적(㎡). 없으면 등기부 값을 씀")] = None,
    dong_nm: Annotated[str | None, Form(description="동. 주소에 없을 때만")] = None,
    ho_nm: Annotated[str | None, Form(description="호. 주소에 없을 때만")] = None,
    registry_file: Annotated[
        list[UploadFile] | None, File(description="등기사항전부증명서 PDF, 스캔본 또는 사진(여러 장 가능, 쪽 순서대로)")
    ] = None,
    contract_files: Annotated[list[UploadFile] | None, File(description="계약서 PDF 또는 사진(여러 장 가능, 쪽 순서대로)")] = None,
) -> dict[str, Any]:
    try:
        engine.check_property_type(property_type)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    data = AnalysisInput(
        address=address,
        property_type=property_type,
        deposit=deposit,
        area_m2=area_m2,
        dong_nm=dong_nm or None,
        ho_nm=ho_nm or None,
        registry_files=[_read_upload(f, "등기부") for f in registry_file or []],
        contract_files=[_read_upload(f, "계약서") for f in contract_files or []],
    )

    analysis_id = uuid.uuid4().hex
    created_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    output = engine.run(data, analysis_id)
    input_summary = {
        "address": address,
        "property_type": property_type,
        "deposit": deposit,
        "area_m2": area_m2,
        "dong_nm": data.dong_nm,
        "ho_nm": data.ho_nm,
        "registry_uploaded": bool(data.registry_files),
        "registry_pages": len(data.registry_files),
        "contract_pages": len(data.contract_files),
    }
    store.save(analysis_id, created_at, input_summary, output.result, output.notes)
    return {"analysis_id": analysis_id, "created_at": created_at, "input": input_summary, "result": output.result, "notes": output.notes}


@router.get("")
def list_analyses(store: Store, limit: int = Query(20, ge=1, le=100)) -> list[dict[str, Any]]:
    return store.list_recent(limit)


@router.get("/{analysis_id}")
def get_analysis(analysis_id: str, store: Store) -> dict[str, Any]:
    found = store.get(analysis_id)
    if found is None:
        raise HTTPException(404, "분석 결과가 없습니다")
    return found
