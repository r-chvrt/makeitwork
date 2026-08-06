# -*- coding: utf-8 -*-
"""Scraper Hellowork — parsing HTML de la page de recherche + pages détail pour le résumé."""
import asyncio
import re
from datetime import date, timedelta

from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession

from ..models import JobOffer
from .base import clean_text

SEARCH_URL = "https://www.hellowork.com/fr-fr/emploi/recherche.html"
BASE = "https://www.hellowork.com"

CONTRACTS = {"CDI", "CDD", "Intérim", "Stage", "Alternance", "Freelance",
             "Indépendant", "Franchise", "Statutaire", "Saisonnier"}


def _parse_relative_date(text: str) -> str | None:
    """Convertit « il y a 7 jours », « hier »... en date ISO."""
    t = text.lower().strip()
    today = date.today()
    if "aujourd" in t or "heure" in t or "minute" in t or "instant" in t:
        return today.isoformat()
    if "hier" in t:
        return (today - timedelta(days=1)).isoformat()
    m = re.search(r"(\d+)\s*jour", t)
    if m:
        return (today - timedelta(days=int(m.group(1)))).isoformat()
    m = re.search(r"(\d+)\s*semaine", t)
    if m:
        return (today - timedelta(weeks=int(m.group(1)))).isoformat()
    m = re.search(r"(\d+)\s*mois", t)
    if m:
        return (today - timedelta(days=30 * int(m.group(1)))).isoformat()
    return None


def _parse_remote(text: str) -> str | None:
    t = text.lower()
    if "télétravail" not in t:
        return None
    if "complet" in t or "total" in t or "100" in t:
        return "total"
    if "partiel" in t:
        return "partiel"
    if "occasionnel" in t:
        return "occasionnel"
    return "partiel"


PAGE_SIZE = 30  # cartes par page de résultats
_summary_semaphore = asyncio.Semaphore(10)  # pages détail simultanées max


async def _fetch_summary(session: AsyncSession, url: str) -> str | None:
    """Récupère la description sur la page détail de l'offre."""
    try:
        async with _summary_semaphore:
            r = await session.get(url, timeout=15)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        paras = [p.get_text(" ", strip=True) for p in soup.select("section p")]
        text = " ".join(p for p in paras if len(p) > 40)
        return clean_text(text) if text else None
    except Exception:
        return None


async def _fetch_page(session: AsyncSession, params: dict, page: int) -> list:
    r = await session.get(SEARCH_URL, params={**params, "p": str(page)}, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    return soup.select('[data-id-storage-target="item"]')


async def search_hellowork(query: str, location: str = "", limit: int = 15,
                           radius_km: int = 30) -> list[JobOffer]:
    params = {"k": query}
    if location:
        params["l"] = location
        params["d"] = str(radius_km)  # rayon en km
    nb_pages = -(-limit // PAGE_SIZE)  # arrondi supérieur
    async with AsyncSession(impersonate="chrome") as session:
        pages = await asyncio.gather(
            *(_fetch_page(session, params, p) for p in range(1, nb_pages + 1)),
            return_exceptions=True,
        )
        cards, seen_ids = [], set()
        for page in pages:
            if isinstance(page, BaseException):
                continue  # une page en erreur n'empêche pas les autres
            for card in page:
                card_id = card.get("data-id-storage-item-id")
                if card_id and card_id in seen_ids:
                    continue
                seen_ids.add(card_id)
                cards.append(card)
        cards = cards[:limit]

        offers: list[JobOffer] = []
        for card in cards:
            link = card.select_one('a[data-cy="offerTitle"], a[href*="/emplois/"]')
            if link is None:
                continue
            parts = list(link.stripped_strings)
            title = parts[0] if parts else "Sans titre"
            company = parts[1] if len(parts) > 1 else None

            loc_el = card.select_one('[data-cy="localisationCard"]')
            contract_el = card.select_one('[data-cy="contractCard"]')

            # Les tags (data-cy="contractTag") portent salaire, télétravail, temps plein...
            tags = [el.get_text(" ", strip=True)
                    for el in card.select('[data-cy="contractTag"]')]
            card_text_lines = [s for s in card.stripped_strings]

            salary = next((t for t in tags + card_text_lines if "€" in t), None)
            remote_txt = next((t for t in tags + card_text_lines
                               if "télétravail" in t.lower()), None)
            date_txt = next((s for s in card_text_lines
                             if re.match(r"^(il y a|hier|aujourd)", s.lower())), None)

            offers.append(JobOffer(
                source="hellowork",
                title=title,
                company=company,
                location=loc_el.get_text(" ", strip=True) if loc_el else None,
                url=BASE + link["href"].split("?")[0],
                published_at=_parse_relative_date(date_txt) if date_txt else None,
                salary=salary,
                remote=_parse_remote(remote_txt) if remote_txt else None,
                contract=(contract_el.get_text(" ", strip=True)
                          if contract_el and contract_el.get_text(strip=True) in CONTRACTS
                          else None),
                summary=None,
            ))

        # Résumés : pages détail récupérées en parallèle
        summaries = await asyncio.gather(
            *(_fetch_summary(session, o.url) for o in offers))
        for offer, summary in zip(offers, summaries):
            offer.summary = summary

    return offers
