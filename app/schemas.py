# app/schemas.py

from datetime import date
from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Pagination(BaseModel):
    page: int
    limit: int
    has_more: bool
    total: int | None = None


class Meta(BaseModel):
    request_id: str
    pagination: Pagination | None = None


class Envelope(BaseModel, Generic[T]):
    success: bool = True
    data: T
    meta: Meta


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any = None


class ErrorEnvelope(BaseModel):
    success: bool = False
    error: ErrorBody
    meta: Meta


class HealthOut(BaseModel):
    status: str


class ReadinessOut(BaseModel):
    status: str
    checks: dict[str, str]


class MessageOut(BaseModel):
    detail: str


class GenreOut(BaseModel):
    id: int
    name: str


class SearchTermOut(BaseModel):
    query: str
    count: int


class VideoItemOut(BaseModel):
    key: str | None = None
    name: str = ""
    type: str = ""
    site: str = "YouTube"
    official: bool = False
    published_at: str | None = None
    size: int = 0


class VideosOut(BaseModel):
    tmdb_id: int
    content_type: str
    videos: list[VideoItemOut] = []
    total: int = 0


class UserContextOut(BaseModel):
    country: str | None = None
    region: str | None = None
    city: str | None = None
    languages: list[str] = []
    language_source: str
    timezone: str | None = None


class GalleryImageOut(BaseModel):
    aspect_ratio: float = 0.0
    height: int = 0
    width: int = 0
    thumbnail: str
    url: str


class GalleryOut(BaseModel):
    backdrops: list[GalleryImageOut] = []
    posters: list[GalleryImageOut] = []
    stills: list[GalleryImageOut] = []


class CastMemberOut(BaseModel):
    id: int
    tmdb_id: int
    name: str
    character: str | None = None
    profile_url: str | None = None
    order: int | None = None
    gender: int | None = None
    known_for_department: str | None = None


class CrewMemberOut(BaseModel):
    id: int
    tmdb_id: int
    name: str
    job: str | None = None
    department: str | None = None
    profile_url: str | None = None


class CrewGroupOut(BaseModel):
    directors: list[CrewMemberOut] = []
    producers: list[CrewMemberOut] = []
    writers: list[CrewMemberOut] = []


class CastCrewOut(BaseModel):
    cast: list[CastMemberOut] = []
    crew: CrewGroupOut = Field(default_factory=CrewGroupOut)


class ProductionCompanyOut(BaseModel):
    id: int | None = None
    name: str
    logo: str | None = None


class SpokenLanguageOut(BaseModel):
    code: str
    name: str


class MetadataOut(BaseModel):
    budget: int | None = None
    certifications: dict[str, str] = {}
    genres: list[str] = []
    is_critics_choice: bool = False
    is_new_release: bool = False
    is_trending: bool = False
    original_language: str | None = None
    popularity: float = 0.0
    production_companies: list[ProductionCompanyOut] = []
    production_countries: list[str] = []
    release_date: date | None = None
    revenue: int | None = None
    runtime: int | None = None
    spoken_languages: list[SpokenLanguageOut] = []
    status: str | None = None
    networks: list[ProductionCompanyOut] | None = None
    created_by: list[dict] | None = None
    episode_run_time: list[int] | None = None


class TMDBRatingOut(BaseModel):
    score: float = 0
    count: int = 0


class IMDBRatingOut(BaseModel):
    score: float = 0
    votes: str = "N/A"


class RatingsOut(BaseModel):
    composite_score: float | None = None
    imdb: IMDBRatingOut = Field(default_factory=IMDBRatingOut)
    tmdb: TMDBRatingOut = Field(default_factory=TMDBRatingOut)


class SynopsisOut(BaseModel):
    keywords: list[str] = []
    overview: str | None = None
    plot: str | None = None
    tagline: str | None = None


class TrailerOut(BaseModel):
    youtube_id: str
    url: str
    name: str | None = None
    thumbnail: str | None = None


