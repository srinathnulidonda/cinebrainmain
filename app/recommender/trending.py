# app/recommender/trending.py

import numpy as np

from app.core.constants import FALLBACK_LANGS
from app.recommender.items import freshness, popularity_norm, top_k
from app.recommender.model import RecommenderModel

SCOPE_TYPES = ("all", "movie", "tv")


def build_trending_lists(
    model: RecommenderModel, recent_engagement: np.ndarray, today_day: int, top_n: int = 100
) -> dict[str, list[list[float]]]:
    t = model.table
    engagement = np.log1p(recent_engagement)
    engagement = engagement / engagement.max() if engagement.size and engagement.max() > 0 else engagement
    score = (
        0.45 * popularity_norm(t.popularity)
        + 0.25 * t.trending
        + 0.20 * engagement
        + 0.10 * freshness(t.release_day, today_day, 45.0, None)
    ).astype(np.float32)
    base = (t.release_day <= today_day) & t.has_poster
    scopes = {"all": base}
    for lang in FALLBACK_LANGS:
        idx = t.lang_vocab.get(lang)
        if idx is not None:
            scopes[lang] = base & (t.lang_ids[:, 0] == idx)
    lists: dict[str, list[list[float]]] = {}
    for scope, scope_mask in scopes.items():
        for kind, kind_mask in (("all", None), ("movie", ~t.is_tv), ("tv", t.is_tv)):
            members = np.flatnonzero(scope_mask if kind_mask is None else scope_mask & kind_mask)
            order = top_k(score[members], top_n, t.ids[members]) if members.size else []
            lists[f"{scope}:{kind}"] = [[int(t.ids[members[j]]), float(score[members[j]])] for j in order]
    return lists
