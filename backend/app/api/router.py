from fastapi import APIRouter

from app.api.routes import analyses, external, health

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(external.router)
api_router.include_router(analyses.router)