class StreamingProviderOut(BaseModel):
    provider_name: str
    provider_id: int
    logo_url: str | None = None
    display_priority: int = 0


class StreamingOut(BaseModel):
    flatrate: list[StreamingProviderOut] = []
    rent: list[StreamingProviderOut] = []
    buy: list[StreamingProviderOut] = []
    link: str | None = None


class SimilarItemOut(BaseModel):
    content_type: str
    genres: list[str] = []
    id: int
    poster_url: str | None = None
    rating: float | None = None
    release_date: date | None = None
    runtime: int | None = None
    slug: str = ""
    title: str
    year: int | None = None
    reason_code: str | None = None
    reason_label: str | None = None


class EpisodeOut(BaseModel):
    episode_number: int
    name: str | None = None
    overview: str | None = None
    air_date: date | None = None
    runtime: int | None = None
    still_url: str | None = None
    rating: float | None = None
    vote_count: int = 0


class SeasonOut(BaseModel):
    season_number: int
    name: str | None = None
    overview: str | None = None
    air_date: date | None = None
    episode_count: int = 0
    poster_url: str | None = None
    episodes: list[EpisodeOut] = []


class SeasonsEpisodesOut(BaseModel):
    number_of_seasons: int | None = None
    number_of_episodes: int | None = None
    in_production: bool | None = None
    seasons: list[SeasonOut] = []
    next_episode: EpisodeOut | None = None
    last_episode: EpisodeOut | None = None


class ContentDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    backdrop_url: str | None = None
    cast_crew: CastCrewOut = Field(default_factory=CastCrewOut)
    content_type: str
    gallery: GalleryOut = Field(default_factory=GalleryOut)
    id: int
    metadata: MetadataOut = Field(default_factory=MetadataOut)
    more_like_this: list[SimilarItemOut] = []
    original_title: str | None = None
    overview: str | None = None
    poster_url: str | None = None
    ratings: RatingsOut = Field(default_factory=RatingsOut)
    seasons_episodes: SeasonsEpisodesOut | None = None
    slug: str = ""
    streaming_info: StreamingOut | None = None
    synopsis: SynopsisOut = Field(default_factory=SynopsisOut)
    title: str
    trailer: TrailerOut | None = None


class RecommendationReason(BaseModel):
    code: str
    label: str
    weight: float = 0.0


