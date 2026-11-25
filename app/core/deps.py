# app/core/deps.py

from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.constants import INDIA_TIMEZONES
from app.core.context import UserContext, resolve_languages
from app.core.security import is_legacy_session_id, new_session_id, sign_session, verify_session
from app.db.session import get_session
from app.infra.cache import Cache
from app.infra.tmdb import TMDBClient
from app.recommender.engine import Recommender
from app.services.catalog import CatalogService
from app.services.details import DetailService
from app.services.discovery import DiscoveryService
from app.services.geo import GeoService
from app.services.person import PersonService
from app.services.recommendation import RecommendationService
from app.utils import parse_accept_language

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_cache(request: Request) -> Cache:
    return request.app.state.cache


def get_tmdb(request: Request) -> TMDBClient:
    return request.app.state.tmdb


def get_recommender(request: Request) -> Recommender:
    return request.app.state.recommender


def get_geo(request: Request) -> GeoService:
    return request.app.state.geo


CacheDep = Annotated[Cache, Depends(get_cache)]
TMDBDep = Annotated[TMDBClient, Depends(get_tmdb)]
RecommenderDep = Annotated[Recommender, Depends(get_recommender)]
GeoDep = Annotated[GeoService, Depends(get_geo)]


def get_session_id(request: Request, response: Response, settings: SettingsDep) -> str:
    cached = getattr(request.state, "session_id", None)
    if cached:
        return cached
    key = settings.SECRET_KEY.get_secret_value().encode()
    cookie = request.cookies.get("cb_session")
    session_id = verify_session(cookie, key)
    reissue = False
    if session_id is None and settings.ACCEPT_LEGACY_SESSIONS and is_legacy_session_id(cookie):
        session_id, reissue = cookie, True
    if session_id is None:
        session_id, reissue = new_session_id(), True
    if reissue:
        response.set_cookie(
            "cb_session",
            sign_session(session_id, key),
            max_age=settings.COOKIE_MAX_AGE,
            httponly=True,
            samesite=settings.COOKIE_SAMESITE,
            secure=settings.cookie_secure,
        )
    request.state.session_id = session_id
    return session_id


SessionIdDep = Annotated[str, Depends(get_session_id)]


def _timezone(request: Request) -> str | None:
    raw = request.headers.get("X-Timezone") or request.query_params.get("timezone")
    if not raw or len(raw) > 64:
        return None
    if raw not in INDIA_TIMEZONES:
        try:
            ZoneInfo(raw)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            return None
    return raw


async def get_user_context(request: Request, session_id: SessionIdDep, geo: GeoDep) -> UserContext:
    cached = getattr(request.state, "user_context", None)
    if cached:
        return cached
    client = request.client.host if request.client else None
    located = await geo.locate(request.headers, client)
    timezone = _timezone(request)
    country = located.get("country") or ("IN" if timezone in INDIA_TIMEZONES else "")
    explicit = (
        request.query_params.get("languages")
        or request.query_params.get("preferred_languages")
        or request.cookies.get("cb_languages")
        or request.headers.get("X-Preferred-Languages")
    )
    languages, source = resolve_languages(
        explicit=explicit.split(",") if explicit else None,
        accept=parse_accept_language(request.headers.get("Accept-Language")),
        geo_langs=located.get("languages"),
        country=country,
    )
    context = UserContext(
        session_id, country, located.get("region", ""), located.get("city", ""), tuple(languages), source, timezone
    )
    request.state.user_context = context
    return context


UserContextDep = Annotated[UserContext, Depends(get_user_context)]


def get_catalog_service(session: SessionDep, tmdb: TMDBDep, cache: CacheDep) -> CatalogService:
    return CatalogService(session, tmdb, cache)


def get_detail_service(session: SessionDep, tmdb: TMDBDep, cache: CacheDep) -> DetailService:
    return DetailService(session, tmdb, cache)


def get_person_service(session: SessionDep, tmdb: TMDBDep, cache: CacheDep) -> PersonService:
    return PersonService(session, tmdb, cache)


def get_recommendation_service(
    request: Request, session: SessionDep, cache: CacheDep, recommender: RecommenderDep
) -> RecommendationService:
    return RecommendationService(session, cache, recommender)


def get_discovery_service(
    request: Request, session: SessionDep, cache: CacheDep, recommender: RecommenderDep
) -> DiscoveryService:
    return DiscoveryService(session, cache, recommender, request.app.state.session_factory)


CatalogDep = Annotated[CatalogService, Depends(get_catalog_service)]
DetailDep = Annotated[DetailService, Depends(get_detail_service)]
PersonDep = Annotated[PersonService, Depends(get_person_service)]
RecoDep = Annotated[RecommendationService, Depends(get_recommendation_service)]
DiscoveryDep = Annotated[DiscoveryService, Depends(get_discovery_service)]
