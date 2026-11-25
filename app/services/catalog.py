# app/services/catalog.py

import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas as S
from app.core.constants import GENRE_NAMES, MAX_ANON_INTERACTIONS, TTL
from app.core.context import UserContext
from app.core.errors import AppError, BadRequestError, NotFoundError
from app.infra.cache import Cache, cache_key
from app.infra.tmdb import TMDBClient
from app.models import Content
from app.repositories.content import ContentRepository, Criteria
from app.repositories.interactions import InteractionRepository
from app.services.mappers import parse_tmdb_row, to_cards
from app.utils import normalize_query

logger = logging.getLogger("app.catalog")
SEARCH_PAGE_SIZE = 20


def genre_names(slugs: str | None) -> list[str]:
    if not slugs:
        return []
    names = [part.strip().replace("_", " ").title() for part in slugs.split(",") if part.strip()][:5]
    unknown = [n for n in names if n not in GENRE_NAMES]
    if unknown:
        raise BadRequestError("Unknown genre", details={"genres": unknown})
    return names


class CatalogService:
    def __init__(self, session: AsyncSession, tmdb: TMDBClient, cache: Cache):
        self.session = session
        self.tmdb = tmdb
        self.cache = cache
        self.content = ContentRepository(session)
        self.interactions = InteractionRepository(session)

    async def stage(self, raw_items: Iterable[dict], default_type: str | None = None) -> list[Content]:
        buckets: dict[str, dict[int, dict]] = {"movie": {}, "tv": {}}
        order: list[tuple[str, int]] = []
        for item in raw_items:
            media, tmdb_id = item.get("media_type") or default_type, item.get("id")
            if media in buckets and isinstance(tmdb_id, int) and tmdb_id > 0 and tmdb_id not in buckets[media]:
                buckets[media][tmdb_id] = parse_tmdb_row(item, media)
                order.append((media, tmdb_id))
        lookup: dict[tuple[str, int], Content] = {}
        for media, rows in buckets.items():
            for content in await self.content.upsert_many(media, rows):
                lookup[(media, content.tmdb_id)] = content
        return [lookup[key] for key in order if key in lookup]

    async def ingest(self, raw_items: Iterable[dict], default_type: str | None = None) -> list[Content]:
        contents = await self.stage(raw_items, default_type)
        await self.session.commit()
        return contents

    async def browse(
        self,
        content_type: str,
        genres: list[str],
        language: str | None,
        year: int | None,
        sort: str,
        page: int,
        limit: int,
        min_runtime: int | None,
        max_runtime: int | None,
    ) -> tuple[list[S.ContentCard], bool]:
        criteria = Criteria(
            content_type=content_type,
            genres=genres or None,
            languages=[language] if language else None,
            year=year,
            min_runtime=min_runtime,
            max_runtime=max_runtime,
        )
        if (
            page == 1
            and not (genres or language or year)
            and not await self.content.find(Criteria(content_type=content_type), limit=1)
        ):
            await self._populate(content_type)
        rows = await self.content.find(criteria, order=sort, limit=limit + 1, offset=(page - 1) * limit)
        return to_cards(rows[:limit]), len(rows) > limit

    async def _populate(self, content_type: str) -> None:
        try:
            payload = await self.tmdb.discover(content_type, vote_count_gte=100 if content_type == "movie" else 50)
            await self.ingest(payload.get("results", []), content_type)
        except AppError:
            logger.warning("initial_population_failed", extra={"content_type": content_type})

    async def search(
        self,
        query: str,
        page: int,
        content_type: str,
        genre: str | None,
        language: str | None,
        year: int | None,
        min_rating: float | None,
        session_id: str,
        ctx: UserContext,
    ) -> S.ContentSearchOut:
        genre_filter = genre_names(genre)
        key = cache_key("search", normalize_query(query), content_type, page)

        async def build() -> dict:
            return (await self._search_upstream(query, page, content_type)).model_dump(mode="json")

        result = S.ContentSearchOut.model_validate(await self.cache.single_flight(key, TTL["search"], build))
        items = result.items
        if genre_filter:
            items = [c for c in items if set(genre_filter) & set(c.genres)]
        if language:
            items = [c for c in items if language in c.languages]
        if year:
            items = [c for c in items if c.year == year]
        if min_rating is not None:
            items = [c for c in items if c.rating is not None and c.rating >= min_rating]
        result.items = self._boost(items, ctx)
        if genre_filter or language or year or min_rating is not None:
            result.total, result.total_pages = len(items), (len(items) + SEARCH_PAGE_SIZE - 1) // SEARCH_PAGE_SIZE
        if page == 1 and result.items:
            top = result.items[0]
            await self.interactions.add_transient(
                session_id,
                top.id,
                "search",
                {
                    "query": query[:200],
                    "genres": top.genres,
                    "languages": top.languages,
                    "content_type": top.content_type,
                },
                MAX_ANON_INTERACTIONS,
            )
            await self.session.commit()
        return result

    async def _search_upstream(self, query: str, page: int, content_type: str) -> S.ContentSearchOut:
        try:
            payload = await self.tmdb.search_multi(query, page)
        except AppError:
            rows = await self.content.find(
                Criteria(title_like=query, content_type=None if content_type == "all" else content_type),
                limit=SEARCH_PAGE_SIZE,
            )
            return S.ContentSearchOut(items=to_cards(rows), total=len(rows), page=page, total_pages=1, query=query)
        wanted = [
            i
            for i in payload.get("results", [])
            if i.get("media_type") in ("movie", "tv") and content_type in ("all", i["media_type"])
        ]
        contents = await self.ingest(wanted)
        return S.ContentSearchOut(
            items=to_cards(contents),
            total=payload.get("total_results", 0),
            page=page,
            total_pages=payload.get("total_pages", 0),
            query=query,
        )

    @staticmethod
    def _boost(items: list[S.ContentCard], ctx: UserContext) -> list[S.ContentCard]:
        if len(items) < 2:
            return items
        top2, own = set(ctx.languages[:2]), set(ctx.indian_languages)

        def key(pair: tuple[int, S.ContentCard]) -> float:
            first = pair[1].languages[0] if pair[1].languages else None
            return pair[0] - (3.0 if first in top2 else 1.5 if first in own else 0.0)

        return [card for _, card in sorted(enumerate(items), key=key)]

    async def suggest(self, query: str, limit: int) -> list[str]:
        return await self.content.suggest_titles(normalize_query(query), limit)

    async def trending_searches(self, limit: int) -> list[S.SearchTermOut]:
        since = datetime.now(UTC) - timedelta(days=7)
        return [
            S.SearchTermOut(query=term, count=hits)
            for term, hits in await self.interactions.popular_searches(since, limit)
        ]

    async def videos(self, tmdb_id: int, content_type: str) -> S.VideosOut:
        key = cache_key("videos", tmdb_id, content_type)

        async def build() -> dict:
            payload = await self.tmdb.videos("tv" if content_type == "tv" else "movie", tmdb_id)
            videos = [
                S.VideoItemOut(
                    key=v.get("key"),
                    name=v.get("name", ""),
                    type=v.get("type", ""),
                    official=v.get("official", False),
                    published_at=v.get("published_at"),
                    size=v.get("size", 0),
                )
                for v in payload.get("results", [])
                if v.get("site") == "YouTube"
            ]
            videos.sort(key=lambda v: (v.type != "Trailer", not v.official, v.type != "Teaser", v.type != "Clip"))
            return S.VideosOut(tmdb_id=tmdb_id, content_type=content_type, videos=videos, total=len(videos)).model_dump(
                mode="json"
            )

        return S.VideosOut.model_validate(await self.cache.single_flight(key, TTL["videos"], build))

    async def _require(self, content_id: int) -> Content:
        content = await self.content.get(content_id)
        if content is None:
            raise NotFoundError("Content not found")
        return content

    async def add_to_list(self, session_id: str, content_id: int, kind: str) -> S.MessageOut:
        content = await self._require(content_id)
        await self.interactions.add_list_item(
            session_id,
            content.id,
            kind,
            {"content_type": content.content_type, "genres": content.genres, "languages": content.languages},
        )
        await self.session.commit()
        return S.MessageOut(detail=f"Added to {kind}")

    async def remove_from_list(self, session_id: str, content_id: int, kind: str) -> S.MessageOut:
        content = await self._require(content_id)
        removed = await self.interactions.remove(session_id, content.id, kind)
        await self.session.commit()
        if not removed:
            raise NotFoundError(f"{kind} entry not found")
        return S.MessageOut(detail=f"Removed from {kind}")

    async def my_list(self, session_id: str, kind: str, page: int, limit: int) -> S.WatchlistOut:
        ids, total = await self.interactions.page_content_ids(session_id, kind, limit, (page - 1) * limit)
        return S.WatchlistOut(items=to_cards(await self.content.get_many(ids)), total=total, page=page, limit=limit)

    async def record_view(self, session_id: str, content_id: int, content_type: str) -> S.MessageOut:
        content = await self._require(content_id)
        await self.interactions.add_transient(
            session_id,
            content.id,
            "view",
            {"content_type": content_type, "genres": content.genres, "languages": content.languages},
            MAX_ANON_INTERACTIONS,
        )
        await self.session.commit()
        return S.MessageOut(detail="View recorded")
