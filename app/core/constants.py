# app/core/constants.py

from enum import StrEnum


class ContentType(StrEnum):
    MOVIE = "movie"
    TV = "tv"


def _each(places: list[str], lang: str) -> dict[str, list[str]]:
    return {p: [lang] for p in places}


INDIAN_LANGUAGES = ["te", "hi", "ta", "ml", "kn"]
FALLBACK_LANGS = [*INDIAN_LANGUAGES, "en"]
LANGUAGE_NAMES = {
    "te": "Telugu",
    "hi": "Hindi",
    "ta": "Tamil",
    "ml": "Malayalam",
    "kn": "Kannada",
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "zh": "Chinese",
    "th": "Thai",
    "tr": "Turkish",
    "ar": "Arabic",
    "ru": "Russian",
}
REGION_LANGUAGE_MAP = {
    "IN": FALLBACK_LANGS,
    "US": ["en"],
    "GB": ["en"],
    "JP": ["ja", "en"],
    "KR": ["ko", "en"],
    "FR": ["fr", "en"],
    "DE": ["de", "en"],
    "ES": ["es", "en"],
    "IT": ["it", "en"],
    "BR": ["pt", "en"],
    "MX": ["es", "en"],
    "CA": ["en", "fr"],
    "AU": ["en"],
    "RU": ["ru", "en"],
    "TR": ["tr", "en"],
    "TH": ["th", "en"],
    "AE": ["ar", "en"],
    "SA": ["ar", "en"],
    "SG": ["en", "zh"],
}
PLACE_LANGUAGES = {
    "andhra pradesh": ["te"],
    "telangana": ["te"],
    "hyderabad": ["te"],
    "tamil nadu": ["ta"],
    "chennai": ["ta"],
    "kerala": ["ml"],
    "kochi": ["ml"],
    "thiruvananthapuram": ["ml"],
    "karnataka": ["kn"],
    "bengaluru": ["kn"],
    "bangalore": ["kn"],
    "maharashtra": ["hi"],
    "mumbai": ["hi"],
    "delhi": ["hi"],
    "new delhi": ["hi"],
    "uttar pradesh": ["hi"],
    "rajasthan": ["hi"],
    **_each(
        [
            "gujarat",
            "punjab",
            "haryana",
            "bihar",
            "madhya pradesh",
            "chhattisgarh",
            "jharkhand",
            "uttarakhand",
            "himachal pradesh",
            "west bengal",
            "odisha",
            "assam",
            "goa",
            "chandigarh",
            "jammu and kashmir",
            "pune",
            "nagpur",
            "kolkata",
            "ahmedabad",
            "jaipur",
            "lucknow",
            "bhopal",
            "indore",
        ],
        "hi",
    ),
    **_each(
        [
            "secunderabad",
            "visakhapatnam",
            "vijayawada",
            "guntur",
            "tirupati",
            "warangal",
            "nellore",
            "karimnagar",
            "rajahmundry",
            "kurnool",
            "nizamabad",
        ],
        "te",
    ),
    **_each(
        ["puducherry", "pondicherry", "coimbatore", "madurai", "tiruchirappalli", "salem", "tirunelveli", "erode"], "ta"
    ),
    **_each(["lakshadweep", "kozhikode", "thrissur", "kollam", "kannur"], "ml"),
    **_each(["mysuru", "mysore", "mangaluru", "mangalore", "hubballi", "belagavi"], "kn"),
}
IN_SUBDIVISION_CODES = {
    "AP": "andhra pradesh",
    "TG": "telangana",
    "TS": "telangana",
    "TN": "tamil nadu",
    "KL": "kerala",
    "KA": "karnataka",
    "MH": "maharashtra",
    "DL": "delhi",
    "UP": "uttar pradesh",
    "RJ": "rajasthan",
    "GJ": "gujarat",
    "PB": "punjab",
    "HR": "haryana",
    "BR": "bihar",
    "MP": "madhya pradesh",
    "WB": "west bengal",
    "OR": "odisha",
    "OD": "odisha",
    "PY": "puducherry",
    "GA": "goa",
    "AS": "assam",
    "CH": "chandigarh",
    "JK": "jammu and kashmir",
    "UK": "uttarakhand",
    "UT": "uttarakhand",
    "HP": "himachal pradesh",
    "JH": "jharkhand",
    "CT": "chhattisgarh",
    "CG": "chhattisgarh",
    "LD": "lakshadweep",
}
INDIA_TIMEZONES = frozenset({"Asia/Kolkata", "Asia/Calcutta"})
GENRE_MAP = {
    28: "Action",
    12: "Adventure",
    16: "Animation",
    35: "Comedy",
    80: "Crime",
    99: "Documentary",
    18: "Drama",
    10751: "Family",
    14: "Fantasy",
    36: "History",
    27: "Horror",
    10402: "Music",
    9648: "Mystery",
    10749: "Romance",
    878: "Science Fiction",
    10770: "TV Movie",
    53: "Thriller",
    10752: "War",
    37: "Western",
    10759: "Action & Adventure",
    10762: "Kids",
    10763: "News",
    10764: "Reality",
    10765: "Sci-Fi & Fantasy",
    10766: "Soap",
    10767: "Talk",
    10768: "War & Politics",
}
GENRE_SLUG_TO_IDS = {
    "action": [28, 10759],
    "adventure": [12, 10759],
    "animation": [16],
    "comedy": [35],
    "crime": [80],
    "documentary": [99],
    "drama": [18],
    "family": [10751],
    "fantasy": [14, 10765],
    "history": [36],
    "horror": [27],
    "music": [10402],
    "mystery": [9648],
    "romance": [10749],
    "science_fiction": [878, 10765],
    "thriller": [53],
    "war": [10752, 10768],
    "western": [37],
}
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p"
TMDB_API_BASE_URL = "https://api.themoviedb.org/3"
YOUTUBE_API_BASE_URL = "https://www.googleapis.com/youtube/v3"

