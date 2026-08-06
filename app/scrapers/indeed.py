# -*- coding: utf-8 -*-
"""Scraper Indeed France — via l'API GraphQL de l'application mobile Indeed.

Le site web fr.indeed.com est protégé par Cloudflare, mais l'API mobile
(apis.indeed.com) accepte les requêtes avec la clé publique embarquée dans l'app.
"""
import re
from datetime import datetime, timezone

from curl_cffi.requests import AsyncSession

from ..models import JobOffer
from .base import clean_text, format_salary

API_URL = "https://apis.indeed.com/graphql"
API_KEY = "161092c2017b5bbab13edb12461a62d5a833871e7cad6d9d475304573de67ac8"

HEADERS = {
    "Host": "apis.indeed.com",
    "content-type": "application/json",
    "indeed-api-key": API_KEY,
    "accept": "application/json",
    "indeed-locale": "fr-FR",
    "accept-language": "fr-FR,fr;q=0.9",
    "user-agent": ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_6_1 like Mac OS X) "
                   "AppleWebKit/605.1.15 (KHTML, like Gecko) Indeed App 193.1"),
    "indeed-app-info": "appv=193.1; appid=com.indeed.jobsearch; osv=16.6.1; os=ios; dtype=phone",
    "indeed-co": "FR",
}

QUERY_TEMPLATE = """
query JobSearch {{
  jobSearch(
    {what_arg}
    location: {{where: {where}, radius: {radius}, radiusUnit: KILOMETERS}}
    limit: {limit}
    sort: RELEVANCE
  ) {{
    results {{
      job {{
        key
        title
        datePublished
        location {{ formatted {{ long short }} }}
        compensation {{
          baseSalary {{ unitOfWork range {{ ... on Range {{ min max }} }} }}
          estimated {{ baseSalary {{ unitOfWork range {{ ... on Range {{ min max }} }} }} currencyCode }}
          currencyCode
        }}
        attributes {{ label }}
        employer {{ name }}
        description {{ html }}
      }}
    }}
  }}
}}
"""

CONTRACT_LABELS = {
    "CDI", "CDD", "Stage", "Alternance", "Apprentissage", "Intérim",
    "Freelance / Indépendant", "Temps plein", "Temps partiel", "Contrat pro",
}


def _gql_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _parse_remote(labels: list[str]) -> str | None:
    joined = " | ".join(labels).lower()
    if "télétravail hybride" in joined:
        return "partiel"
    if "télétravail" in joined:
        # ex: "Télétravail", "Télétravail à 100 %"
        return "total" if "100" in joined or joined.strip() == "télétravail" else "partiel"
    return None


async def search_indeed(query: str, location: str = "", limit: int = 15,
                        radius_km: int = 30) -> list[JobOffer]:
    gql = QUERY_TEMPLATE.format(
        what_arg=f"what: {_gql_str(query)}" if query.strip() else "",
        where=_gql_str(location or "France"),
        radius=radius_km,
        limit=limit,
    )
    async with AsyncSession(impersonate="safari_ios") as session:
        r = await session.post(API_URL, headers=HEADERS, json={"query": gql}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("errors"):
        raise RuntimeError(f"Erreur GraphQL Indeed : {data['errors'][0].get('message')}")

    offers = []
    for res in data["data"]["jobSearch"]["results"]:
        j = res["job"]
        labels = [a["label"] for a in (j.get("attributes") or []) if a.get("label")]

        comp = j.get("compensation") or {}
        salary = None
        base = comp.get("baseSalary") or {}
        rng = base.get("range") or {}
        if rng.get("min") or rng.get("max"):
            salary = format_salary(rng.get("min"), rng.get("max"),
                                   comp.get("currencyCode") or "EUR", base.get("unitOfWork"))
        elif comp.get("estimated"):
            est = comp["estimated"]
            ebase = est.get("baseSalary") or {}
            erng = ebase.get("range") or {}
            if erng.get("min") or erng.get("max"):
                salary = format_salary(erng.get("min"), erng.get("max"),
                                       est.get("currencyCode") or "EUR", ebase.get("unitOfWork"))
                salary += " (estimation Indeed)"

        published = None
        if j.get("datePublished"):
            published = datetime.fromtimestamp(
                j["datePublished"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")

        desc_html = ((j.get("description") or {}).get("html")) or ""
        summary = clean_text(re.sub(r"<[^>]+>", " ", desc_html)) or None

        contract = next((l for l in labels if l in CONTRACT_LABELS), None)

        offers.append(JobOffer(
            source="indeed",
            title=j.get("title") or "Sans titre",
            company=(j.get("employer") or {}).get("name"),
            location=((j.get("location") or {}).get("formatted") or {}).get("short"),
            url=f"https://fr.indeed.com/viewjob?jk={j['key']}",
            published_at=published,
            salary=salary,
            remote=_parse_remote(labels),
            contract=contract,
            summary=summary,
        ))
    return offers
