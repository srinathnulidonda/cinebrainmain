# app/core/context.py

from dataclasses import dataclass, replace

from app.core.constants import FALLBACK_LANGS
from app.utils import INDIAN_LANGS_SET, ensure_english, merge_langs, normalize_langs, resolve_primary_langs

SUPPORTED = frozenset(FALLBACK_LANGS)


@dataclass(frozen=True, slots=True)
class UserContext:
    session_id: str
    country: str
    region: str
    city: str
    languages: tuple[str, ...]
    language_source: str
    timezone: str | None = None

    @property
    def lang_list(self) -> list[str]:
        return list(self.languages)

    @property
    def lang_key(self) -> str:
        return ",".join(self.languages)

    @property
    def indian_languages(self) -> list[str]:
        return [lang for lang in self.languages if lang in INDIAN_LANGS_SET]

    @property
    def region_label(self) -> str | None:
        return (self.city or self.region).title() or self.country or None

    @property
    def geo_scope(self) -> str:
        return f"{self.country or 'global'}:{self.city or self.region or 'all'}"

    def with_behavior(self, learned: list[str], interactions: int, threshold: int = 5) -> "UserContext":
        learned = normalize_langs(learned, 3)
        if self.language_source == "explicit" or interactions < threshold or not learned:
            return self
        return replace(self, languages=tuple(merge_langs(learned, list(self.languages))), language_source="behavior")


def resolve_languages(
    *, explicit: list[str] | None, accept: list[str] | None, geo_langs: list[str] | None, country: str
) -> tuple[list[str], str]:
    if chosen := normalize_langs(explicit):
        return ensure_english(chosen), "explicit"
    preferred = [lang for lang in normalize_langs(accept) if lang in SUPPORTED and lang != "en"]
    merged = merge_langs(preferred, resolve_primary_langs(country, list(geo_langs or [])))
    return merged, "accept_language" if preferred else ("geo" if country else "default")
