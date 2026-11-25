# app/recommender/items.py

import heapq
import math
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date

import numpy as np
from scipy import sparse

from app.core.constants import GENRE_MAP, INDIAN_LANGUAGES, MIN_VOTES_CONFIDENCE, POPULARITY_REFERENCE, SCORE_WEIGHTS

EPOCH = date(1970, 1, 1)
NO_DATE = np.iinfo(np.int32).min
GENRE_VOCAB = sorted(set(GENRE_MAP.values()))
GENRE_INDEX = {name: i for i, name in enumerate(GENRE_VOCAB)}
PRIOR_MEAN = 6.3
LN2 = math.log(2)
SPOKEN_ONLY = 0.85
MATCH_CEILING = 0.80
MAX_LANGS_PER_ITEM = 3
_INDIAN = frozenset(INDIAN_LANGUAGES)

TIME_GENRES = {
    "morning": {"Family", "Animation", "Comedy"},
    "afternoon": {"Comedy", "Adventure", "Action"},
    "evening": {"Drama", "Romance", "Comedy", "Family"},
    "night": {"Thriller", "Crime", "Mystery", "Science Fiction", "Action"},
    "late_night": {"Horror", "Thriller", "Mystery"},
}


@dataclass(frozen=True, slots=True)
class Profile:
    weights: tuple[float, ...]
    half_life: float = 90.0
    horizon: float | None = None
    context_bonus: float = 0.03


DEFAULT_PROFILE = Profile(tuple(SCORE_WEIGHTS.values()))
FRESH_PROFILE = Profile((0.20, 0.32, 0.10, 0.25, 0.05, 0.03, 0.05), half_life=21.0)
FOR_YOU_PROFILE = Profile((0.18, 0.12, 0.17, 0.33, 0.10, 0.04, 0.06))
TRENDING_PROFILE = Profile((0.30, 0.15, 0.10, 0.20, 0.05, 0.03, 0.17), half_life=45.0)
CRITICS_PROFILE = Profile((0.10, 0.05, 0.45, 0.25, 0.05, 0.02, 0.08), half_life=365.0)
UPCOMING_PROFILE = Profile((0.40, 0.15, 0.0, 0.35, 0.05, 0.03, 0.02), horizon=120.0)
GEMS_PROFILE = Profile((0.05, 0.05, 0.45, 0.25, 0.12, 0.03, 0.05), half_life=730.0)


@dataclass(slots=True)
class UserProfile:
    languages: list[str]
    genres: list[str] = field(default_factory=list)
    content_types: list[str] = field(default_factory=list)
    count: int = 0


def day_number(value: date) -> int:
    return (value - EPOCH).days


class ItemTable:
    __slots__ = (
        "_diversity",
        "genres",
        "has_en",
        "has_indian",
        "has_lang",
        "has_poster",
        "ids",
        "is_tv",
        "lang_ids",
        "lang_vocab",
        "popularity",
        "rating",
        "release_day",
        "trending",
        "votes",
    )

    def __init__(self, **arrays):
        for name, value in arrays.items():
            setattr(self, name, value)
        self._diversity = None

    def __len__(self) -> int:
        return int(self.ids.shape[0])

    @classmethod
    def from_rows(cls, rows: Sequence, vocab: dict[str, int] | None = None) -> "ItemTable":
        n = len(rows)
        grow = vocab is None
        vocab = {} if vocab is None else vocab
        lang_ids = np.full((n, MAX_LANGS_PER_ITEM), -1, dtype=np.int16)
        has_indian = np.zeros(n, dtype=bool)
        has_en = np.zeros(n, dtype=bool)
        has_lang = np.zeros(n, dtype=bool)
        gr, gc = [], []
        for i, row in enumerate(rows):
            langs = row.languages or []
            has_lang[i] = bool(langs)
            has_en[i] = "en" in langs
            has_indian[i] = any(lang in _INDIAN for lang in langs)
            for j, lang in enumerate(langs[:MAX_LANGS_PER_ITEM]):
                idx = vocab.get(lang)
                if idx is None and grow:
                    idx = vocab[lang] = len(vocab)
                if idx is not None:
                    lang_ids[i, j] = idx
            for genre in row.genres or []:
                col = GENRE_INDEX.get(genre)
                if col is not None:
                    gr.append(i)
                    gc.append(col)
        genres = sparse.csr_matrix(
            (np.ones(len(gr), dtype=np.float32), (gr, gc)), shape=(n, len(GENRE_VOCAB)), dtype=np.float32
        )
        genres.data[:] = 1.0
        return cls(
            ids=np.fromiter((r.id for r in rows), np.int64, n),
            is_tv=np.fromiter((r.content_type == "tv" for r in rows), bool, n),
            popularity=np.fromiter((r.popularity or 0.0 for r in rows), np.float32, n),
            rating=np.fromiter((r.rating or 0.0 for r in rows), np.float32, n),
            votes=np.fromiter((r.vote_count or 0 for r in rows), np.int32, n),
            release_day=np.fromiter(
                (day_number(r.release_date) if r.release_date else NO_DATE for r in rows), np.int32, n
            ),
            has_poster=np.fromiter((bool(r.poster_path) for r in rows), bool, n),
            trending=np.fromiter((bool(r.is_trending) for r in rows), bool, n),
            lang_ids=lang_ids,
            has_indian=has_indian,
            has_en=has_en,
            has_lang=has_lang,
            genres=genres,
            lang_vocab=vocab,
        )

    def take(self, idx: np.ndarray) -> "ItemTable":
        return ItemTable(
            ids=self.ids[idx],
            is_tv=self.is_tv[idx],
            popularity=self.popularity[idx],
            rating=self.rating[idx],
            votes=self.votes[idx],
            release_day=self.release_day[idx],
            has_poster=self.has_poster[idx],
            trending=self.trending[idx],
            lang_ids=self.lang_ids[idx],
            has_indian=self.has_indian[idx],
            has_en=self.has_en[idx],
            has_lang=self.has_lang[idx],
            genres=self.genres[idx],
            lang_vocab=self.lang_vocab,
        )

    def diversity_features(self) -> sparse.csr_matrix:
        if self._diversity is None:
            tv = sparse.csr_matrix(0.5 * self.is_tv.astype(np.float32)[:, None])
            self._diversity = sparse.hstack([self.genres, tv], format="csr", dtype=np.float32)
        return self._diversity