class ContentCard(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tmdb_id: int | None = None
    title: str
    original_title: str | None = None
    content_type: str
    genres: list[str] = []
    languages: list[str] = []
    release_date: date | None = None
    runtime: int | None = None
    rating: float | None = None
    vote_count: int = 0
    popularity: float = 0.0
    overview: str | None = None
    poster_url: str | None = None
    backdrop_url: str | None = None
    year: int | None = None
    cinebrain_match: int | None = None
    match_confidence: float | None = None
    time_commitment: str | None = None
    reasons: list[RecommendationReason] = []

    @classmethod
    def from_content(cls, content: Any, **extra: Any) -> "ContentCard":
        year = content.release_date.year if content.release_date else None
        return cls.model_validate(content, from_attributes=True).model_copy(update={"year": year, **extra})


class ContentSearchOut(BaseModel):
    items: list[ContentCard] = []
    total: int = 0
    page: int = 1
    total_pages: int = 0
    query: str = ""


class WatchlistOut(BaseModel):
    items: list[ContentCard] = []
    total: int = 0
    page: int = 1
    limit: int = 50


class RecommendationCard(ContentCard):
    recommendation_score: float = 0.0
    recommendation_reason: str | None = None


class DecideOut(BaseModel):
    primary: Annotated[list[ContentCard], Field(default_factory=list)]
    fallback: Annotated[list[ContentCard], Field(default_factory=list)]
    total: int = 0
    context_summary: Annotated[dict, Field(default_factory=dict)]


class HiddenGemsOut(BaseModel):
    items: Annotated[list[ContentCard], Field(default_factory=list)]
    total: int = 0
    page: int = 1


class ThisWeekOut(BaseModel):
    week_start: str
    week_end: str
    movies: Annotated[list[ContentCard], Field(default_factory=list)]
    tv: Annotated[list[ContentCard], Field(default_factory=list)]
    upcoming: list[ContentCard] = []
    total: int = 0


class LocalTrendingOut(BaseModel):
    region: str | None = None
    items: list[ContentCard] = []
    total: int = 0


class FeedSectionOut(BaseModel):
    title: str
    section_type: str
    items: list[ContentCard] = []
    total: int = 0
    has_more: bool = False


class HomeFeedOut(BaseModel):
    sections: list[FeedSectionOut] = []
    session_id: str | None = None
    detected_region: str | None = None
    detected_languages: list[str] = []


class TrendingOut(BaseModel):
    items: list[ContentCard] = []
    total: int = 0
    page: int = 1
    region: str | None = None


class GenreContentOut(BaseModel):
    genre: str
    items: list[ContentCard] = []
    total: int = 0
    page: int = 1
    has_more: bool = False


class RegionalContentOut(BaseModel):
    language: str
    language_code: str
    items: list[ContentCard] = []
    total: int = 0
    page: int = 1
    has_more: bool = False


class SimilarContentOut(BaseModel):
    source_id: int
    items: list[ContentCard] = []
    total: int = 0


class FeelsLikeOut(BaseModel):
    query: str
    items: list[ContentCard] = []
    total: int = 0


class FilmographyEntryOut(BaseModel):
    content_id: int | None = None
    tmdb_id: int
    title: str
    content_type: str
    role: str | None = None
    character: str | None = None
    job: str | None = None
    department: str | None = None
    release_date: date | None = None
    year: int | None = None
    poster_url: str | None = None
    rating: float | None = None
    popularity: float = 0.0
    vote_count: int = 0


class FilmographyStatsOut(BaseModel):
    total_credits: int = 0
    average_rating: float | None = None
    years_active: int = 0
    first_year: int | None = None
    last_year: int | None = None
    total_as_actor: int = 0
    total_as_director: int = 0
    total_as_writer: int = 0
    total_as_producer: int = 0


class FilmographyOut(BaseModel):
    as_actor: list[FilmographyEntryOut] = []
    as_director: list[FilmographyEntryOut] = []
    as_writer: list[FilmographyEntryOut] = []
    as_producer: list[FilmographyEntryOut] = []
    by_year: dict[str, list[FilmographyEntryOut]] = {}
    by_decade: dict[str, list[FilmographyEntryOut]] = {}
    upcoming: list[FilmographyEntryOut] = []
    stats: FilmographyStatsOut | None = None


class PersonSocialOut(BaseModel):
    imdb_id: str | None = None
    facebook_id: str | None = None
    instagram_id: str | None = None
    twitter_id: str | None = None
    tiktok_id: str | None = None
    youtube_id: str | None = None
    homepage: str | None = None


class PersonalInfoOut(BaseModel):
    age: int | None = None
    zodiac_sign: str | None = None
    nationality: str | None = None
    career_span: str | None = None
    birth_name: str | None = None


class KnownForOut(BaseModel):
    items: list[FilmographyEntryOut] = []


class PersonDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tmdb_id: int
    name: str
    biography: str | None = None
    birthday: date | None = None
    deathday: date | None = None
    place_of_birth: str | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None
    profile_path: str | None = None
    popularity: float = 0.0
    known_for_department: str | None = None
    gender: int | None = None
    also_known_as: list[str] = []
    personal_info: PersonalInfoOut | None = None
    social_media: PersonSocialOut | None = None
    filmography: FilmographyOut | None = None
    known_for: KnownForOut | None = None
    images: dict | None = None
