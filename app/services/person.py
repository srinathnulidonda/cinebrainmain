# app/services/person.py

from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas as S
from app.core.constants import KNOWN_FOR_LIMIT, TTL
from app.core.errors import NotFoundError, UpstreamNotFound
from app.infra.cache import Cache, cache_key
from app.infra.tmdb import TMDBClient
from app.models import Person
from app.repositories.people import PersonRepository
from app.services import mappers as M
from app.utils import parse_iso_date


class PersonService:
    def __init__(self, session: AsyncSession, tmdb: TMDBClient, cache: Cache):
        self.session = session
        self.tmdb = tmdb
        self.cache = cache
        self.people = PersonRepository(session)

    async def get(self, tmdb_id: int) -> S.PersonDetailOut:
        async def build() -> dict:
            try:
                raw = await self.tmdb.person(tmdb_id)
            except UpstreamNotFound as exc:
                raise NotFoundError("Person not found") from exc
            person = await self._upsert(raw)
            await self.session.commit()
            return M.person_detail(person, raw, M.build_filmography(raw), KNOWN_FOR_LIMIT).model_dump(mode="json")

        return S.PersonDetailOut.model_validate(
            await self.cache.single_flight(cache_key("person", tmdb_id), TTL["person"], build)
        )

    async def _upsert(self, raw: dict) -> Person:
        tmdb_id = raw.get("id", 0)
        person = await self.people.get_by_tmdb(tmdb_id)
        incoming = {
            "name": raw.get("name"),
            "biography": raw.get("biography"),
            "birthday": parse_iso_date(raw.get("birthday")),
            "deathday": parse_iso_date(raw.get("deathday")),
            "place_of_birth": raw.get("place_of_birth"),
            "profile_path": raw.get("profile_path"),
            "backdrop_path": raw.get("backdrop_path"),
            "known_for_department": raw.get("known_for_department"),
        }
        if person:
            for field, value in incoming.items():
                setattr(person, field, value or getattr(person, field))
            person.popularity = raw.get("popularity", person.popularity)
            person.gender = raw.get("gender", person.gender)
            person.also_known_as = list(raw.get("also_known_as") or person.also_known_as or [])
            await self.people.session.flush()
            return person
        return await self.people.create(
            Person(
                tmdb_id=tmdb_id,
                popularity=raw.get("popularity", 0.0),
                gender=raw.get("gender"),
                also_known_as=raw.get("also_known_as", []),
                **{**incoming, "name": incoming["name"] or ""},
            )
        )
