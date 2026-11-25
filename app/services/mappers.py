# app/services/mappers.py

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any

from app import schemas as S
from app.core.constants import GENRE_MAP, MAX_BACKDROPS, MAX_POSTERS, MAX_STILLS
from app.models import Content, Person
from app.recommender.explain import time_commitment
from app.utils import image_url, parse_iso_date, slugify, tmdb_image_url, today

IMPORTANT_JOBS = {"Director", "Writer", "Screenplay", "Creator", "Producer", "Executive Producer"}
WRITER_JOBS = ("Writer", "Screenplay", "Creator")
PRODUCER_JOBS = ("Producer", "Executive Producer")
REGION_PRIORITY = ("IN", "US", "GB")


def trailer_id_from_videos(videos: dict | None) -> str | None:
    youtube = [v for v in (videos or {}).get("results", []) if (v.get("site") or "").lower() == "youtube"]
    for kind, official_only in (("trailer", True), ("trailer", False), ("teaser", False)):
        for video in youtube:
            if (video.get("type") or "").lower() == kind and (video.get("official", True) or not official_only):
                return video.get("key")
    return None


def parse_tmdb_row(raw: dict, content_type: str) -> dict:
    genres = [
        g.get("name", "") if isinstance(g, dict) else GENRE_MAP.get(g, str(g))
        for g in raw.get("genres", raw.get("genre_ids", []))
    ]
    languages = [raw["original_language"]] if raw.get("original_language") else []
    languages += [c for s in raw.get("spoken_languages", []) if (c := s.get("iso_639_1")) and c not in languages]
    runtime = raw.get("runtime") or next(iter(raw.get("episode_run_time") or []), None)
    return {
        "tmdb_id": raw.get("id") or None,
        "title": raw.get("title") or raw.get("name", ""),
        "original_title": raw.get("original_title") or raw.get("original_name"),
        "content_type": content_type,
        "genres": [g for g in genres if g],
        "languages": languages,
        "release_date": parse_iso_date(raw.get("release_date") or raw.get("first_air_date")),
        "runtime": runtime,
        "rating": raw.get("vote_average"),
        "vote_count": raw.get("vote_count", 0),
        "popularity": raw.get("popularity", 0.0),
        "overview": raw.get("overview"),
        "poster_path": raw.get("poster_path"),
        "backdrop_path": raw.get("backdrop_path"),
    }


def to_card(content: Content, **extra: Any) -> S.ContentCard:
    extra.setdefault("time_commitment", time_commitment(content))
    return S.ContentCard.from_content(
        content,
        poster_url=image_url("poster", content.poster_path),
        backdrop_url=image_url("backdrop", content.backdrop_path),
        **extra,
    )


def to_cards(items: Iterable[Content]) -> list[S.ContentCard]:
    return [to_card(c) for c in items]


def build_streaming_info(raw: dict) -> tuple[S.StreamingOut | None, bool]:
    results = (raw.get("watch/providers") or {}).get("results") or {}
    region = next((results[r] for r in REGION_PRIORITY if r in results), None) or next(iter(results.values()), None)
    if not region:
        return None, False

    def providers(key: str) -> list[S.StreamingProviderOut]:
        return sorted(
            (
                S.StreamingProviderOut(
                    provider_name=p.get("provider_name", ""),
                    provider_id=p.get("provider_id", 0),
                    logo_url=tmdb_image_url(p.get("logo_path"), "w92"),
                    display_priority=p.get("display_priority", 0),
                )
                for p in region.get(key) or []
            ),
            key=lambda p: p.display_priority,
        )

    out = S.StreamingOut(
        flatrate=providers("flatrate"), rent=providers("rent"), buy=providers("buy"), link=region.get("link")
    )
    return out, bool(out.flatrate or out.rent or out.buy)