def popularity_norm(popularity: np.ndarray) -> np.ndarray:
    return np.minimum(1.0, np.log1p(np.maximum(popularity, 0.0)) / math.log1p(POPULARITY_REFERENCE))


def rating_confidence(rating: np.ndarray, votes: np.ndarray) -> np.ndarray:
    v = np.maximum(votes, 0).astype(np.float32)
    weight = v / (v + MIN_VOTES_CONFIDENCE)
    shrunk = np.clip((weight * rating + (1.0 - weight) * PRIOR_MEAN) / 10.0, 0.0, 1.0)
    return np.where(rating <= 0, np.where(votes == 0, 0.5, 0.0), shrunk)


def freshness(release_day: np.ndarray, today_day: int, half_life: float, horizon: float | None) -> np.ndarray:
    delta = today_day - release_day.astype(np.int64)
    past = np.exp(-LN2 * np.maximum(delta, 0) / half_life)
    future = np.exp(-LN2 * np.maximum(-delta, 0) / horizon) if horizon else np.full(delta.shape, 0.5)
    undated = math.exp(-LN2 * 365 / half_life)
    return np.where(release_day == NO_DATE, undated, np.where(delta >= 0, past, future)).astype(np.float32)


def language_weights(vocab: dict[str, int], languages: Sequence[str]) -> np.ndarray:
    weights = np.zeros(len(vocab) + 1, dtype=np.float32)
    for position, lang in enumerate(languages):
        idx = vocab.get(lang)
        if idx is not None:
            weights[idx] = max(1.0 - position * 0.1, 0.5)
    return weights


def language_score(t: ItemTable, languages: Sequence[str]) -> np.ndarray:
    table = language_weights(t.lang_vocab, languages)[t.lang_ids]
    best = np.maximum(table[:, 0], SPOKEN_ONLY * np.maximum(table[:, 1], table[:, 2]))
    fallback = np.where(t.has_indian, 0.4, np.where(t.has_en, 0.2, np.where(t.has_lang, 0.1, 0.0)))
    return np.where(best > 0, best, fallback).astype(np.float32)


def context_bonus(t: ItemTable, context: dict | None) -> np.ndarray:
    if not context:
        return np.zeros(len(t), dtype=np.float32)
    vec = np.zeros(len(GENRE_VOCAB), dtype=np.float32)
    for genre in TIME_GENRES.get(context.get("time_of_day", ""), ()):
        if genre in GENRE_INDEX:
            vec[GENRE_INDEX[genre]] = 1.0
    bonus = 0.6 * ((t.genres @ vec) > 0)
    if context.get("is_weekend"):
        bonus = bonus + 0.4 * t.is_tv
    return np.minimum(bonus, 1.0).astype(np.float32)


