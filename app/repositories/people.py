# app/repositories/people.py

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ContentPerson, Person


class PersonRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def by_tmdb_ids(self, tmdb_ids: Sequence[int]) -> dict[int, Person]:
        rows = await self.session.execute(select(Person).where(Person.tmdb_id.in_(list(tmdb_ids))))
        return {p.tmdb_id: p for p in rows.scalars()}

    async def by_ids(self, ids: Sequence[int]) -> dict[int, Person]:
        rows = await self.session.execute(select(Person).where(Person.id.in_(list(ids))))
        return {p.id: p for p in rows.scalars()}

    async def get_by_tmdb(self, tmdb_id: int) -> Person | None:
        return (await self.session.execute(select(Person).where(Person.tmdb_id == tmdb_id))).scalar_one_or_none()

    async def add_many(self, persons: list[Person]) -> bool:
        try:
            async with self.session.begin_nested():
                self.session.add_all(persons)
                await self.session.flush()
            return True
        except SQLAlchemyError:
            return False

    async def create(self, person: Person) -> Person:
        try:
            async with self.session.begin_nested():
                self.session.add(person)
                await self.session.flush()
            return person
        except IntegrityError:
            existing = await self.get_by_tmdb(person.tmdb_id)
            if existing is None:
                raise
            return existing

    async def links_for_content(self, content_id: int) -> list[ContentPerson]:
        stmt = (
            select(ContentPerson)
            .where(ContentPerson.content_id == content_id)
            .order_by(ContentPerson.order.asc().nulls_last())
        )
        return list((await self.session.execute(stmt)).scalars())

    async def add_links(self, links: list[ContentPerson]) -> bool:
        try:
            async with self.session.begin_nested():
                self.session.add_all(links)
                await self.session.flush()
            return True
        except IntegrityError:
            return False
