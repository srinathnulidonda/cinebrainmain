# app/routers/recommendations.py

from fastapi import APIRouter

from app import schemas as S
from app.core.deps import RecoDep, UserContextDep
from app.routers.common import ContentId, Limit, ok

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("/for-you", response_model=S.Envelope[list[S.RecommendationCard]])
async def for_you(service: RecoDep, ctx: UserContextDep, limit: Limit = 24):
    items, _ = await service.for_you(ctx, limit)
    return ok(items, page=1, limit=limit, has_more=False)


@router.get("/similar/{content_id}", response_model=S.Envelope[S.SimilarContentOut])
async def similar(service: RecoDep, content_id: ContentId, limit: Limit = 12):
    return ok(await service.similar(content_id, limit))