def score_items(
    t: ItemTable,
    user: UserProfile,
    profile: Profile = DEFAULT_PROFILE,
    context: dict | None = None,
    today_day: int | None = None,
) -> np.ndarray:
    today_day = day_number(date.today()) if today_day is None else today_day
    gvec = np.zeros(len(GENRE_VOCAB), dtype=np.float32)
    top = [g for g in user.genres if g in GENRE_INDEX]
    for genre in top:
        gvec[GENRE_INDEX[genre]] = 1.0 / len(top)
    genre_affinity = np.minimum(1.0, t.genres @ gvec) if top else np.zeros(len(t), dtype=np.float32)
    want_tv, want_movie = "tv" in user.content_types, "movie" in user.content_types
    type_affinity = np.where(t.is_tv, float(want_tv), float(want_movie)).astype(np.float32)
    parts = (
        popularity_norm(t.popularity),
        freshness(t.release_day, today_day, profile.half_life, profile.horizon),
        rating_confidence(t.rating, t.votes),
        language_score(t, user.languages),
        genre_affinity,
        type_affinity,
        t.trending.astype(np.float32),
    )
    raw = np.zeros(len(t), dtype=np.float32)
    for weight, part in zip(profile.weights, parts, strict=True):
        raw += np.float32(weight) * part
    raw += np.float32(profile.context_bonus) * context_bonus(t, context)
    return (raw * np.where(t.has_poster, 1.0, 0.85)).astype(np.float32)


def top_k(scores: np.ndarray, k: int, tiebreak: np.ndarray | None = None) -> np.ndarray:
    n = scores.shape[0]
    if k <= 0 or n == 0:
        return np.empty(0, dtype=np.int64)
    k = min(k, n)
    part = np.arange(n) if k == n else np.argpartition(-scores, k - 1)[:k]
    secondary = tiebreak[part] if tiebreak is not None else part
    return part[np.lexsort((secondary, -scores[part]))]


def _weighted_stream(weight: float, ranked: Sequence[Sequence[float]]) -> Iterator[tuple[float, int]]:
    for item, score in ranked:
        yield -(float(score) * weight), int(item)


def merge_ranked(sources: Iterable[tuple[float, Sequence[Sequence[float]]]], k: int) -> list[tuple[int, float]]:
    seen: set[int] = set()
    out: list[tuple[int, float]] = []
    for negative, item in heapq.merge(*[_weighted_stream(weight, ranked) for weight, ranked in sources]):
        if item not in seen:
            seen.add(item)
            out.append((item, -negative))
            if len(out) >= k:
                break
    return out


def mmr_select(scores: np.ndarray, features: sparse.csr_matrix, k: int, lam: float = 0.7) -> list[int]:
    m = scores.shape[0]
    k = min(k, m)
    if m <= 1 or k <= 0:
        return list(range(k))
    norms = np.sqrt(np.asarray(features.multiply(features).sum(axis=1)).ravel())
    norms[norms == 0] = 1.0
    unit = sparse.diags(1.0 / norms) @ features
    similarity = (unit @ unit.T).toarray()
    spread = float(np.ptp(scores)) or 1.0
    relevance = (scores - scores.min()) / spread
    chosen: list[int] = []
    available = np.ones(m, dtype=bool)
    worst = np.zeros(m, dtype=np.float32)
    for _ in range(k):
        value = lam * relevance - (1.0 - lam) * worst
        value[~available] = -np.inf
        pick = int(np.argmax(value))
        chosen.append(pick)
        available[pick] = False
        worst = np.maximum(worst, similarity[pick])
    return chosen


@dataclass(slots=True)
class Ranked:
    rows: list
    scores: np.ndarray
    table: ItemTable
    order: np.ndarray

    def top(self, k: int) -> list[tuple[object, float]]:
        return [(self.rows[i], float(self.scores[i])) for i in self.order[:k]]

    def diversified(self, k: int, lam: float = 0.7, pool: int | None = None) -> list[tuple[object, float]]:
        pool = min(len(self.order), pool or max(k * 4, 40))
        head = self.order[:pool]
        picks = mmr_select(self.scores[head], self.table.diversity_features()[head], k, lam)
        return [(self.rows[head[j]], float(self.scores[head[j]])) for j in picks]


def rank_rows(
    rows: Sequence,
    user: UserProfile,
    profile: Profile = DEFAULT_PROFILE,
    context: dict | None = None,
    today_day: int | None = None,
) -> Ranked:
    table = ItemTable.from_rows(rows)
    scores = score_items(table, user, profile, context, today_day)
    return Ranked(list(rows), scores, table, top_k(scores, len(rows), table.ids))


def to_match(score: float) -> int:
    return max(0, min(100, round(score / MATCH_CEILING * 100)))
