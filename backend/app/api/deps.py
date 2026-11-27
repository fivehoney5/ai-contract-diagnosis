from functools import lru_cache

from app.clients.law import LawApiClient
from app.clients.public_data import PublicDataClient
from app.core.config import get_settings
from app.services.analysis_engine import AnalysisEngine
from app.services.analysis_store import AnalysisStore


def get_law_client() -> LawApiClient:
    return LawApiClient(get_settings())


def get_public_data_client() -> PublicDataClient:
    return PublicDataClient(get_settings())


@lru_cache
def get_analysis_engine() -> AnalysisEngine:
    return AnalysisEngine.from_document_modules()


@lru_cache
def get_analysis_store() -> AnalysisStore:
    return AnalysisStore(get_settings().database_path)
