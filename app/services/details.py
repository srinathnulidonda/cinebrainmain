# app/services/details.py

import logging
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas as S
from app.core.constants import MAX_ANON_INTERACTIONS, MAX_CAST_FETCHED, MIN_CAST_FROM_DB, SIMILAR_LIMIT, TTL
from app.core.errors import NotFoundError, UpstreamNotFound
from app.infra.cache import Cache, cache_key
from app.infra.tmdb import TMDBClient
from app.models import Content, ContentPerson, Person
from app.repositories.content import ContentRepository
from app.repositories.interactions import InteractionRepository
from app.repositories.people import PersonRepository
from app.services import mappers as M
from app.services.catalog import CatalogService
from app.utils import image_url, slugify

logger = logging.getLogger("app.details")
_PROJECTED = {
    "cast_crew": S.CastCrewOut,
    "gallery": S.GalleryOut,
    "ratings": S.RatingsOut,
    "metadata": S.MetadataOut,
    "synopsis": S.SynopsisOut,
}
_NULLABLE = ("streaming_info", "seasons_episodes", "trailer")


def project(detail: S.ContentDetailOut, fields: set[str] | None) -> S.ContentDetailOut:
    if not fields:
        return detail
    update: dict[str, Any] = {k: factory() for k, factory in _PROJECTED.items() if k not in fields}
    update.update({k: None for k in _NULLABLE if k not in fields})
    if "similar" not in fields:
        update["more_like_this"] = []
    return detail.model_copy(update=update)


class DetailService:
    def __init__(self, session: AsyncSession, tmdb: TMDBClient, cache: Cache):
        self.session = session
        self.tmdb = tmdb
        self.cache = cache
        self.content = ContentRepository(session)
        self.people = PersonRepository(session)
        self.interactions = InteractionRepository(session)
        self.catalog = CatalogService(session, tmdb, cache)

    async def get(
        self, tmdb_id: int, content_type: str, session_id: str, fields: set[str] | None
    ) -> S.ContentDetailOut:
        content = await self.content.get_by_tmdb(tmdb_id, content_type)
        if content is None:
            raise NotFoundError("Content not found")

        async def build() -> dict:
            return (await self._build(content, tmdb_id, content_type)).model_dump(mode="json")

        detail = S.ContentDetailOut.model_validate(
            await self.cache.single_flight(cache_key("detail", tmdb_id, content_type), TTL["detail"], build)
        )
        await self.interactions.add_transient(
            session_id,
            content.id,
            "view",
            {"genres": content.genres, "languages": content.languages, "content_type": content.content_type},
            MAX_ANON_INTERACTIONS,
        )
        await self.session.commit()
        return project(detail, fields)

    async def _build(self, content: Content, tmdb_id: int, content_type: str) -> S.ContentDetailOut:
        tv = content.content_type != "movie"
        append = "credits,videos,images,similar,watch/providers,keywords," + (
            "content_ratings" if tv else "release_dates"
        )
        try:
            raw = await (self.tmdb.tv if tv else self.tmdb.movie)(content.tmdb_id, append)
        except UpstreamNotFound as exc:
            raise NotFoundError("Content not found") from exc
        trailer = M.extract_trailer(raw)
        if trailer and not content.youtube_trailer_id:
            content.youtube_trailer_id = trailer.youtube_id
        cast_crew = await self._safe(self._cast_crew(raw, content), S.CastCrewOut())
        similar = await self._safe(self._similar(raw, content_type), [])
        streaming, available = M.build_streaming_info(raw)
        await self.cache.set_json(cache_key("availability", tmdb_id, content_type), available, 86400)
        metadata = M.build_metadata(raw, tv)
        metadata.is_trending, metadata.is_new_release, metadata.is_critics_choice = (
            content.is_trending,
            content.is_new_release,
            content.is_critics_choice,
        )
        await self.session.commit()
        year = content.release_date.year if content.release_date else None
        slug = slugify(content.title or "")
        return S.ContentDetailOut(
            backdrop_url=image_url("backdrop", content.backdrop_path),
            cast_crew=cast_crew,
            content_type=content.content_type,
            gallery=M.build_gallery(raw),
            id=content.id,
            metadata=metadata,
            more_like_this=similar,
            original_title=content.original_title,
            overview=content.overview,
            poster_url=image_url("poster", content.poster_path),
            ratings=M.build_ratings(raw),
            seasons_episodes=M.build_seasons_episodes(raw) if tv else None,
            slug=f"{slug}-{year}" if year else slug,
            streaming_info=streaming,
            synopsis=M.build_synopsis(raw, tv),
            title=content.title or "",
            trailer=trailer,
        )

    @staticmethod
    async def _safe(awaitable, default):
        try:
            return await awaitable
        except (SQLAlchemyError, ValueError, KeyError, AttributeError) as exc:
            logger.warning("detail_section_failed", extra={"error": type(exc).__name__})
            return default

    async def _similar(self, raw: dict, content_type: str) -> list[S.SimilarItemOut]:
        results = [i for i in (raw.get("similar") or {}).get("results", [])[:SIMILAR_LIMIT] if i.get("id")]
        return [M.similar_item(c) for c in await self.catalog.stage(results, content_type)]

    async def _cast_crew(self, raw: dict, content: Content) -> S.CastCrewOut:
        links = await self.people.links_for_content(content.id)
        if sum(link.role_type == "cast" for link in links) >= MIN_CAST_FROM_DB:
            people = await self.people.by_ids({link.person_id for link in links})
            return M.assemble_cast(
                [
                    (people[k.person_id], k.role_type, k.character, k.job, k.department, k.order)
                    for k in links
                    if k.person_id in people
                ]
            )
        credits = raw.get("credits") or {}
        cast = credits.get("cast", [])[:MAX_CAST_FETCHED]
        crew = [m for m in credits.get("crew", []) if m.get("job") in M.IMPORTANT_JOBS]
        members = {m["id"]: m for m in [*cast, *crew] if m.get("id")}
        persons = await self.people.by_tmdb_ids(list(members))
        fresh = [
            Person(
                tmdb_id=tid,
                name=m.get("name", ""),
                profile_path=m.get("profile_path"),
                popularity=m.get("popularity", 0.0),
                known_for_department=m.get("known_for_department"),
                gender=m.get("gender"),
                also_known_as=[],
            )
            for tid, m in members.items()
            if tid not in persons
        ]
        if fresh and await self.people.add_many(fresh):
            persons.update({p.tmdb_id: p for p in fresh})
        entries: dict[tuple, tuple] = {}
        for m in cast:
            if person := persons.get(m.get("id")):
                entries.setdefault(
                    (person.id, "cast", m.get("character"), None),
                    (person, "cast", m.get("character"), None, None, m.get("order")),
                )
        for m in crew:
            if person := persons.get(m.get("id")):
                entries.setdefault(
                    (person.id, "crew", None, m["job"]), (person, "crew", None, m["job"], m.get("department"), None)
                )
        have = {(k.person_id, k.role_type, k.character, k.job) for k in links}
        links_new = [
            ContentPerson(
                content_id=content.id,
                person_id=k[0],
                role_type=k[1],
                character=k[2],
                job=k[3],
                department=e[4],
                order=e[5],
            )
            for k, e in entries.items()
            if k not in have
        ]
        if links_new:
            await self.people.add_links(links_new)
        return M.assemble_cast(list(entries.values()))
