# app/routers/common.py

from typing import Annotated, Any, Literal

from fastapi import Path, Query

from app.core.constants import MAX_PAGE
from app.core.logging import request_id_var

Page = Annotated[int, Query(ge=1, le=MAX_PAGE)]
Limit = Annotated[int, Query(ge=1, le=50)]
Lang = Annotated[str, Query(pattern=r"^[a-z]{2,3}$")]
Year = Annotated[int, Query(ge=1888, le=2100)]
ContentId = Annotated[int, Path(gt=0, le=2_147_483_647)]
TmdbId = Annotated[int, Path(gt=0, le=999_999_999)]
Slug = Annotated[str, Path(pattern=r"^[A-Za-z_]{2,30}$")]
MediaFilter = Literal["all", "movie", "tv"]
MediaType = Literal["movie", "tv"]
SortKey = Literal["popularity", "rating", "release_date", "alpha"]
FeedLanguage = Literal["te", "hi", "ta", "ml", "kn", "en"]
ListKind = Literal["watchlist", "favorite"]
Mood = Literal[
    "action",
    "comedy",
    "drama",
    "thriller",
    "horror",
    "romance",
    "scary",
    "funny",
    "emotional",
    "intelligent",
    "easy_watch",
    "cinematic",
    "binge",
]
Situation = Literal["date_night", "family_night", "solo_night", "weekend_binge", "quick_watch", "movie_night"]
LanguageList = Annotated[str, Query(pattern=r"^[a-z]{2,3}(,[a-z]{2,3}){0,5}$")]
GenreList = Annotated[str, Query(pattern=r"^[A-Za-z _,&-]{2,120}$")]
TextQuery = Annotated[str, Query(min_length=1, max_length=200)]


def ok(
    data: Any, *, page: int | None = None, limit: int | None = None, has_more: bool = False, total: int | None = None
) -> dict:
    pagination = (
        {"page": page, "limit": limit, "has_more": has_more, "total": total}
        if page is not None and limit is not None
        else None
    )
    return {"success": True, "data": data, "meta": {"request_id": request_id_var.get(), "pagination": pagination}}