def similar_item(content: Content) -> S.SimilarItemOut:
    year = content.release_date.year if content.release_date else None
    names = [
        GENRE_MAP.get(g, g)
        if isinstance(g, int)
        else g.get("name", str(g))
        if isinstance(g, dict)
        else str(g).replace("_", " ").title()
        for g in content.genres or []
    ]
    return S.SimilarItemOut(
        content_type=content.content_type,
        genres=[str(n) for n in names],
        id=content.id,
        poster_url=image_url("poster", content.poster_path),
        rating=content.rating,
        release_date=content.release_date,
        runtime=content.runtime,
        slug=f"{slugify(content.title)}-{year}" if year else slugify(content.title),
        title=content.title,
        year=year,
    )


def assemble_cast(entries: Sequence[tuple]) -> S.CastCrewOut:
    cast, groups = [], {"directors": [], "producers": [], "writers": []}
    for person, role, character, job, department, order in entries:
        if role == "cast":
            cast.append(
                S.CastMemberOut(
                    id=person.id,
                    tmdb_id=person.tmdb_id,
                    name=person.name,
                    character=character,
                    profile_url=image_url("profile", person.profile_path),
                    order=order,
                    gender=person.gender,
                    known_for_department=person.known_for_department,
                )
            )
            continue
        member = S.CrewMemberOut(
            id=person.id,
            tmdb_id=person.tmdb_id,
            name=person.name,
            job=job,
            department=department,
            profile_url=image_url("profile", person.profile_path),
        )
        group = (
            "directors"
            if job == "Director"
            else "producers"
            if job in PRODUCER_JOBS
            else "writers"
            if job in WRITER_JOBS
            else None
        )
        if group:
            groups[group].append(member)
    return S.CastCrewOut(cast=cast, crew=S.CrewGroupOut(**groups))


def person_detail(person: Person, raw: dict, filmography: S.FilmographyOut, known_for: int) -> S.PersonDetailOut:
    known = sorted(
        filmography.as_actor + filmography.as_director,
        key=lambda e: ((e.rating or 0) * 10 + e.popularity) / 2,
        reverse=True,
    )[:known_for]
    stats, ext = filmography.stats, raw.get("external_ids") or {}
    from app.utils import calculate_age, format_career_span, get_zodiac_sign

    span = (
        format_career_span(stats.first_year, stats.last_year if person.deathday else None)
        if stats and stats.first_year
        else "Unknown"
    )
    return S.PersonDetailOut(
        id=person.id,
        tmdb_id=person.tmdb_id,
        name=person.name,
        biography=person.biography,
        birthday=person.birthday,
        deathday=person.deathday,
        place_of_birth=person.place_of_birth,
        poster_path=person.profile_path,
        backdrop_path=person.backdrop_path,
        profile_path=person.profile_path,
        popularity=person.popularity,
        known_for_department=person.known_for_department,
        gender=person.gender,
        also_known_as=person.also_known_as or [],
        personal_info=S.PersonalInfoOut(
            age=calculate_age(person.birthday, person.deathday),
            zodiac_sign=get_zodiac_sign(person.birthday),
            nationality=(person.place_of_birth or "").rsplit(",", 1)[-1].strip() or None,
            career_span=span,
            birth_name=person.also_known_as[0] if person.also_known_as else None,
        ),
        social_media=S.PersonSocialOut(
            **{
                k: ext.get(k)
                for k in ("imdb_id", "facebook_id", "instagram_id", "twitter_id", "tiktok_id", "youtube_id")
            },
            homepage=raw.get("homepage"),
        ),
        filmography=filmography,
        known_for=S.KnownForOut(items=known),
        images={
            "profiles": [
                tmdb_image_url(p["file_path"], "w185")
                for p in (raw.get("images") or {}).get("profiles", [])[:5]
                if p.get("file_path")
            ]
        },
    )


def extract_trailer(raw: dict) -> S.TrailerOut | None:
    videos = raw.get("videos")
    if not (yt_id := trailer_id_from_videos(videos)):
        return None
    name = next((v.get("name") for v in (videos or {}).get("results", []) if v.get("key") == yt_id), None)
    return S.TrailerOut(
        youtube_id=yt_id,
        url=f"https://www.youtube.com/watch?v={yt_id}",
        name=name,
        thumbnail=f"https://img.youtube.com/vi/{yt_id}/hqdefault.jpg",
    )


