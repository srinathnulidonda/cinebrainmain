# app/utils.py

import re
import unicodedata
from collections.abc import Iterable
from datetime import UTC, date, datetime

from app.core.constants import FALLBACK_LANGS, INDIAN_LANGUAGES, REGION_LANGUAGE_MAP, TMDB_IMAGE_BASE_URL

INDIAN_LANGS_SET = frozenset(INDIAN_LANGUAGES)
_LANG_RE = re.compile(r"^[a-z]{2,3}$")
_ZODIAC = [
    ((1, 20), "Aquarius"),
    ((2, 19), "Pisces"),
    ((3, 21), "Aries"),
    ((4, 20), "Taurus"),
    ((5, 21), "Gemini"),
    ((6, 21), "Cancer"),
    ((7, 23), "Leo"),
    ((8, 23), "Virgo"),
    ((9, 23), "Libra"),
    ((10, 23), "Scorpio"),
    ((11, 22), "Sagittarius"),
    ((12, 22), "Capricorn"),
]
_SIZES = {
    "poster": {"small": "w185", "medium": "w342", "large": "w500"},
    "backdrop": {"small": "w300", "medium": "w780", "large": "w1280"},
    "profile": {"small": "w45", "medium": "w185", "large": "h632"},
    "still": {"small": "w92", "medium": "w185", "large": "w300"},
}


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower().strip()
    text = re.sub(r"[\s_]+", "-", re.sub(r"[^\w\s-]", "", text))
    return re.sub(r"-+", "-", text).strip("-") or "untitled"


def normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", query.strip()).lower()


def today() -> date:
    return datetime.now(UTC).date()


def parse_iso_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except (ValueError, TypeError):
        return None


def calculate_age(birthday: date | None, deathday: date | None = None) -> int | None:
    if not birthday:
        return None
    end = deathday or today()
    return end.year - birthday.year - ((end.month, end.day) < (birthday.month, birthday.day))


def get_zodiac_sign(birthday: date | None) -> str | None:
    if not birthday:
        return None
    sign = "Capricorn"
    for start, name in _ZODIAC:
        if (birthday.month, birthday.day) >= start:
            sign = name
    return sign


def format_career_span(start: int | None, end: int | None = None) -> str:
    return "Unknown" if not start else f"{start} - {end or 'Present'}"


def tmdb_image_url(path: str | None, size: str = "original") -> str | None:
    return f"{TMDB_IMAGE_BASE_URL}/{size}{path}" if path else None


def image_url(kind: str, path: str | None, size: str = "large") -> str | None:
    return tmdb_image_url(path, _SIZES[kind].get(size, size))


def normalize_langs(values: Iterable[str] | None, limit: int = 6) -> list[str]:
    out: list[str] = []
    for raw in values or ():
        lang = (raw or "").strip().lower()
        if _LANG_RE.match(lang) and lang not in out:
            out.append(lang)
    return out[:limit]


def merge_langs(primary: list[str], secondary: list[str]) -> list[str]:
    merged = list(dict.fromkeys([*primary, *secondary]))
    if "en" not in merged:
        merged.append("en")
    return merged[:6]


def ensure_english(langs: list[str], limit: int = 6) -> list[str]:
    langs = langs[:limit]
    if "en" not in langs:
        langs = [*langs[: limit - 1], "en"] if len(langs) >= limit else [*langs, "en"]
    return langs


def parse_accept_language(header: str | None) -> list[str]:
    weighted = []
    for idx, part in enumerate((header or "").split(",")[:10]):
        tag, _, params = part.strip().partition(";")
        if not tag or tag == "*":
            continue
        try:
            q = float(params.strip()[2:]) if params.strip().startswith("q=") else 1.0
        except ValueError:
            q = 0.0
        if q > 0:
            weighted.append((-q, idx, tag.replace("_", "-").partition("-")[0].lower()))
    return normalize_langs(lang for _, _, lang in sorted(weighted))


def resolve_primary_langs(country: str, geo_langs: list[str]) -> list[str]:
    if country == "IN" and geo_langs:
        indian = [lang for lang in geo_langs if lang in INDIAN_LANGS_SET]
        others = [lang for lang in geo_langs if lang not in INDIAN_LANGS_SET]
        return merge_langs(indian + [lang for lang in FALLBACK_LANGS if lang not in indian and lang not in others], [])
    if country in REGION_LANGUAGE_MAP:
        return list(dict.fromkeys(REGION_LANGUAGE_MAP[country] + ["en"]))[:6]
    return list(FALLBACK_LANGS)
