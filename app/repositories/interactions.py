# app/repositories/interactions.py

from collections.abc import AsyncIterator
from datetime import datetime

from sqlalchemy import delete, desc, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AnonymousInteraction as AI

TRANSIENT_KINDS = ("view", "search")
LIST_KINDS = ("watchlist", "favorite")


class InteractionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add_transient(self, session_id: str, content_id: int, kind: str, metadata: dict | None, cap: int) -> None:
        self.session.add(
            AI(session_id=session_id, content_id=content_id, interaction_type=kind, interaction_metadata=metadata)
        )
        await self.session.flush()
        stale = (
            select(AI.id)
            .where(AI.session_id == session_id, AI.interaction_type.in_(TRANSIENT_KINDS))
            .order_by(AI.timestamp.desc(), AI.id.desc())
            .offset(cap)
        )
        await self.session.execute(delete(AI).where(AI.id.in_(stale)))

    async def add_list_item(self, session_id: str, content_id: int, kind: str, metadata: dict | None) -> bool:
        stmt = (
            insert(AI)
            .values(session_id=session_id, content_id=content_id, interaction_type=kind, interaction_metadata=metadata)
            .on_conflict_do_nothing(
                index_elements=["session_id", "content_id", "interaction_type"],
                index_where=text("interaction_type IN ('watchlist','favorite')"),
            )
        )
        return (await self.session.execute(stmt)).rowcount > 0

    async def remove(self, session_id: str, content_id: int, kind: str) -> int:
        stmt = delete(AI).where(AI.session_id == session_id, AI.content_id == content_id, AI.interaction_type == kind)
        return (await self.session.execute(stmt)).rowcount

    async def page_content_ids(self, session_id: str, kind: str, limit: int, offset: int) -> tuple[list[int], int]:
        latest = (
            select(AI.content_id, func.max(AI.timestamp).label("latest"))
            .where(AI.session_id == session_id, AI.interaction_type == kind)
            .group_by(AI.content_id)
            .subquery()
        )
        total = await self.session.scalar(select(func.count()).select_from(latest)) or 0
        if not total:
            return [], 0
        stmt = (
            select(latest.c.content_id)
            .order_by(latest.c.latest.desc(), latest.c.content_id)
            .offset(offset)
            .limit(limit)
        )
        return [row[0] for row in (await self.session.execute(stmt)).all()], total

    async def recent(self, session_id: str, limit: int) -> list:
        stmt = (
            select(AI.content_id, AI.interaction_type, AI.interaction_metadata, AI.timestamp)
            .where(AI.session_id == session_id)
            .order_by(AI.timestamp.desc(), AI.id.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).all())

    async def popular_searches(self, since: datetime, limit: int) -> list[tuple[str, int]]:
        term = func.lower(AI.interaction_metadata["query"].astext)
        stmt = (
            select(term.label("term"), func.count().label("hits"))
            .where(AI.interaction_type == "search", AI.timestamp >= since, term.isnot(None))
            .group_by(term)
            .order_by(desc("hits"), term)
            .limit(limit)
        )
        return [(row.term, row.hits) for row in (await self.session.execute(stmt)).all()]

    async def stream_for_model(self, since: datetime, max_rows: int, chunk: int = 50_000) -> AsyncIterator[list]:
        stmt = (
            select(AI.session_id, AI.content_id, AI.interaction_type, AI.timestamp)
            .where(AI.timestamp >= since)
            .order_by(AI.timestamp.desc())
            .limit(max_rows)
            .execution_options(stream_results=True)
        )
        result = await self.session.stream(stmt)
        async for partition in result.partitions(chunk):
            yield partition

    async def engagement_since(self, since: datetime) -> list[tuple[int, str, int]]:
        stmt = (
            select(AI.content_id, AI.interaction_type, func.count())
            .where(AI.timestamp >= since)
            .group_by(AI.content_id, AI.interaction_type)
        )
        return [(row[0], row[1], row[2]) for row in (await self.session.execute(stmt)).all()]