def build_gallery(raw: dict) -> S.GalleryOut:
    images = raw.get("images") or {}

    def build(key: str, limit: int, thumb: str, full: str, ratio: float) -> list[S.GalleryImageOut]:
        return [
            S.GalleryImageOut(
                aspect_ratio=i.get("aspect_ratio", ratio),
                height=i.get("height", 0),
                width=i.get("width", 0),
                thumbnail=tmdb_image_url(i["file_path"], thumb) or "",
                url=tmdb_image_url(i["file_path"], full) or "",
            )
            for i in images.get(key, [])[:limit]
            if i.get("file_path")
        ]

    return S.GalleryOut(
        backdrops=build("backdrops", MAX_BACKDROPS, "w780", "w1280", 1.778),
        posters=build("posters", MAX_POSTERS, "w185", "w500", 0.667),
        stills=build("stills", MAX_STILLS, "w185", "w300", 1.778),
    )


def build_metadata(raw: dict, tv: bool = False) -> S.MetadataOut:
    def companies(items: list[dict]) -> list[S.ProductionCompanyOut]:
        return [
            S.ProductionCompanyOut(
                id=i.get("id"), name=i.get("name", ""), logo=tmdb_image_url(i.get("logo_path"), "w92")
            )
            for i in items
        ]

    certs: dict[str, str] = {}
    if tv:
        for r in (raw.get("content_ratings") or {}).get("results", []):
            if r.get("rating"):
                certs.setdefault(r.get("iso_3166_1", ""), r["rating"])
    else:
        for r in (raw.get("release_dates") or {}).get("results", []):
            for rd in r.get("release_dates", []):
                if rd.get("certification"):
                    certs.setdefault(r.get("iso_3166_1", ""), rd["certification"])
    genres = [g.get("name", "") if isinstance(g, dict) else str(g) for g in raw.get("genres", [])]
    fields: dict[str, Any] = {
        "certifications": certs,
        "genres": [g for g in genres if g],
        "original_language": raw.get("original_language"),
        "popularity": raw.get("popularity", 0.0),
        "production_companies": companies(raw.get("production_companies", [])),
        "spoken_languages": [
            S.SpokenLanguageOut(code=x.get("iso_639_1", ""), name=x.get("english_name", x.get("name", "")))
            for x in raw.get("spoken_languages", [])
        ],
        "status": raw.get("status"),
    }
    if tv:
        fields.update(
            release_date=parse_iso_date(raw.get("first_air_date")),
            runtime=next(iter(raw.get("episode_run_time") or []), None),
            networks=companies(raw.get("networks", [])),
            episode_run_time=raw.get("episode_run_time", []),
            created_by=[
                {
                    "id": c.get("id"),
                    "name": c.get("name", ""),
                    "profile_url": tmdb_image_url(c.get("profile_path"), "w185"),
                }
                for c in raw.get("created_by", [])
            ],
        )
    else:
        fields.update(
            budget=raw.get("budget") or None,
            revenue=raw.get("revenue") or None,
            runtime=raw.get("runtime"),
            release_date=parse_iso_date(raw.get("release_date")),
            production_countries=[c.get("name", "") for c in raw.get("production_countries", [])],
        )
    return S.MetadataOut(**fields)


def build_synopsis(raw: dict, tv: bool = False) -> S.SynopsisOut:
    kw = raw.get("keywords") or {}
    items = kw.get("results" if tv else "keywords", []) if isinstance(kw, dict) else []
    return S.SynopsisOut(
        overview=raw.get("overview"),
        plot=raw.get("overview"),
        tagline=raw.get("tagline"),
        keywords=[k["name"] for k in items if k.get("name")],
    )


def _episode(ep: dict | None) -> S.EpisodeOut | None:
    return ep and S.EpisodeOut(
        episode_number=ep.get("episode_number", 0),
        name=ep.get("name"),
        overview=ep.get("overview"),
        air_date=parse_iso_date(ep.get("air_date")),
        runtime=ep.get("runtime"),
        still_url=image_url("still", ep.get("still_path")),
        rating=ep.get("vote_average"),
        vote_count=ep.get("vote_count", 0),
    )


