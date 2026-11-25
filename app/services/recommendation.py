# app/services/recommendation.py

import asyncio
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas as S
from app.core.constants import DECIDE_LIMIT, FALLBACK_LIMIT, TTL
from app.core.context import UserContext
from app.core.errors import NotFoundError
from app.infra.cache import Cache, cache_key
from app.models import Content
from app.recommender.engine import Recommender
from app.recommender.explain import SITUATION_CONFIG, build_context, confidence_for, reasons_for, resolve_mood_genres
from app.recommender.items import DEFAULT_PROFILE, FOR_YOU_PROFILE, GEMS_PROFILE, UserProfile, rank_rows, to_match
from app.repositories.content import ContentRepository, Criteria
from app.repositories.interactions import InteractionRepository
from app.services.mappers import to_card, to_cards
from app.utils import INDIAN_LANGS_SET, normalize_query, today

logger = logging.getLogger("app.reco")
TYPE_WEIGHTS = {"view": 1.0, "search": 0.8, "watchlist": 2.0, "favorite": 3.0, "rating": 2.5}
HALF_LIFE_DAYS = 30.0
GENRE_WORDS = {
    "action": "Action",
    "comedy": "Comedy",
    "drama": "Drama",
    "horror": "Horror",
    "thriller": "Thriller",
    "romance": "Romance",
    "sci-fi": "Science Fiction",
    "fantasy": "Fantasy",
    "crime": "Crime",
    "mystery": "Mystery",
    "adventure": "Adventure",
    "animation": "Animation",
    "family": "Family",
    "documentary": "Documentary",
    "war": "War",
    "history": "History",
    "music": "Music",
    "western": "Western",
}
LANG_WORDS = {
    "telugu": "te",
    "hindi": "hi",
    "tamil": "ta",
    "malayalam": "ml",
    "kannada": "kn",
    "english": "en",
    "japanese": "ja",
    "korean": "ko",
    "french": "fr",
    "spanish": "es",
    "bollywood": "hi",
    "tollywood": "te",
    "kollywood": "ta",
    "mollywood": "ml",
    "sandalwood": "kn",
}


@dataclass(slots=True)
class Signals:
    count: int = 0
    genres: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    content_types: list[str] = field(default_factory=list)
    history: list[tuple[int, float]] = field(default_factory=list)
    seen_ids: set[int] = field(default_factory=set)

    @property
    def taste(self) -> dict:
        return {"genres": self.genres, "content_types": self.content_types, "count": self.count}

    def profile(self, languages: list[str]) -> UserProfile:
        return UserProfile(
            languages=languages, genres=self.genres[:5], content_types=self.content_types[:3], count=self.count
        )


