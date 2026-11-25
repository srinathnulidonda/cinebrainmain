# app/repositories/content.py

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import true

from app.models import Content

Order = Literal["popularity", "rating", "release_date", "release_asc", "alpha"]
_ORDERS = {
    "popularity": (Content.popularity.desc(),),
    "rating": (Content.rating.desc().nulls_last(), Content.vote_count.desc()),
    "release_date": (Content.release_date.desc().nulls_last(), Content.popularity.desc()),
    "release_asc": (Content.release_date.asc(), Content.popularity.desc()),
    "alpha": (Content.title.asc(),),
}
SNAPSHOT_COLUMNS = (
    Content.id,
    Content.content_type,
    Content.genres,
    Content.languages,
    Content.release_date,
    Content.rating,
    Content.vote_count,
    Content.popularity,
    Content.poster_path,
    Content.is_trending,
)


@dataclass(slots=True)
class Criteria:
    content_type: str | None = None
    languages: Sequence[str] | None = None
    genres: Sequence[str] | None = None
    released_from: date | None = None
    released_to: date | None = None
    released_after: date | None = None
    year: int | None = None
    min_rating: float | None = None
    min_votes: int | None = None
    max_votes: int | None = None
    max_popularity: float | None = None
    min_runtime: int | None = None
    max_runtime: int | None = None
    trending: bool | None = None
    require_poster: bool = False
    require_backdrop: bool = False
    exclude_ids: Sequence[int] | None = None
    ids: Sequence[int] | None = None
    title_like: str | None = None


def _overlap(column, values: Sequence[str]):
    return or_(*[column.contains([v]) for v in values]) if values else true()


def _clause(c: Criteria):
    conditions = []
    if c.content_type:
        conditions.append(Content.content_type == c.content_type)
    if c.languages:
        conditions.append(_overlap(Content.languages, c.languages))
    if c.genres:
        conditions.append(_overlap(Content.genres, c.genres))
    if c.released_from:
        conditions.append(Content.release_date >= c.released_from)
    if c.released_to:
        conditions.append(Content.release_date <= c.released_to)
    if c.released_after:
        conditions.append(Content.release_date > c.released_after)
    if c.year:
        conditions += [Content.release_date >= date(c.year, 1, 1), Content.release_date < date(c.year + 1, 1, 1)]
    if c.min_rating is not None:
        conditions.append(Content.rating >= c.min_rating)
    if c.min_votes is not None:
        conditions.append(Content.vote_count >= c.min_votes)
    if c.max_votes is not None:
        conditions.append(Content.vote_count <= c.max_votes)
    if c.max_popularity is not None:
        conditions.append(Content.popularity <= c.max_popularity)
    if c.min_runtime is not None:
        conditions.append(Content.runtime >= c.min_runtime)
    if c.max_runtime is not None:
        conditions.append(Content.runtime <= c.max_runtime)
    if c.trending is not None:
        conditions.append(Content.is_trending.is_(c.trending))
    if c.require_poster:
        conditions.append(Content.poster_path.isnot(None))
    if c.require_backdrop:
        conditions.append(Content.backdrop_path.isnot(None))
    if c.exclude_ids:
        conditions.append(Content.id.not_in(list(c.exclude_ids)))
    if c.ids is not None:
        conditions.append(Content.id.in_(list(c.ids)))
    if c.title_like:
        escaped = c.title_like.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        conditions.append(Content.title.ilike(f"%{escaped}%", escape="\\"))
    return and_(*conditions) if conditions else true()


class ContentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, content_id: int) -> Content | None:
        return await self.session.get(Content, content_id)

    async def get_by_tmdb(self, tmdb_id: int, content_type: str) -> Content | None:
        stmt = select(Content).where(Content.tmdb_id == tmdb_id, Content.content_type == content_type)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_many(self, ids: Sequence[int]) -> list[Content]:
        if not ids:
            return []
        rows = (await self.session.execute(select(Content).where(Content.id.in_(list(ids))))).scalars()
        by_id = {c.id: c for c in rows}
        return [by_id[i] for i in ids if i in by_id]

    async def find(
        self, *criteria: Criteria, order: Order = "popularity", limit: int = 20, offset: int = 0
    ) -> list[Content]:
        clause = (
            or_(*[_clause(c) for c in criteria])
            if len(criteria) > 1
            else _clause(criteria[0] if criteria else Criteria())
        )
        stmt = select(Content).where(clause).order_by(*_ORDERS[order], Content.id.asc()).offset(offset).limit(limit)
        return list((await self.session.execute(stmt)).scalars())

    async def tmdb_index(self, tmdb_ids: Sequence[int], content_type: str) -> dict[int, Content]:
        if not tmdb_ids:
            return {}
        stmt = select(Content).where(Content.tmdb_id.in_(list(tmdb_ids)), Content.content_type == content_type)
        return {c.tmdb_id: c for c in (await self.session.execute(stmt)).scalars()}

    async def upsert_many(self, content_type: str, rows: dict[int, dict]) -> list[Content]:
        if not rows:
            return []
        found = await self.tmdb_index(list(rows), content_type)
        missing = [tid for tid in rows if tid not in found]
        if missing:
            stmt = insert(Content).values([rows[tid] for tid in missing])
            await self.session.execute(stmt.on_conflict_do_nothing(index_elements=["tmdb_id", "content_type"]))
            await self.session.flush()
            found.update(await self.tmdb_index(missing, content_type))
        return [found[tid] for tid in rows if tid in found]

    async def suggest_titles(self, needle: str, limit: int) -> list[str]:
        escaped = needle.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        out: dict[str, str] = {}
        for pattern in (f"{escaped}%", f"%{escaped}%"):
            stmt = (
                select(Content.title)
                .where(Content.title.ilike(pattern, escape="\\"))
                .order_by(Content.popularity.desc())
                .limit(limit * 3)
            )
            for title in (await self.session.execute(stmt)).scalars():
                out.setdefault(title.lower(), title)
            if len(out) >= limit:
                break
        return list(out.values())[:limit]

    async def snapshot(self, limit: int, today: date) -> list:
        stmt = (
            select(*SNAPSHOT_COLUMNS)
            .where(or_(Content.release_date.is_(None), Content.release_date <= today))
            .order_by(Content.popularity.desc(), Content.id.asc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).all())

    async def refresh_flags(
        self, trending_ids: set[int], today: date, window_days: int, min_rating: float, min_votes: int
    ) -> None:
        cutoff = today - timedelta(days=window_days)
        if trending_ids:
            ids = list(trending_ids)
            await self.session.execute(
                update(Content).where(Content.id.in_(ids), Content.is_trending.is_(False)).values(is_trending=True)
            )
            await self.session.execute(
                update(Content).where(Content.is_trending.is_(True), Content.id.not_in(ids)).values(is_trending=False)
            )
        fresh = and_(Content.release_date >= cutoff, Content.release_date <= today)
        critic = and_(Content.rating >= min_rating, Content.vote_count >= min_votes)
        for column, on, off in (
            (
                Content.is_new_release,
                fresh,
                or_(Content.release_date < cutoff, Content.release_date > today, Content.release_date.is_(None)),
            ),
            (
                Content.is_critics_choice,
                critic,
                or_(Content.rating.is_(None), Content.rating < min_rating, Content.vote_count < min_votes),
            ),
        ):
            await self.session.execute(update(Content).where(on, column.is_(False)).values({column.key: True}))
            await self.session.execute(update(Content).where(column.is_(True), off).values({column.key: False}))
