# app/recommender/explain.py

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.constants import INDIA_TIMEZONES, LANGUAGE_NAMES, MAX_CONFIDENCE, MIN_CONFIDENCE_COLD_START
from app.recommender.items import PRIOR_MEAN
from app.schemas import RecommendationReason
from app.utils import today

MOOD_GENRE_MAP = {
    "action": ["Action", "Action & Adventure"],
    "comedy": ["Comedy"],
    "drama": ["Drama"],
    "thriller": ["Thriller"],
    "horror": ["Horror"],
    "romance": ["Romance"],
    "scary": ["Horror"],
    "funny": ["Comedy"],
    "emotional": ["Drama", "Romance"],
    "intelligent": ["Mystery", "Science Fiction"],
    "easy_watch": ["Comedy", "Family"],
    "cinematic": ["Action", "Adventure", "Science Fiction"],
    "binge": ["Science Fiction", "Fantasy", "Action & Adventure"],
}
SITUATION_CONFIG = {
    "date_night": {"moods": ["romance", "comedy", "drama"], "runtime_max": 150},
    "family_night": {"moods": ["easy_watch", "comedy"], "runtime_max": 130},
    "solo_night": {"moods": ["thriller", "drama", "intelligent"], "runtime_max": None},
    "weekend_binge": {"prefer_series": True, "runtime_max": None},
    "quick_watch": {"runtime_preferred_max": 100, "runtime_hard_max": 120},
    "movie_night": {"runtime_min": 100, "runtime_max": 200},
}
_IST = timezone(timedelta(hours=5, minutes=30))


def build_context(tz: str | None = None, country: str | None = None) -> dict:
    try:
        now = datetime.now(ZoneInfo(tz)) if tz else None
    except (ZoneInfoNotFoundError, ValueError, OSError):
        now = None
    if now is None:
        now = datetime.now(_IST if country == "IN" or tz in INDIA_TIMEZONES else UTC)
    hour = now.hour
    time_of_day = (
        "morning"
        if 5 <= hour < 12
        else "afternoon"
        if 12 <= hour < 17
        else "evening"
        if 17 <= hour < 21
        else "night"
        if hour >= 21
        else "late_night"
    )
    day = now.strftime("%A")
    return {
        "time_of_day": time_of_day,
        "day_of_week": day,
        "is_weekend": day in ("Saturday", "Sunday")
        or (day == "Friday" and time_of_day in ("evening", "night", "late_night")),
    }


def resolve_mood_genres(mood: str | None, situation: str | None = None) -> list[str]:
    genres = set(MOOD_GENRE_MAP.get(mood or "", []))
    for m in SITUATION_CONFIG.get(situation or "", {}).get("moods", []):
        genres.update(MOOD_GENRE_MAP.get(m, []))
    return sorted(genres)


def time_commitment(content) -> str | None:
    if not content.runtime:
        return None
    if content.content_type != "movie":
        return f"~{content.runtime}m per episode"
    hours, minutes = divmod(content.runtime, 60)
    return " ".join(p for p in (f"{hours}h" if hours else "", f"{minutes}m" if minutes or not hours else "") if p)


def confidence_for(count: int) -> float:
    if count <= 0:
        return MIN_CONFIDENCE_COLD_START
    return next(
        (v for bound, v in ((3, 0.40), (5, 0.50), (10, 0.60), (20, 0.70), (30, 0.80)) if count < bound), MAX_CONFIDENCE
    )


def _bayes(rating: float | None, votes: int) -> float:
    w = votes / (votes + 100)
    return max(0.0, min(1.0, (w * (rating or 0.0) + (1 - w) * PRIOR_MEAN) / 10))


def reasons_for(
    content, languages: Sequence[str], taste: dict | None, region: str | None
) -> list[RecommendationReason]:
    out: list[RecommendationReason] = []

    def add(code: str, label: str, weight: float) -> None:
        out.append(RecommendationReason(code=code, label=label, weight=round(weight, 3)))

    matched = [lang for lang in languages if lang in (content.languages or [])]
    age = (today() - content.release_date).days if content.release_date else None
    if matched:
        name = LANGUAGE_NAMES.get(matched[0], matched[0].upper())
        position = languages.index(matched[0])
        add("LANGUAGE_MATCH", f"{name} content", max(1.0 - 0.1 * position, 0.5))
        if age is not None and 0 <= age <= 30 and position < 2 and matched[0] != "en":
            add("NEW_IN_LANGUAGE", f"New in {name}", 0.9 * max(1.0 - 0.1 * position, 0.5))
    if taste:
        overlap = sorted(set(taste.get("genres", [])) & set(content.genres or []))[:2]
        if overlap:
            add(
                "BEHAVIORAL_GENRE_MATCH",
                f"Matches your interest in {', '.join(overlap)}",
                len(overlap) / max(len(taste["genres"]), 1),
            )
        if content.content_type in taste.get("content_types", []):
            add("BEHAVIORAL_TYPE_MATCH", f"You often watch {content.content_type}s", 1.0)
    if content.is_trending:
        add("REGIONAL_TRENDING", f"Trending in {region or 'India'}", 1.0)
    if content.rating and content.vote_count and content.vote_count >= 200:
        add("STRONG_RATING", "Strong rating signal", _bayes(content.rating, content.vote_count))
    if age is not None and 0 <= age <= 30:
        add("RECENT_RELEASE", "Recently released", 0.06)
    return sorted(out, key=lambda r: r.weight, reverse=True)[:4]
