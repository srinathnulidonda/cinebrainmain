# app/routers/__init__.py

from fastapi import APIRouter

from app.routers import content, discovery, recommendations

api_router = APIRouter()
api_router.include_router(content.router)
api_router.include_router(discovery.router)
api_router.include_router(recommendations.router)
