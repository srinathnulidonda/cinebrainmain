# app/infra/tmdb.py

from datetime import date, timedelta
from typing import Any

from app.infra.http import ResilientClient

_DISCOVER_PARAMS = {
    "primary_release_date_gte": "primary_release_date.gte",
    "primary_release_date_lte": "primary_release_date.lte",
    "first_air_date_gte": "first_air_date.gte",
    "first_air_date_lte": "first_air_date.lte",
    "vote_average_gte": "vote_average.gte",
    "vote_count_gte": "vote_count.gte",
}


class TMDBClient:
    def __init__(self, http: ResilientClient, api_key: str):
        self.http = http
        self._key = api_key

    def _get(self, path: str, **params: Any):
        return self.http.get_json(path, {"api_key": self._key, **params})

    def _discover(self, media: str, page: int = 1, sort_by: str = "popularity.desc", **filters: Any):
        extra = {_DISCOVER_PARAMS.get(k, k): v for k, v in filters.items() if v is not None}
        return self._get(f"/discover/{media}", page=page, sort_by=sort_by, include_adult="false", **extra)

    def movie(self, tmdb_id: int, append: str):
        return self._get(f"/movie/{tmdb_id}", append_to_response=append)

    def tv(self, tmdb_id: int, append: str):
        return self._get(f"/tv/{tmdb_id}", append_to_response=append)

    def person(self, tmdb_id: int):
        return self._get(f"/person/{tmdb_id}", append_to_response="combined_credits,images,external_ids")

    def search_multi(self, query: str, page: int = 1):
        return self._get("/search/multi", query=query, page=page, language="en-US", include_adult="false")

    def trending(self, media_type: str = "all", window: str = "week", page: int = 1):
        return self._get(f"/trending/{media_type}/{window}", page=page)

    def discover(self, media: str, **filters: Any):
        return self._discover(media, **filters)

    def upcoming(self, page: int = 1, region: str = "US"):
        return self._get("/movie/upcoming", page=page, region=region)

    def videos(self, media: str, tmdb_id: int):
        return self._get(f"/{media}/{tmdb_id}/videos")

    def new_releases(self, media: str, language: str | None = None, page: int = 1, window_days: int = 30):
        now = date.today()
        field = "primary_release_date" if media == "movie" else "first_air_date"
        return self._discover(
            media,
            page=page,
            with_original_language=language,
            **{f"{field}_gte": (now - timedelta(days=window_days)).isoformat(), f"{field}_lte": now.isoformat()},
        )

    def upcoming_discover(self, language: str | None = None, page: int = 1, days_ahead: int = 180):
        now = date.today()
        return self._discover(
            "movie",
            page=page,
            with_original_language=language,
            primary_release_date_gte=(now + timedelta(days=1)).isoformat(),
            primary_release_date_lte=(now + timedelta(days=days_ahead)).isoformat(),
        )

    def critics_choice(self, page: int = 1):
        return self._discover("movie", page=page, sort_by="vote_average.desc", vote_count_gte=200, vote_average_gte=7.5)
