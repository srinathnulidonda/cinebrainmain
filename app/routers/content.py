# app/routers/content.py

from typing import Annotated

from fastapi import APIRouter, Query

from app import schemas as S
from app.core.constants import GENRE_MAP
from app.core.deps import CatalogDep, DetailDep, PersonDep, RecoDep, SessionIdDep, UserContextDep
from app.core.errors import BadRequestError
from app.routers.common import (
    ContentId,
    GenreList,
    Lang,
    Limit,
    ListKind,
    MediaFilter,
    MediaType,
    Page,
    SortKey,
    TextQuery,
    TmdbId,
    Year,
    ok,
)
from app.services.catalog import genre_names

router = APIRouter(prefix="/content", tags=["content"])
DETAIL_FIELDS = {
    "cast_crew",
    "gallery",
    "similar",
    "streaming_info",
    "ratings",
    "metadata",
    "synopsis",
    "seasons_episodes",
    "trailer",
}


@router.get("/search", response_model=S.Envelope[S.ContentSearchOut])
async def search(
    service: CatalogDep,
    ctx: UserContextDep,
    session_id: SessionIdDep,
    query: TextQuery,
    page: Page = 1,
    content_type: MediaFilter = "all",
    genre: GenreList | None = None,
    language: Lang | None = None,
    year: Year | None = None,
    min_rating: Annotated[float | None, Query(ge=0, le=10)] = None,
):
    result = await service.search(query, page, content_type, genre, language, year, min_rating, session_id, ctx)
    return ok(result, page=result.page, limit=20, has_more=result.page < result.total_pages, total=result.total)


@router.get("/search/suggest", response_model=S.Envelope[list[str]])
async def suggest(
    service: CatalogDep,
    query: Annotated[str, Query(min_length=1, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
):
    return ok(await service.suggest(query, limit))


@router.get("/search/trending", response_model=S.Envelope[list[S.SearchTermOut]])
async def trending_searches(service: CatalogDep, limit: Annotated[int, Query(ge=1, le=20)] = 10):
    return ok(await service.trending_searches(limit))


@router.get("/feels-like", response_model=S.Envelope[S.FeelsLikeOut])
async def feels_like(
    service: RecoDep,
    query: Annotated[str, Query(min_length=2, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
):
    return ok(await service.feels_like(query, limit))


@router.get("/browse/genres", response_model=S.Envelope[list[S.GenreOut]])
async def browse_genres():
    return ok([S.GenreOut(id=gid, name=name) for gid, name in sorted(GENRE_MAP.items(), key=lambda item: item[1])])


@router.get("/browse/{content_type}", response_model=S.Envelope[list[S.ContentCard]])
async def browse(
    service: CatalogDep,
    content_type: MediaType,
    genre: GenreList | None = None,
    language: Lang | None = None,
    year: Year | None = None,
    sort: SortKey = "popularity",
    page: Page = 1,
    limit: Limit = 24,
    min_runtime: Annotated[int | None, Query(ge=15, le=600)] = None,
    max_runtime: Annotated[int | None, Query(ge=15, le=600)] = None,
):
    items, has_more = await service.browse(
        content_type, genre_names(genre), language, year, sort, page, limit, min_runtime, max_runtime
    )
    return ok(items, page=page, limit=limit, has_more=has_more)


@router.get("/me/watchlist", response_model=S.Envelope[S.WatchlistOut])
async def my_watchlist(service: CatalogDep, session_id: SessionIdDep, page: Page = 1, limit: Limit = 50):
    result = await service.my_list(session_id, "watchlist", page, limit)
    return ok(result, page=page, limit=limit, has_more=page * limit < result.total, total=result.total)


@router.get("/me/favorites", response_model=S.Envelope[S.WatchlistOut])
async def my_favorites(service: CatalogDep, session_id: SessionIdDep, page: Page = 1, limit: Limit = 50):
    result = await service.my_list(session_id, "favorite", page, limit)
    return ok(result, page=page, limit=limit, has_more=page * limit < result.total, total=result.total)


@router.get("/me/history", response_model=S.Envelope[S.WatchlistOut])
async def my_history(service: CatalogDep, session_id: SessionIdDep, page: Page = 1, limit: Limit = 50):
    result = await service.my_list(session_id, "view", page, limit)
    return ok(result, page=page, limit=limit, has_more=page * limit < result.total, total=result.total)


@router.get("/person/{tmdb_id}", response_model=S.Envelope[S.PersonDetailOut])
async def person(service: PersonDep, tmdb_id: TmdbId):
    return ok(await service.get(tmdb_id))


@router.get("/{tmdb_id}/videos", response_model=S.Envelope[S.VideosOut])
async def videos(service: CatalogDep, tmdb_id: TmdbId, content_type: MediaType = "movie"):
    return ok(await service.videos(tmdb_id, content_type))


@router.get("/{tmdb_id}", response_model=S.Envelope[S.ContentDetailOut])
async def detail(
    service: DetailDep,
    session_id: SessionIdDep,
    tmdb_id: TmdbId,
    content_type: MediaType = "movie",
    fields: Annotated[str | None, Query(max_length=200)] = None,
):
    requested = {f.strip() for f in (fields or "").split(",") if f.strip()}
    if unknown := requested - DETAIL_FIELDS:
        raise BadRequestError("Unknown field", details={"fields": sorted(unknown)})
    return ok(await service.get(tmdb_id, content_type, session_id, requested or None))


@router.post("/{content_id}/view", response_model=S.Envelope[S.MessageOut])
async def record_view(
    service: CatalogDep, session_id: SessionIdDep, content_id: ContentId, content_type: MediaType = "movie"
):
    return ok(await service.record_view(session_id, content_id, content_type))


@router.post("/{content_id}/{kind}", response_model=S.Envelope[S.MessageOut], status_code=200)
async def add_to_list(service: CatalogDep, session_id: SessionIdDep, content_id: ContentId, kind: ListKind):
    return ok(await service.add_to_list(session_id, content_id, kind))


@router.delete("/{content_id}/{kind}", response_model=S.Envelope[S.MessageOut])
async def remove_from_list(service: CatalogDep, session_id: SessionIdDep, content_id: ContentId, kind: ListKind):
    return ok(await service.remove_from_list(session_id, content_id, kind))