def build_seasons_episodes(raw: dict) -> S.SeasonsEpisodesOut:
    return S.SeasonsEpisodesOut(
        number_of_seasons=raw.get("number_of_seasons"),
        number_of_episodes=raw.get("number_of_episodes"),
        in_production=raw.get("in_production"),
        next_episode=_episode(raw.get("next_episode_to_air")),
        last_episode=_episode(raw.get("last_episode_to_air")),
        seasons=[
            S.SeasonOut(
                season_number=s.get("season_number", 0),
                name=s.get("name"),
                overview=s.get("overview"),
                air_date=parse_iso_date(s.get("air_date")),
                episode_count=s.get("episode_count", 0),
                poster_url=image_url("poster", s.get("poster_path")),
            )
            for s in raw.get("seasons", [])
        ],
    )


def build_ratings(raw: dict) -> S.RatingsOut:
    avg = round(raw.get("vote_average") or 0, 1)
    return S.RatingsOut(
        composite_score=avg or None,
        tmdb=S.TMDBRatingOut(score=avg, count=raw.get("vote_count", 0)),
        imdb=S.IMDBRatingOut(score=0, votes="N/A"),
    )


def _credit(raw: dict, role: str, **extra) -> S.FilmographyEntryOut:
    released = parse_iso_date(raw.get("release_date") or raw.get("first_air_date"))
    return S.FilmographyEntryOut(
        tmdb_id=raw.get("id", 0),
        title=raw.get("title") or raw.get("name", ""),
        content_type="movie" if raw.get("media_type", "movie") == "movie" else "tv",
        role=role,
        release_date=released,
        year=released.year if released else None,
        poster_url=image_url("poster", raw.get("poster_path")),
        rating=raw.get("vote_average"),
        popularity=raw.get("popularity", 0.0),
        vote_count=raw.get("vote_count", 0),
        **extra,
    )


def build_filmography(raw: dict) -> S.FilmographyOut:
    credits = raw.get("combined_credits") or {}
    groups: dict[str, list[S.FilmographyEntryOut]] = {"actor": [], "director": [], "writer": [], "producer": []}
    everything = []
    for c in credits.get("cast", []):
        groups["actor"].append(entry := _credit(c, "actor", character=c.get("character")))
        everything.append(entry)
    for c in credits.get("crew", []):
        job = c.get("job", "")
        entry = _credit(c, "crew", job=job, department=c.get("department"))
        everything.append(entry)
        kind = (
            "director"
            if job == "Director"
            else "writer"
            if job in ("Writer", "Screenplay", "Story")
            else "producer"
            if job in ("Producer", "Executive Producer")
            else None
        )
        if kind:
            groups[kind].append(entry)
    for g in groups.values():
        g.sort(key=lambda e: e.release_date or date.min, reverse=True)

    by_year, by_decade, upcoming = defaultdict(list), defaultdict(list), []
    for e in everything:
        if e.release_date:
            upcoming += [e] if e.release_date > today() else []
            by_year[str(e.release_date.year)].append(e)
            by_decade[f"{e.release_date.year // 10 * 10}s"].append(e)
    years = [e.year for e in everything if e.year]
    ratings = [e.rating for e in everything if e.rating and e.rating > 0]
    return S.FilmographyOut(
        as_actor=groups["actor"],
        as_director=groups["director"],
        as_writer=groups["writer"],
        as_producer=groups["producer"],
        by_year=dict(sorted(by_year.items(), reverse=True)),
        by_decade=dict(sorted(by_decade.items(), reverse=True)),
        upcoming=upcoming,
        stats=S.FilmographyStatsOut(
            total_credits=len(everything),
            average_rating=round(sum(ratings) / len(ratings), 1) if ratings else None,
            years_active=max(years) - min(years) + 1 if years else 0,
            first_year=min(years, default=None),
            last_year=max(years, default=None),
            total_as_actor=len(groups["actor"]),
            total_as_director=len(groups["director"]),
            total_as_writer=len(groups["writer"]),
            total_as_producer=len(groups["producer"]),
        ),
    )
