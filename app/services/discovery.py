# app/services/discovery.py

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import schemas as S
from app.core import constants as K
from app.core.context import UserContext
from app.core.errors import AppError, NotFoundError
from app.infra.cache import Cache, cache_key
from app.models import Content
from app.recommender.engine import Recommender
from app.recommender.explain import build_context
from app.recommender.items import (
    CRITICS_PROFILE,
    DEFAULT_PROFILE,
    FRESH_PROFILE,
    TRENDING_PROFILE,
    UPCOMING_PROFILE,
    UserProfile,
    merge_ranked,
    rank_rows,
)
from app.repositories.content import ContentRepository, Criteria
from app.services.mappers import to_cards
from app.services.recommendation import RecommendationService
from app.utils import INDIAN_LANGS_SET, today

logger = logging.getLogger("app.discovery")
LIST_SIZE = 60
GLOBAL_TREND_WEIGHT = 0.5


def page_of(items: list, page: int, limit: int) -> tuple[list, bool]:
    start = (page - 1) * limit
    return items[start : start + limit], len(items) > start + limit


def dedupe(rows: list[Content]) -> list[Content]:
    return list({row.id: row for row in rows}.values())


class DiscoveryService:
    def __init__(
        self,
        session: AsyncSession,
        cache: Cache,
        recommender: Recommender,
        session_factory: async_sessionmaker[AsyncSession],
    ):
        self.session = session
        self.cache = cache
        self.recommender = recommender
        self.session_factory = session_factory
        self.content = ContentRepository(session)
        self.reco = RecommendationService(session, cache, recommender)

    def with_session(self, session: AsyncSession) -> "DiscoveryService":
        return DiscoveryService(session, self.cache, self.recommender, self.session_factory)

    async def _cards(
        self, key: str, ttl: int, build: Callable[[], Awaitable[list[S.ContentCard]]]
    ) -> list[S.ContentCard]:
        async def produce() -> list[dict]:
            return [c.model_dump(mode="json") for c in await build()]

        return [
            S.ContentCard.model_validate(i) for i in await self.cache.single_flight(key, ttl, produce, cacheable=bool)
        ]

    async def _model(self, key: str, ttl: int, build: Callable[[], Awaitable[Any]], model: type) -> Any:
        async def produce() -> dict:
            return (await build()).model_dump(mode="json")

        return model.model_validate(await self.cache.single_flight(key, ttl, produce))

    @staticmethod
    def _ranked_cards(rows: list[Content], languages: list[str], profile, size: int = LIST_SIZE) -> list[S.ContentCard]:
        return to_cards(row for row, _ in rank_rows(rows, UserProfile(languages=languages), profile).diversified(size))

    async def _trending_ids(self, kind: str, languages: list[str], k: int, include_global: bool) -> list[int]:
        store = self.recommender.store
        sources = []
        for position, lang in enumerate(languages):
            ranked = await store.trending(lang, kind)
            if ranked:
                sources.append((max(1.0 - 0.1 * position, 0.5), ranked))
        if include_global and (ranked := await store.trending("all", kind)):
            sources.append((GLOBAL_TREND_WEIGHT, ranked))
        if sources:
            return [item for item, _ in merge_ranked(sources, k)]
        criteria = Criteria(
            content_type=None if kind == "all" else kind,
            trending=True,
            languages=languages or None,
            released_to=today(),
            require_poster=True,
        )
        rows = await self.content.find(criteria, limit=k)
        return [row.id for row, _ in rank_rows(rows, UserProfile(languages=languages), TRENDING_PROFILE).top(k)]

    async def trending(self, kind: str, ctx: UserContext, page: int, limit: int) -> tuple[list[S.ContentCard], bool]:
        async def build() -> list[S.ContentCard]:
            ids = await self._trending_ids(kind, ctx.lang_list, LIST_SIZE, True)
            return to_cards(await self.content.get_many(ids))

        items = await self._cards(cache_key("trending", kind, ctx.lang_key), K.TTL["trending"] // 3, build)
        return page_of(items, page, limit)

    async def local_trending(self, ctx: UserContext) -> S.LocalTrendingOut:
        if not ctx.country and ctx.language_source != "explicit":
            return S.LocalTrendingOut()
        languages = ctx.indian_languages or ctx.lang_list[:2]

        async def build() -> S.LocalTrendingOut:
            ids = await self._trending_ids("all", languages, K.TRENDING_LOCAL_MAX_ITEMS, False)
            cards = to_cards(await self.content.get_many(ids))
            return S.LocalTrendingOut(region=ctx.region_label, items=cards, total=len(cards))

        return await self._model(
            cache_key("trending_local", ctx.geo_scope, ctx.lang_key), K.TTL["trending"] // 3, build, S.LocalTrendingOut
        )

    async def new_releases(
        self, language: str, ctx: UserContext, page: int, limit: int
    ) -> tuple[list[S.ContentCard], bool]:
        specific = language != "all"
        languages = [language, *[x for x in ctx.lang_list if x != language]] if specific else ctx.lang_list

        async def build() -> list[S.ContentCard]:
            now = today()
            window = {
                "released_from": now - timedelta(days=K.NEW_RELEASE_WINDOW_DAYS),
                "released_to": now,
                "require_poster": True,
            }
            if specific:
                rows = await self.content.find(Criteria(languages=[language], **window), limit=LIST_SIZE)
            else:
                own = ctx.indian_languages
                local = await self.content.find(Criteria(languages=own, **window), limit=LIST_SIZE) if own else []
                rows = dedupe(local + await self.content.find(Criteria(**window), limit=LIST_SIZE))
            return self._ranked_cards(rows, languages, FRESH_PROFILE)

        key = cache_key("new", language, "" if specific else ctx.lang_key)
        return page_of(await self._cards(key, K.TTL["releases"], build), page, limit)

    async def language_rail(self, language: str, size: int = K.SECTION_LIMIT) -> list[S.ContentCard]:
        async def build() -> list[S.ContentCard]:
            now = today()
            rows: list[Content] = []
            for days in (K.NEW_RELEASE_WINDOW_DAYS, 90):
                rows = await self.content.find(
                    Criteria(
                        languages=[language],
                        released_from=now - timedelta(days=days),
                        released_to=now,
                        require_poster=True,
                    ),
                    limit=size * 3,
                )
                if len(rows) >= 6:
                    break
            return self._ranked_cards(rows, [language, "en"], FRESH_PROFILE, size)

        return await self._cards(cache_key("lang_new", language), K.TTL["releases"], build)

    async def latest(self, kind: str, ctx: UserContext, page: int, limit: int) -> tuple[list[S.ContentCard], bool]:
        async def build() -> list[S.ContentCard]:
            now = today()
            criteria = Criteria(
                content_type=None if kind == "all" else kind,
                languages=ctx.lang_list,
                released_from=now - timedelta(days=120),
                released_to=now,
                require_poster=True,
            )
            return to_cards(
                await self.content.find(criteria, order="release_date", limit=limit + 1, offset=(page - 1) * limit)
            )

        rows = await self._cards(cache_key("latest", kind, ctx.lang_key, page, limit), K.TTL["trending"], build)
        return rows[:limit], len(rows) > limit

    async def critics(self, languages: list[str], page: int, limit: int) -> tuple[list[S.ContentCard], bool]:
        async def build() -> list[S.ContentCard]:
            indian = [x for x in languages if x in INDIAN_LANGS_SET]
            alts = [Criteria(min_rating=K.CRITICS_MIN_RATING, min_votes=K.CRITICS_MIN_VOTES)]
            if indian:
                alts.append(Criteria(min_rating=7.0, min_votes=K.HIDDEN_GEMS_FALLBACK_MIN_VOTE_COUNT, languages=indian))
            rows = await self.content.find(*alts, order="rating", limit=K.CRITICS_DB_LIMIT * 2)
            return self._ranked_cards(rows, languages, CRITICS_PROFILE)

        return page_of(
            await self._cards(cache_key("critics", ",".join(languages)), K.TTL["critics"], build), page, limit
        )

    async def upcoming(self, languages: list[str], page: int, limit: int) -> tuple[list[S.ContentCard], bool]:
        async def build() -> list[S.ContentCard]:
            now = today()
            rows = await self.content.find(
                Criteria(released_after=now, released_to=now + timedelta(days=K.UPCOMING_DAYS_AHEAD)),
                order="release_asc",
                limit=200,
            )
            return self._ranked_cards(rows, languages, UPCOMING_PROFILE, 100)

        return page_of(
            await self._cards(cache_key("upcoming", ",".join(languages)), K.TTL["upcoming"], build), page, limit
        )

    async def this_week(self, languages: list[str]) -> S.ThisWeekOut:
        now = today()
        start = now - timedelta(days=now.weekday())

        async def build() -> S.ThisWeekOut:
            window = {"released_from": now - timedelta(days=K.THIS_WEEK_WINDOW_DAYS), "released_to": now}
            over = K.THIS_WEEK_MAX_PER_GROUP * 3
            movies = await self.content.find(Criteria(content_type="movie", **window), order="release_date", limit=over)
            shows = await self.content.find(Criteria(content_type="tv", **window), order="release_date", limit=over)
            soon = await self.content.find(
                Criteria(released_after=now, released_to=now + timedelta(days=K.THIS_WEEK_UPCOMING_WINDOW_DAYS)),
                order="release_asc",
                limit=over,
            )
            groups = [
                self._ranked_cards(rows, languages, profile, K.THIS_WEEK_MAX_PER_GROUP)
                for rows, profile in ((movies, FRESH_PROFILE), (shows, FRESH_PROFILE), (soon, UPCOMING_PROFILE))
            ]
            return S.ThisWeekOut(
                week_start=start.isoformat(),
                week_end=(start + timedelta(days=6)).isoformat(),
                movies=groups[0],
                tv=groups[1],
                upcoming=groups[2],
                total=sum(map(len, groups)),
            )

        return await self._model(
            cache_key("this_week", now.isoformat(), ",".join(languages)), K.TTL["releases"], build, S.ThisWeekOut
        )

    async def regional(self, language: str, page: int, limit: int) -> S.RegionalContentOut:
        async def build() -> S.RegionalContentOut:
            rows = await self.content.find(Criteria(languages=[language]), limit=limit + 1, offset=(page - 1) * limit)
            return S.RegionalContentOut(
                language=K.LANGUAGE_NAMES.get(language, language.upper()),
                language_code=language,
                items=to_cards(rows[:limit]),
                total=len(rows[:limit]),
                page=page,
                has_more=len(rows) > limit,
            )

        return await self._model(
            cache_key("regional", language, page, limit), K.TTL["regional"], build, S.RegionalContentOut
        )

    async def genre(
        self, slug: str, content_type: str, language: str | None, year: int | None, sort: str, page: int, limit: int
    ) -> S.GenreContentOut:
        name = slug.replace("_", " ").title()
        if name not in K.GENRE_NAMES:
            raise NotFoundError("Genre not found")

        async def build() -> S.GenreContentOut:
            criteria = Criteria(
                genres=[name],
                content_type=None if content_type == "all" else content_type,
                languages=[language] if language else None,
                year=year,
            )
            rows = await self.content.find(criteria, order=sort, limit=limit + 1, offset=(page - 1) * limit)
            return S.GenreContentOut(
                genre=slug, items=to_cards(rows[:limit]), total=len(rows[:limit]), page=page, has_more=len(rows) > limit
            )

        key = cache_key("genre", slug, content_type, language, year, sort, page, limit)
        return await self._model(key, K.TTL["genre"], build, S.GenreContentOut)

    async def _hero(self, ctx: UserContext) -> list[S.ContentCard]:
        now = today()
        window = {"released_from": now - timedelta(days=75), "released_to": now, "require_backdrop": True}
        alts = [Criteria(min_rating=7.0, min_votes=400, **window)]
        if ctx.indian_languages:
            alts.append(Criteria(min_rating=6.5, min_votes=50, languages=ctx.indian_languages, **window))
        rows = await self.content.find(*alts, limit=K.HERO_CANDIDATE_LIMIT) or await self.content.find(
            Criteria(min_rating=7.5, min_votes=800, require_backdrop=True),
            limit=K.HERO_CANDIDATE_LIMIT,
        )
        top = rank_rows(
            rows, UserProfile(languages=ctx.lang_list), FRESH_PROFILE, build_context(ctx.timezone, ctx.country)
        ).diversified(K.HERO_LIMIT)
        return to_cards(row for row, _ in top)

    async def _popular(self, ctx: UserContext) -> list[S.ContentCard]:
        rows = await self.content.find(
            Criteria(languages=ctx.indian_languages or sorted(INDIAN_LANGS_SET)), limit=K.POPULAR_INDIA_DB_LIMIT
        )
        return self._ranked_cards(rows, ctx.lang_list, DEFAULT_PROFILE, K.SECTION_LIMIT)

    async def _isolated(
        self, name: str, job: Callable[["DiscoveryService"], Awaitable[Any]], gate: asyncio.Semaphore
    ) -> Any:
        async with gate:
            try:
                async with self.session_factory() as session:
                    return await job(self.with_session(session))
            except (TimeoutError, AppError, SQLAlchemyError, ValueError, KeyError) as exc:
                logger.warning("home_section_failed", extra={"section": name, "error": type(exc).__name__})
                return None

    async def _shared_sections(self, ctx: UserContext) -> S.HomeFeedOut:
        langs, rails = ctx.lang_list, ctx.indian_languages[:3]
        jobs: dict[str, Callable[[DiscoveryService], Awaitable[Any]]] = {
            "hero": lambda s: s._hero(ctx),
            "local": lambda s: s.local_trending(ctx),
            "trending": lambda s: s.trending("all", ctx, 1, 20),
            "new": lambda s: s.new_releases("all", ctx, 1, 20),
            "week": lambda s: s.this_week(langs),
            "popular": lambda s: s._popular(ctx),
            "critics": lambda s: s.critics(langs, 1, 20),
            "soon": lambda s: s.upcoming(langs, 1, 20),
            **{f"rail_{lang}": (lambda s, lang=lang: s.language_rail(lang)) for lang in rails},
        }
        gate = asyncio.Semaphore(4)
        got = dict(zip(jobs, await asyncio.gather(*(self._isolated(n, j, gate) for n, j in jobs.items())), strict=True))

        def section(
            title: str, kind: str, items: list[S.ContentCard] | None, total: int | None = None
        ) -> S.FeedSectionOut | None:
            return (
                S.FeedSectionOut(
                    title=title,
                    section_type=kind,
                    items=items,
                    total=total or len(items),
                    has_more=(total or len(items)) > len(items),
                )
                if items
                else None
            )

        week, local = got["week"], got["local"]
        mixed: list[S.ContentCard] = []
        if week:
            mixed = (
                [c for pair in zip(week.movies, week.tv, strict=False) for c in pair]
                + week.movies[len(week.tv) :]
                + week.tv[len(week.movies) :]
            )
        trending, new, critics, soon = (got[k][0] if got[k] else None for k in ("trending", "new", "critics", "soon"))
        sections = [
            section("Top Picks", "hero", got["hero"]),
            section("Trending Near You", "local_trending", local.items if local else None, local.total if local else 0),
            section("Trending Now", "trending", trending),
            *[section(f"New in {K.LANGUAGE_NAMES.get(x, x.upper())}", f"new_{x}", got[f"rail_{x}"]) for x in rails],
            section("New Releases", "new_releases", new),
            section("This Week", "this_week", mixed[: K.SECTION_LIMIT], week.total if week else 0),
            section("Popular in India", "popular_india", got["popular"]),
            section("Critics' Choice", "critics_choice", critics),
            section("Coming Soon", "upcoming", soon),
        ]
        return S.HomeFeedOut(
            sections=[s for s in sections if s], detected_region=ctx.country or None, detected_languages=langs[:5]
        )

    async def home(self, ctx: UserContext) -> S.HomeFeedOut:
        shared = await self._model(
            cache_key("home", ctx.geo_scope, ctx.lang_key),
            K.TTL["home"],
            lambda: self._shared_sections(ctx),
            S.HomeFeedOut,
        )
        try:
            recommendations, interactions = await self.reco.for_you(ctx, 24)
        except (AppError, SQLAlchemyError) as exc:
            logger.warning("personalized_section_failed", extra={"error": type(exc).__name__})
            recommendations, interactions = [], 0
        if recommendations and interactions:
            shared.sections.insert(
                min(1, len(shared.sections)),
                S.FeedSectionOut(
                    title="Recommended for You",
                    section_type="personalized",
                    items=list(recommendations),
                    total=len(recommendations),
                ),
            )
        shared.session_id, shared.detected_region, shared.detected_languages = (
            ctx.session_id,
            ctx.country or None,
            ctx.lang_list[:5],
        )
        return shared
