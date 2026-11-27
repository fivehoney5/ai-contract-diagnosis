from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 저장소 루트의 .env를 읽습니다 (backend/app/core/config.py 기준 세 단계 위).
ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "전세사기 조기경보 서비스 API"
    api_prefix: str = "/api"
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    llm_api_key: str = ""

    # 국가법령정보 공동활용
    law_api_oc: str = ""
    law_api_base_url: str = "https://www.law.go.kr/DRF"

    # 공공데이터포털
    public_data_api_key: str = ""
    public_data_base_url: str = "https://apis.data.go.kr"

    external_api_timeout: float = 10.0

    # 분석 결과 저장 (backend/var/는 .gitignore의 var/에 포함)
    database_path: str = str(BACKEND_DIR / "var" / "analyses.db")
    max_upload_mb: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()
