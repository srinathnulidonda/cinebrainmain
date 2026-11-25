# app/services/geo.py

import ipaddress
import logging
from collections.abc import Mapping
from urllib.parse import unquote

from app.core.constants import IN_SUBDIVISION_CODES, PLACE_LANGUAGES, REGION_LANGUAGE_MAP, TTL
from app.core.errors import AppError
from app.infra.cache import Cache, LocalTTLCache
from app.infra.http import ResilientClient

logger = logging.getLogger("app.geo")
_COUNTRY = ("CF-IPCountry", "X-Vercel-IP-Country", "CloudFront-Viewer-Country", "X-Country-Code")
_REGION = ("X-Vercel-IP-Country-Region", "CloudFront-Viewer-Country-Region", "CF-Region-Code", "CF-Region")
_CITY = ("X-Vercel-IP-City", "CF-IPCity", "CloudFront-Viewer-City")
_MISS = {"_miss": True}


def _header(headers: Mapping[str, str], names: tuple[str, ...]) -> str:
    return next((v.strip() for n in names if (v := headers.get(n)) and v.strip()), "")


def compose(country: str, region: str | None, city: str | None) -> dict:
    region = (region or "").strip()
    region = IN_SUBDIVISION_CODES.get(region.upper(), region.lower()) if country == "IN" else region.lower()
    city = (city or "").strip().lower()
    langs = list(REGION_LANGUAGE_MAP.get(country, ["en"]))
    if country == "IN":
        local = next((PLACE_LANGUAGES[k] for k in (city, region) if k in PLACE_LANGUAGES), [])
        langs = list(dict.fromkeys(local + langs))
    if "en" not in langs:
        langs.append("en")
    return {"country": country, "region": region, "city": city, "languages": langs[:6]}


class GeoService:
    def __init__(self, http: ResilientClient | None, cache: Cache, local: LocalTTLCache, trust_headers: bool):
        self.http = http
        self.cache = cache
        self.local = local
        self.trust_headers = trust_headers

    def from_headers(self, headers: Mapping[str, str]) -> dict:
        if not self.trust_headers:
            return {}
        country = _header(headers, _COUNTRY).upper()
        if len(country) != 2 or not country.isalpha() or country in {"XX", "T1", "ZZ"}:
            return {}
        return compose(country, _header(headers, _REGION), unquote(_header(headers, _CITY)))

    async def lookup(self, ip: str | None) -> dict:
        try:
            addr = ipaddress.ip_address(ip or "")
        except ValueError:
            return {}
        if not addr.is_global or self.http is None:
            return {}
        key = f"geo:{addr}"
        cached = self.local.get(key)
        if cached is None:
            cached = await self.cache.get_json(key)
        if cached is not None:
            self.local.set(key, cached, 3600)
            return {} if cached.get("_miss") else cached
        try:
            data = await self.http.get_json(f"/{addr}", {"fields": "status,countryCode,region,regionName,city"})
        except AppError:
            self.local.set(key, _MISS, 300)
            return {}
        if data.get("status") == "success" and data.get("countryCode"):
            result = compose(
                data["countryCode"].upper(), data.get("regionName") or data.get("region"), data.get("city")
            )
            self.local.set(key, result, 3600)
            await self.cache.set_json(key, result, TTL["geo"])
            return result
        self.local.set(key, _MISS, 300)
        await self.cache.set_json(key, _MISS, 300)
        return {}

    async def locate(self, headers: Mapping[str, str], ip: str | None) -> dict:
        return self.from_headers(headers) or await self.lookup(ip)
