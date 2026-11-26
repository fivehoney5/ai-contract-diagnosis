from app.clients.law import LawApiClient
from app.clients.public_data import PublicDataClient
from app.core.config import get_settings


def get_law_client() -> LawApiClient:
    return LawApiClient(get_settings())


def get_public_data_client() -> PublicDataClient:
    return PublicDataClient(get_settings())
