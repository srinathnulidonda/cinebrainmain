# app/recommender/engine.py

import heapq
from collections.abc import Sequence

import numpy as np

from app.recommender.items import FOR_YOU_PROFILE, NO_DATE, UserProfile, day_number, mmr_select, score_items, top_k
from app.recommender.store import ModelStore
from app.utils import today

PERSONAL_WEIGHT = 0.5
EXPLORATION = 0.04
HISTORY_CONFIDENCE = 3.0
GLOBAL_POOL = 200
LANGUAGE_POOL_LANGS = 4


class Recommender:
    def __init__(self, store: ModelStore):
        self.store = store

    @property
    def ready(self) -> bool:
        return self.store.model is not None

    def similar(self, content_id: int, k: int, exclude: Sequence[int] = ()) -> list[tuple[int, float]] | None:
        model = self.store.model
        idx = model.id_to_idx.get(content_id) if model else None
        if idx is None:
            return None
        neighbors, similarity = model.neighbors[idx], model.similarity[idx]
        mask = neighbors >= 0
        neighbors, similarity = neighbors[mask], similarity[mask]
        scores = similarity * (0.85 + 0.15 * model.prior[neighbors])
        blocked = set(exclude) | {content_id}
        ids = model.table.ids[neighbors]
        candidates = ((float(s), int(i)) for s, i in zip(scores, ids, strict=True) if int(i) not in blocked)
        return [(item, score) for score, item in heapq.nlargest(k, candidates)]

    def candidate_pool(self, languages: Sequence[str]) -> np.ndarray:
        model = self.store.model
        vocab = model.table.lang_vocab
        pools = [model.top_prior[:GLOBAL_POOL].astype(np.int64)]
        for lang in languages[:LANGUAGE_POOL_LANGS]:
            idx = vocab.get(lang)
            if idx is not None:
                row = model.lang_top[idx]
                pools.append(row[row >= 0].astype(np.int64))
        return np.unique(np.concatenate(pools))

    def personalize(
        self,
        history: Sequence[tuple[int, float]],
        user: UserProfile,
        context: dict | None,
        k: int,
        exclude_ids: Sequence[int] = (),
        diversity: float = 0.7,
    ) -> list[tuple[int, float]] | None:
        model = self.store.model
        if model is None:
            return None
        table = model.table
        today_day = day_number(today())
        pairs = [(model.id_to_idx[c], w) for c, w in history if c in model.id_to_idx]
        pool = self.candidate_pool(user.languages)
        personal = np.zeros(pool.size, dtype=np.float32)
        if pairs:
            hist_idx = np.fromiter((i for i, _ in pairs), np.int64, len(pairs))
            hist_w = np.fromiter((w for _, w in pairs), np.float32, len(pairs))
            neighbors = model.neighbors[hist_idx]
            valid = neighbors >= 0
            contributions = (model.similarity[hist_idx] * hist_w[:, None])[valid]
            flat = neighbors[valid].astype(np.int64)
            reached, inverse = np.unique(flat, return_inverse=True)
            sums = np.bincount(inverse, weights=contributions, minlength=reached.size)
            pool = np.union1d(reached, pool)
            personal = np.zeros(pool.size, dtype=np.float32)
            personal[np.searchsorted(pool, reached)] = sums
        sub = table.take(pool)
        base = score_items(sub, user, FOR_YOU_PROFILE, context, today_day)
        strength = float(sum(w for _, w in pairs))
        beta = strength / (strength + HISTORY_CONFIDENCE)
        peak = float(personal.max()) if personal.size else 0.0
        normalized = personal / peak if peak > 0 else personal
        explore = EXPLORATION / np.sqrt(1.0 + model.interactions[pool])
        weight = PERSONAL_WEIGHT * beta
        final = base * (1.0 - weight) + weight * normalized + explore
        seen = {i for i, _ in pairs} | {model.id_to_idx[c] for c in exclude_ids if c in model.id_to_idx}
        blocked = ((sub.release_day > today_day) & (sub.release_day != NO_DATE)) | np.isin(pool, list(seen))
        final = np.where(blocked, -np.inf, final).astype(np.float32)
        head = top_k(final, max(k * 8, 120), sub.ids)
        head = head[np.isfinite(final[head])]
        picks = mmr_select(final[head], sub.diversity_features()[head], k, diversity)
        return [(int(sub.ids[head[j]]), float(final[head[j]])) for j in picks]