NEW_RELEASE_WINDOW_DAYS, KNOWN_FOR_LIMIT, HERO_LIMIT, SECTION_LIMIT = 30, 10, 5, 12
TRENDING_LOCAL_MAX_ITEMS, TRENDING_INDIAN_DB_LIMIT, TRENDING_LOCAL_DB_LIMIT = 20, 30, 40
TRENDING_MIN_RATING, TRENDING_INDIAN_MIN_RATING = 5.5, 5.0
CRITICS_MIN_RATING, CRITICS_MIN_VOTES, CRITICS_MAX_CARDS, CRITICS_DB_LIMIT = 7.5, 200, 20, 60
NEW_RELEASES_MAX_CARDS, NEW_RELEASES_DB_LIMIT, NEW_RELEASES_API_LIMIT_PER_TYPE = 20, 40, 10
UPCOMING_DAYS_AHEAD, UPCOMING_MIN_DB_ITEMS, UPCOMING_MAX_CARDS = 180, 12, 20
THIS_WEEK_WINDOW_DAYS, THIS_WEEK_UPCOMING_WINDOW_DAYS, THIS_WEEK_MAX_PER_GROUP = 7, 7, 20
HIDDEN_GEMS_MIN_RATING, HIDDEN_GEMS_MIN_VOTE_COUNT, HIDDEN_GEMS_MAX_VOTE_COUNT = 7.0, 100, 5000
HIDDEN_GEMS_MAX_POPULARITY, HIDDEN_GEMS_MAX_RESULTS = 60.0, 20
HIDDEN_GEMS_FALLBACK_MIN_VOTE_COUNT, HIDDEN_GEMS_CANDIDATE_LIMIT, HIDDEN_GEMS_FALLBACK_LIMIT = 50, 80, 40
REGIONAL_PAGE_SIZE = 20
DECIDE_LIMIT, FALLBACK_LIMIT, CANDIDATE_POOL_LIMIT, DECIDE_CACHE_TTL = 3, 2, 80, 300
SIMILAR_LIMIT, SIMILAR_CANDIDATE_LIMIT, SIMILAR_FALLBACK_LIMIT = 12, 40, 20
FEELS_LIKE_DEFAULT_LIMIT, FEELS_LIKE_CANDIDATE_LIMIT = 20, 50
MAX_ANON_INTERACTIONS, MIN_CAST_FROM_DB, MAX_CAST_FETCHED = 100, 5, 20
MAX_BACKDROPS, MAX_POSTERS, MAX_STILLS = 20, 15, 10
MAX_BACKOFF_SECONDS = 8.0
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
MAX_CONFIDENCE, MIN_CONFIDENCE_COLD_START, MIN_VOTES_CONFIDENCE, POPULARITY_REFERENCE = 0.95, 0.30, 100, 5000.0
HERO_CANDIDATE_LIMIT, POPULAR_INDIA_DB_LIMIT = 20, 30
ANONYMOUS_RECS_TOP_N, PERSONALIZED_FETCH_LIMIT, FALLBACK_POOL_LIMIT = 24, 60, 40
TRENDING_SEARCHES_DB_LIMIT, ANONYMOUS_INTERACTIONS_DEFAULT_LIMIT = 200, 50
SCORE_WEIGHTS = {
    "popularity": 0.20,
    "freshness": 0.15,
    "rating": 0.20,
    "language": 0.20,
    "genre_affinity": 0.10,
    "content_type_affinity": 0.05,
    "trending": 0.10,
}

TTL = {
    "detail": 1800,
    "trending": 900,
    "releases": 2100,
    "search": 600,
    "feels": 1800,
    "genre": 3600,
    "regional": 3600,
    "critics": 3600,
    "upcoming": 3600,
    "similar": 1800,
    "home": 900,
    "person": 86400,
    "videos": 86400,
    "geo": 86400,
}
GENRE_NAMES = frozenset(GENRE_MAP.values())
MAX_PAGE = 100
