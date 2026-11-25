# app/recommender/model.py

import io
import json
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

import numpy as np
from scipy import sparse

from app.recommender.items import ItemTable, day_number, freshness, popularity_norm, rating_confidence, top_k

_TABLE_ARRAYS = (
    "ids",
    "is_tv",
    "popularity",
    "rating",
    "votes",
    "release_day",
    "has_poster",
    "trending",
    "lang_ids",
    "has_indian",
    "has_en",
    "has_lang",
)
TOP_PRIOR_SIZE = 5000
LANG_TOP_SIZE = 400


@dataclass(slots=True)
class RecommenderModel:
    version: str
    built_at: float
    table: ItemTable
    neighbors: np.ndarray
    similarity: np.ndarray
    interactions: np.ndarray
    prior: np.ndarray
    top_prior: np.ndarray
    lang_top: np.ndarray
    id_to_idx: dict[int, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id_to_idx:
            self.id_to_idx = {int(v): i for i, v in enumerate(self.table.ids)}

    def to_bytes(self) -> bytes:
        t = self.table
        buffer = io.BytesIO()
        meta = {"version": self.version, "built_at": self.built_at, "lang_vocab": t.lang_vocab}
        np.savez_compressed(
            buffer,
            **{name: getattr(t, name) for name in _TABLE_ARRAYS},
            genre_data=t.genres.data,
            genre_indices=t.genres.indices,
            genre_indptr=t.genres.indptr,
            genre_shape=np.array(t.genres.shape),
            neighbors=self.neighbors,
            similarity=self.similarity,
            interactions=self.interactions,
            prior=self.prior,
            top_prior=self.top_prior,
            lang_top=self.lang_top,
            meta=np.frombuffer(json.dumps(meta).encode(), dtype=np.uint8),
        )
        return buffer.getvalue()

    @classmethod
    def from_bytes(cls, data: bytes) -> "RecommenderModel":
        with np.load(io.BytesIO(data), allow_pickle=False) as npz:
            meta = json.loads(bytes(npz["meta"]).decode())
            genres = sparse.csr_matrix(
                (npz["genre_data"], npz["genre_indices"], npz["genre_indptr"]), shape=tuple(npz["genre_shape"])
            )
            table = ItemTable(
                **{name: npz[name] for name in _TABLE_ARRAYS}, genres=genres, lang_vocab=meta["lang_vocab"]
            )
            return cls(
                version=meta["version"],
                built_at=meta["built_at"],
                table=table,
                neighbors=npz["neighbors"],
                similarity=npz["similarity"],
                interactions=npz["interactions"],
                prior=npz["prior"],
                top_prior=npz["top_prior"],
                lang_top=npz["lang_top"],
            )


def content_features(t: ItemTable) -> sparse.csr_matrix:
    n = len(t)
    df = np.asarray(t.genres.sum(axis=0)).ravel()
    idf = (np.log((1.0 + n) / (1.0 + df)) + 1.0).astype(np.float32)
    genre_block = t.genres @ sparse.diags(idf)
    primary = t.lang_ids[:, 0].astype(np.int64)
    has_primary = primary >= 0
    vocab_size = max(len(t.lang_vocab), 1)
    lang_df = np.bincount(primary[has_primary], minlength=vocab_size).astype(np.float32)
    lang_idf = np.log((1.0 + n) / (1.0 + lang_df)) + 1.0
    rows = np.flatnonzero(has_primary)
    lang_block = sparse.csr_matrix(
        (0.6 * lang_idf[primary[rows]], (rows, primary[rows])), shape=(n, vocab_size), dtype=np.float32
    )
    year = np.where(t.release_day == np.iinfo(np.int32).min, -1, (t.release_day // 1826).astype(np.int64))
    dated = np.flatnonzero(year >= 0)
    buckets = int(year.max()) + 1 if dated.size else 1
    decade_block = sparse.csr_matrix(
        (np.full(dated.size, 0.3, dtype=np.float32), (dated, year[dated])), shape=(n, buckets)
    )
    type_block = sparse.csr_matrix(
        (np.full(n, 0.4, dtype=np.float32), (np.arange(n), t.is_tv.astype(np.int64))), shape=(n, 2)
    )
    features = sparse.hstack([genre_block, lang_block, decade_block, type_block], format="csr", dtype=np.float32)
    norms = np.sqrt(np.asarray(features.multiply(features).sum(axis=1)).ravel())
    norms[norms == 0] = 1.0
    return (sparse.diags(1.0 / norms).astype(np.float32) @ features).tocsr()


def content_neighbors(
    features: sparse.csr_matrix, k: int, max_cells: int = 16_000_000
) -> tuple[np.ndarray, np.ndarray]:
    n = features.shape[0]
    k = max(0, min(k, n - 1))
    neighbors = np.full((n, k), -1, dtype=np.int32)
    similarity = np.zeros((n, k), dtype=np.float32)
    if k == 0:
        return neighbors, similarity
    transposed = features.T.tocsr()
    chunk = max(1, min(n, max_cells // n))
    for start in range(0, n, chunk):
        stop = min(start + chunk, n)
        block = (features[start:stop] @ transposed).toarray()
        block[np.arange(stop - start), np.arange(start, stop)] = -1.0
        idx = np.argpartition(-block, k - 1, axis=1)[:, :k]
        vals = np.take_along_axis(block, idx, axis=1)
        order = np.argsort(-vals, axis=1)
        idx, vals = np.take_along_axis(idx, order, axis=1), np.take_along_axis(vals, order, axis=1)
        keep = vals > 0
        neighbors[start:stop] = np.where(keep, idx, -1)
        similarity[start:stop] = np.where(keep, vals, 0.0)
    return neighbors, similarity


def select_top_k(rows: np.ndarray, cols: np.ndarray, vals: np.ndarray, k: int):
    if rows.size == 0:
        return rows, cols, vals, np.empty(0, dtype=np.int64)
    order = np.lexsort((cols, -vals, rows))
    rows, cols, vals = rows[order], cols[order], vals[order]
    starts = np.flatnonzero(np.r_[True, rows[1:] != rows[:-1]])
    counts = np.diff(np.r_[starts, rows.size])
    rank = np.arange(rows.size) - np.repeat(starts, counts)
    keep = rank < k
    return rows[keep], cols[keep], vals[keep], rank[keep]


def collaborative_neighbors(
    session_codes: np.ndarray,
    item_idx: np.ndarray,
    weights: np.ndarray,
    n_items: int,
    k: int,
    shrinkage: float,
    chunk: int = 2000,
) -> sparse.csr_matrix:
    empty = sparse.csr_matrix((n_items, n_items), dtype=np.float32)
    if session_codes.size == 0 or k <= 0:
        return empty
    n_sessions = int(session_codes.max()) + 1
    ratings = sparse.csr_matrix((weights.astype(np.float32), (session_codes, item_idx)), shape=(n_sessions, n_items))
    ratings.data = np.log1p(ratings.data).astype(np.float32)
    ratings = sparse.diags((np.diff(ratings.indptr) >= 2).astype(np.float32)) @ ratings
    ratings.eliminate_zeros()
    if ratings.nnz == 0:
        return empty
    binary = ratings.copy()
    binary.data[:] = 1.0
    norms = np.sqrt(np.asarray(ratings.multiply(ratings).sum(axis=0)).ravel())
    norms[norms == 0] = 1.0
    normalized = (ratings @ sparse.diags((1.0 / norms).astype(np.float32))).tocsr()
    norm_t, bin_t = normalized.T.tocsr(), binary.T.tocsr()
    out_r, out_c, out_v = [], [], []
    for start in range(0, n_items, chunk):
        stop = min(start + chunk, n_items)
        sim = (norm_t[start:stop] @ normalized).tocsr()
        co = (bin_t[start:stop] @ binary).tocsr()
        co.data = co.data / (co.data + shrinkage)
        shrunk = sim.multiply(co).tocoo()
        keep = (shrunk.row + start != shrunk.col) & (shrunk.data > 0)
        r, c, v, _ = select_top_k(shrunk.row[keep] + start, shrunk.col[keep], shrunk.data[keep], k)
        out_r.append(r), out_c.append(c), out_v.append(v)
    rows, cols, vals = (np.concatenate(x) if x else np.empty(0) for x in (out_r, out_c, out_v))
    return sparse.csr_matrix((vals.astype(np.float32), (rows, cols)), shape=(n_items, n_items))


def blend_neighbors(
    content_nbr: np.ndarray,
    content_sim: np.ndarray,
    collab: sparse.csr_matrix,
    interactions: np.ndarray,
    confidence: float,
    k: int,
) -> tuple[np.ndarray, np.ndarray]:
    n = content_nbr.shape[0]
    mask = content_nbr >= 0
    rows = np.repeat(np.arange(n), content_nbr.shape[1])[mask.ravel()]
    content = sparse.csr_matrix((content_sim[mask], (rows, content_nbr[mask])), shape=(n, n), dtype=np.float32)
    alpha = (confidence / (confidence + interactions)).astype(np.float32)
    hybrid = (sparse.diags(alpha) @ content + sparse.diags(1.0 - alpha) @ collab).tocoo()
    r, c, v, rank = select_top_k(hybrid.row, hybrid.col, hybrid.data, k)
    neighbors = np.full((n, k), -1, dtype=np.int32)
    similarity = np.zeros((n, k), dtype=np.float32)
    neighbors[r, rank] = c
    similarity[r, rank] = v
    return neighbors, similarity


def build_prior(t: ItemTable, engagement: np.ndarray, today_day: int) -> np.ndarray:
    eng = np.log1p(engagement)
    eng = eng / eng.max() if eng.size and eng.max() > 0 else eng
    fresh = freshness(t.release_day, today_day, 180.0, None)
    prior = (
        0.40 * popularity_norm(t.popularity) + 0.30 * rating_confidence(t.rating, t.votes) + 0.20 * fresh + 0.10 * eng
    )
    return (prior * np.where(t.has_poster, 1.0, 0.85)).astype(np.float32)


def build_model(
    rows: Sequence,
    session_codes: np.ndarray,
    item_ids: np.ndarray,
    weights: np.ndarray,
    *,
    neighbors: int,
    confidence: float,
    shrinkage: float,
    today_day: int | None = None,
) -> RecommenderModel:
    today_day = day_number(date.today()) if today_day is None else today_day
    ordered = sorted(rows, key=lambda r: r.id)
    table = ItemTable.from_rows(ordered)
    n = len(table)
    pos = np.searchsorted(table.ids, item_ids) if n else np.zeros(item_ids.shape, dtype=np.int64)
    valid = (
        (pos < n) & (table.ids[np.minimum(pos, max(n - 1, 0))] == item_ids)
        if n
        else np.zeros(item_ids.shape, dtype=bool)
    )
    item_idx, codes, w = pos[valid], session_codes[valid], weights[valid]
    counts = np.bincount(item_idx, minlength=n).astype(np.int32)
    engagement = np.bincount(item_idx, weights=w, minlength=n).astype(np.float32)
    content_nbr, content_sim = content_neighbors(content_features(table), neighbors)
    collab = collaborative_neighbors(codes, item_idx, w, n, neighbors, shrinkage)
    nbr, sim = blend_neighbors(content_nbr, content_sim, collab, counts, confidence, neighbors)
    prior = build_prior(table, engagement, today_day)
    lang_top = np.full((max(len(table.lang_vocab), 1), LANG_TOP_SIZE), -1, dtype=np.int32)
    primary = table.lang_ids[:, 0]
    for idx in table.lang_vocab.values():
        members = np.flatnonzero(primary == idx)
        best = members[top_k(prior[members], LANG_TOP_SIZE, table.ids[members])]
        lang_top[idx, : best.size] = best
    return RecommenderModel(
        version=uuid.uuid4().hex[:12],
        built_at=time.time(),
        table=table,
        neighbors=nbr,
        similarity=sim,
        interactions=counts,
        prior=prior,
        top_prior=top_k(prior, min(TOP_PRIOR_SIZE, n), table.ids).astype(np.int32),
        lang_top=lang_top,
    )
