# -*- coding: utf-8 -*-
"""Scraper Welcome To The Jungle — via leur API de recherche Algolia (celle du site)."""
from curl_cffi.requests import AsyncSession

from ..models import JobOffer
from .base import format_salary, geocode_fr

APP_ID = "CSEKHVMS53"
API_KEY = "4bd8f6215d0cc52b26430765769e65a0"  # clé publique de recherche, visible dans /api/env du site
INDEX = "wttj_jobs_production_fr"
BASE_URL = f"https://{APP_ID.lower()}-dsn.algolia.net"

HEADERS = {
    "x-algolia-application-id": APP_ID,
    "x-algolia-api-key": API_KEY,
    "content-type": "application/json",
    "Referer": "https://www.welcometothejungle.com/",
    "Origin": "https://www.welcometothejungle.com",
}

REMOTE_MAP = {
    "fulltime": "total",
    "full": "total",
    "partial": "partiel",
    "punctual": "occasionnel",
    "no": "non",
    "none": "non",
}

CONTRACT_MAP = {
    "full_time": "CDI",
    "temporary": "CDD",
    "internship": "Stage",
    "apprenticeship": "Alternance",
    "freelance": "Freelance",
    "vie": "VIE",
    "part_time": "Temps partiel",
    "other": None,
}

FIELDS = [
    "name", "slug", "summary", "remote", "has_remote", "contract_type",
    "salary_minimum", "salary_maximum", "salary_period", "salary_currency",
    "published_at", "offices", "organization",
]


async def search_wttj(query: str, location: str = "", limit: int = 15,
                      radius_km: int = 30) -> list[JobOffer]:
    async with AsyncSession(impersonate="chrome") as session:
        body: dict = {
            "query": query,
            "hitsPerPage": limit,
            "attributesToRetrieve": FIELDS,
        }
        if location:
            geo = await geocode_fr(session, location)
            if geo:
                lat, lng, _ = geo
                body["aroundLatLng"] = f"{lat},{lng}"
                body["aroundRadius"] = radius_km * 1000

        r = await session.post(
            f"{BASE_URL}/1/indexes/{INDEX}/query",
            headers=HEADERS, json=body, timeout=20,
        )
        r.raise_for_status()
        hits = r.json().get("hits", [])

    offers = []
    for h in hits:
        org = h.get("organization") or {}
        offices = h.get("offices") or []
        city = ", ".join(dict.fromkeys(o.get("city") for o in offices if o.get("city")))
        published = (h.get("published_at") or "")[:10] or None
        logo = ((org.get("logo") or {}).get("thumb") or {}).get("url") or \
               ((org.get("logo") or {}).get("url"))

        contract_raw = h.get("contract_type")
        offers.append(JobOffer(
            source="wttj",
            title=h.get("name") or "Sans titre",
            company=org.get("name"),
            location=city or None,
            url=f"https://www.welcometothejungle.com/fr/companies/{org.get('slug')}/jobs/{h.get('slug')}",
            published_at=published,
            salary=format_salary(
                h.get("salary_minimum"), h.get("salary_maximum"),
                h.get("salary_currency") or "EUR", h.get("salary_period"),
            ),
            remote=REMOTE_MAP.get(h.get("remote"), None),
            contract=CONTRACT_MAP.get(contract_raw, contract_raw),
            summary=h.get("summary") or None,
            logo=logo,
        ))
    return offers
