# app/routers/discovery.py

from typing import Annotated

from fastapi import APIRouter, Query

from app import schemas as S
from app.core.deps import DiscoveryDep, RecoDep, UserContextDep
from app.routers.common import (
    FeedLanguage,
    Lang,
    LanguageList,
    Limit,
    MediaFilter,
    Mood,
    Page,
    Situation,
    Slug,
    SortKey,
    Year,
    ok,
)
from app.utils import normalize_langs

router = APIRouter(prefix="/discovery", tags=["discovery"])


@router.get("/context", response_model=S.Envelope[S.UserContextOut])
async def resolved_context(ctx: UserContextDep):
    return ok(
        S.UserContextOut(
            country=ctx.country or None,
            region=ctx.region or None,
            city=ctx.city or None,
            languages=ctx.lang_list,
            language_source=ctx.language_source,
            timezone=ctx.timezone,
        )
    )


@router.get("/home", response_model=S.Envelope[S.HomeFeedOut])
async def home(service: DiscoveryDep, ctx: UserContextDep):
    return ok(await service.home(ctx))


@router.get("/decide", response_model=S.Envelope[S.DecideOut])
async def decide(
    service: RecoDep,
    ctx: UserContextDep,
    mood: Mood | None = None,
    situation: Situation | None = None,
    max_runtime: Annotated[int | None, Query(ge=15, le=600)] = None,
    min_runtime: Annotated[int | None, Query(ge=15, le=600)] = None,
    languages: LanguageList | None = None,
):
    chosen = normalize_langs(languages.split(",")) if languages else None
    return ok(await service.decide(ctx, mood, max_runtime, min_runtime, chosen, situation))


@router.get("/hidden-gems", response_model=S.Envelope[list[S.ContentCard]])
async def hidden_gems(
    service: RecoDep, ctx: UserContextDep, page: Annotated[int, Query(ge=1, le=10)] = 1, limit: Limit = 20
):
    items, has_more = await service.hidden_gems(ctx, page, limit)
    return ok(items, page=page, limit=limit, has_more=has_more)


@router.get("/this-week", response_model=S.Envelope[S.ThisWeekOut])
async def this_week(service: DiscoveryDep, ctx: UserContextDep):
    return ok(await service.this_week(ctx.lang_list))


@router.get("/trending/local", response_model=S.Envelope[S.LocalTrendingOut])
async def trending_local(service: DiscoveryDep, ctx: UserContextDep):
    return ok(await service.local_trending(ctx))


@router.get("/trending", response_model=S.Envelope[list[S.ContentCard]])
async def trending(
    service: DiscoveryDep, ctx: UserContextDep, content_type: MediaFilter = "all", page: Page = 1, limit: Limit = 20
):
    items, has_more = await service.trending(content_type, ctx, page, limit)
    return ok(items, page=page, limit=limit, has_more=has_more)


@router.get("/latest", response_model=S.Envelope[list[S.ContentCard]])
async def latest(
    service: DiscoveryDep, ctx: UserContextDep, content_type: MediaFilter = "all", page: Page = 1, limit: Limit = 20
):
    items, has_more = await service.latest(content_type, ctx, page, limit)
    return ok(items, page=page, limit=limit, has_more=has_more)


@router.get("/new-releases", response_model=S.Envelope[list[S.ContentCard]])
async def new_releases(
    service: DiscoveryDep,
    ctx: UserContextDep,
    language: Annotated[str, Query(pattern=r"^(all|[a-z]{2,3})$")] = "all",
    page: Page = 1,
    limit: Limit = 20,
):
    items, has_more = await service.new_releases(language, ctx, page, limit)
    return ok(items, page=page, limit=limit, has_more=has_more)


@router.get("/upcoming", response_model=S.Envelope[list[S.ContentCard]])
async def upcoming(service: DiscoveryDep, ctx: UserContextDep, page: Page = 1, limit: Limit = 20):
    items, has_more = await service.upcoming(ctx.lang_list, page, limit)
    return ok(items, page=page, limit=limit, has_more=has_more)


@router.get("/critics-choice", response_model=S.Envelope[list[S.ContentCard]])
async def critics_choice(service: DiscoveryDep, ctx: UserContextDep, page: Page = 1, limit: Limit = 20):
    items, has_more = await service.critics(ctx.lang_list, page, limit)
    return ok(items, page=page, limit=limit, has_more=has_more)


@router.get("/regional/{language}", response_model=S.Envelope[S.RegionalContentOut])
async def regional(service: DiscoveryDep, language: FeedLanguage, page: Page = 1, limit: Limit = 20):
    result = await service.regional(language, page, limit)
    return ok(result, page=page, limit=limit, has_more=result.has_more)


@router.get("/genre/{genre}", response_model=S.Envelope[S.GenreContentOut])
async def genre(
    service: DiscoveryDep,
    genre: Slug,
    content_type: MediaFilter = "all",
    language: Lang | None = None,
    year: Year | None = None,
    sort: SortKey = "popularity",
    page: Page = 1,
    limit: Limit = 20,
):
    result = await service.genre(genre, content_type, language, year, sort, page, limit)
    return ok(result, page=page, limit=limit, has_more=result.has_more)