class RecommendationService:
    def __init__(self, session: AsyncSession, cache: Cache, recommender: Recommender):
        self.session = session
        self.cache = cache
        self.recommender = recommender
        self.content = ContentRepository(session)
        self.interactions = InteractionRepository(session)

    async def signals(self, session_id: str) -> Signals:
        rows = await self.interactions.recent(session_id, 100)
        now = datetime.now(UTC)
        genres, languages, types = Counter(), Counter(), Counter()
        history: dict[int, float] = {}
        for content_id, kind, meta, stamp in rows:
            weight = TYPE_WEIGHTS.get(kind, 1.0)
            decay = 0.5 ** (max((now - stamp).total_seconds() / 86400, 0.0) / HALF_LIFE_DAYS)
            history[content_id] = history.get(content_id, 0.0) + weight * decay
            meta = meta or {}
            for name in meta.get("genres", []):
                genres[name] += weight
            for lang in meta.get("languages", []):
                languages[lang] += weight
            if meta.get("content_type"):
                types[meta["content_type"]] += weight
        return Signals(
            count=len(rows),
            genres=[g for g, _ in genres.most_common(5)],
            languages=[x for x, _ in languages.most_common(3)],
            content_types=[t for t, _ in types.most_common(3)],
            history=list(history.items()),
            seen_ids=set(history),
        )

    def cards(
        self, pairs: list[tuple[Content, float]], languages: list[str], signals: Signals, region: str | None
    ) -> list[S.ContentCard]:
        confidence = confidence_for(signals.count)
        return [
            to_card(
                c,
                cinebrain_match=to_match(score),
                match_confidence=confidence,
                reasons=reasons_for(c, languages, signals.taste, region),
            )
            for c, score in pairs
        ]

    async def _fallback(
        self, languages: list[str], user: UserProfile, context: dict, limit: int, seen: set[int]
    ) -> list[tuple[Content, float]]:
        own = [lang for lang in languages if lang in INDIAN_LANGS_SET]
        criteria = Criteria(
            languages=[*own, "en"] if own else None,
            min_rating=5.0,
            released_to=today(),
            require_poster=True,
            exclude_ids=list(seen) or None,
        )
        rows = await self.content.find(criteria, limit=300)
        return rank_rows(rows, user, FOR_YOU_PROFILE, context).diversified(limit)

    async def for_you(self, ctx: UserContext, limit: int = 24) -> tuple[list[S.RecommendationCard], int]:
        signals = await self.signals(ctx.session_id)
        effective = ctx.with_behavior(signals.languages, signals.count)
        languages = effective.lang_list
        user, context = signals.profile(languages), build_context(ctx.timezone, ctx.country)
        picks = await asyncio.to_thread(self.recommender.personalize, signals.history, user, context, limit)
        if picks is None:
            pairs = await self._fallback(languages, user, context, limit, signals.seen_ids)
        else:
            scores = dict(picks)
            pairs = [(row, scores[row.id]) for row in await self.content.get_many([i for i, _ in picks])]
        cards = self.cards(pairs, languages, signals, ctx.region_label)
        return [
            S.RecommendationCard(
                **c.model_dump(),
                recommendation_score=float(c.cinebrain_match or 0),
                recommendation_reason=c.reasons[0].label if c.reasons else None,
            )
            for c in cards
        ], signals.count

    async def similar(self, content_id: int, limit: int) -> S.SimilarContentOut:
        async def build() -> dict:
            scored = self.recommender.similar(content_id, limit)
            if scored:
                return S.SimilarContentOut(
                    source_id=content_id,
                    items=to_cards(await self.content.get_many([i for i, _ in scored])),
                    total=len(scored),
                ).model_dump(mode="json")
            source = await self.content.get(content_id)
            if source is None:
                raise NotFoundError("Content not found")
            criteria = Criteria(
                content_type=source.content_type,
                genres=source.genres or None,
                min_rating=5.0,
                released_to=today(),
                exclude_ids=[source.id],
            )
            rows = await self.content.find(criteria, limit=60)
            top = rank_rows(rows, UserProfile(languages=source.languages or []), DEFAULT_PROFILE).diversified(limit)
            return S.SimilarContentOut(
                source_id=content_id, items=to_cards(c for c, _ in top), total=len(top)
            ).model_dump(mode="json")

        return S.SimilarContentOut.model_validate(
            await self.cache.single_flight(cache_key("similar", content_id, limit), TTL["similar"], build)
        )

    async def feels_like(self, query: str, limit: int) -> S.FeelsLikeOut:
        text = normalize_query(query)
        genres = [g for word, g in GENRE_WORDS.items() if word in text]
        langs = [lang for word, lang in LANG_WORDS.items() if word in text]

        async def build() -> dict:
            rows = await self.content.find(
                Criteria(genres=genres or None, languages=langs or None, min_rating=6.0), limit=60
            )
            user = UserProfile(languages=langs or ["te", "hi", "ta", "ml", "kn", "en"], genres=genres)
            top = rank_rows(rows, user).diversified(limit)
            return S.FeelsLikeOut(query=query, items=to_cards(c for c, _ in top), total=len(top)).model_dump(
                mode="json"
            )

        return S.FeelsLikeOut.model_validate(
            await self.cache.single_flight(cache_key("feels", text, limit), TTL["feels"], build)
        )

    async def hidden_gems(self, ctx: UserContext, page: int, limit: int) -> tuple[list[S.ContentCard], bool]:
        signals = await self.signals(ctx.session_id)
        effective = ctx.with_behavior(signals.languages, signals.count)
        own, languages = effective.indian_languages, effective.lang_list
        taste = ",".join(sorted(signals.genres[:3])) if signals.count else "cold"

        async def build() -> dict:
            main = Criteria(
                min_rating=7.0, min_votes=100, max_votes=5000, max_popularity=60.0, genres=signals.genres[:3] or None
            )
            alts = [main] + (
                [
                    Criteria(
                        min_rating=7.0,
                        min_votes=50,
                        max_votes=5000,
                        max_popularity=60.0,
                        languages=own,
                        genres=signals.genres[:3] or None,
                    )
                ]
                if own
                else []
            )
            rows = await self.content.find(*alts, order="rating", limit=120)
            if len(rows) < 10:
                rows = await self.content.find(
                    Criteria(min_rating=7.0, min_votes=50, max_popularity=60.0), order="rating", limit=60
                )
            context = build_context(ctx.timezone, ctx.country)
            top = rank_rows(rows, signals.profile(languages), GEMS_PROFILE, context).diversified(60)
            return [c.model_dump(mode="json") for c in self.cards(top, languages, signals, ctx.region_label)]

        payload = await self.cache.single_flight(
            cache_key("gems", ctx.country, taste, effective.lang_key), TTL["critics"], build, cacheable=bool
        )
        items = [S.ContentCard.model_validate(i) for i in payload]
        start = (page - 1) * limit
        return items[start : start + limit], len(items) > start + limit

    async def decide(
        self,
        ctx: UserContext,
        mood: str | None,
        max_runtime: int | None,
        min_runtime: int | None,
        languages: list[str] | None,
        situation: str | None,
    ) -> S.DecideOut:
        signals = await self.signals(ctx.session_id)
        effective = ctx.with_behavior(signals.languages, signals.count)
        langs = languages or effective.lang_list
        context = build_context(ctx.timezone, ctx.country)
        config = SITUATION_CONFIG.get(situation or "", {})
        max_rt, min_rt = max_runtime, min_runtime
        if situation == "quick_watch":
            max_rt = max_rt if max_rt is not None else config.get("runtime_preferred_max")
            hard = config.get("runtime_hard_max")
            if hard and (max_rt is None or max_rt > hard):
                max_rt = hard
        elif config.get("runtime_max") and max_rt is None:
            max_rt = config["runtime_max"]
        if config.get("runtime_min") and min_rt is None:
            min_rt = config["runtime_min"]
        own = [lang for lang in langs if lang in INDIAN_LANGS_SET]
        now = today()
        pool = Criteria(
            min_rating=6.0,
            min_votes=50,
            released_from=now - timedelta(days=365),
            released_to=now,
            genres=resolve_mood_genres(mood, situation) or None,
            content_type="tv" if config.get("prefer_series") else None,
            languages=own or None,
            min_runtime=min_rt,
            max_runtime=max_rt,
        )
        rows = await self.content.find(pool, limit=80) or await self.content.find(
            Criteria(min_rating=6.5, min_votes=100), limit=40
        )
        summary = {
            "time_of_day": context["time_of_day"],
            "day_of_week": context["day_of_week"],
            "region": ctx.country or None,
        }
        if not rows:
            return S.DecideOut(primary=[], fallback=[], total=0, context_summary=summary)
        top = rank_rows(rows, signals.profile(langs), DEFAULT_PROFILE, context).diversified(
            DECIDE_LIMIT + FALLBACK_LIMIT
        )
        cards = self.cards(top, langs, signals, ctx.region_label)
        return S.DecideOut(
            primary=cards[:DECIDE_LIMIT],
            fallback=cards[DECIDE_LIMIT:],
            total=len(cards),
            context_summary={**summary, "languages": langs[:5], "mood": mood, "situation": situation},
        )
