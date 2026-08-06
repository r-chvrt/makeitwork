# -*- coding: utf-8 -*-
"""Scraping des recherches suivies : à la demande (nouvelle recherche)
et en tâche de fond à intervalle régulier.

Variables d'environnement :
- SCRAPE_INTERVAL_MINUTES : fréquence de rafraîchissement (défaut 30)
- SCRAPE_LIMIT : offres max par site et par recherche (défaut 100)
"""
import asyncio
import logging
import os

from . import db
from .categorize import categorize, salary_to_annual
from .dedup import dedup_offers
from .models import JobOffer
from .relevance import apply_relevance
from .scrapers import SCRAPERS

log = logging.getLogger("makeitwork.refresh")

SCRAPE_INTERVAL_MINUTES = int(os.environ.get("SCRAPE_INTERVAL_MINUTES", "30"))
SCRAPE_LIMIT = int(os.environ.get("SCRAPE_LIMIT", "100"))
ACTIVE_DAYS = 7     # une recherche inutilisée depuis N jours n'est plus rafraîchie
PRUNE_DAYS = 30     # ... et est supprimée au bout de M jours


async def scrape(q: str, location: str, radius_km: int) -> tuple[list[JobOffer], dict]:
    """Scrape les 3 sites puis applique dédup, pertinence et enrichissement."""
    names = list(SCRAPERS)
    outcomes = await asyncio.gather(
        *(SCRAPERS[n](q, location, SCRAPE_LIMIT, radius_km) for n in names),
        return_exceptions=True,
    )
    results, errors = [], {}
    for name, outcome in zip(names, outcomes):
        if isinstance(outcome, BaseException):
            errors[name] = f"{type(outcome).__name__}: {outcome}"
        else:
            results.extend(outcome)

    results = dedup_offers(results)
    results = apply_relevance(results, q)
    for offer in results:
        offer.category = categorize(offer)
        offer.salary_annual = salary_to_annual(offer.salary)
    return results, errors


async def refresh_search(search: dict) -> dict:
    """Rafraîchit une recherche suivie et persiste le résultat. Retourne les erreurs."""
    offers, errors = await scrape(search["q"], search["location"], search["radius_km"])
    # ne pas écraser des données valides par un scrape totalement en échec
    if offers or not errors:
        db.replace_offers(search["id"], offers)
    db.mark_scraped(search["id"], errors)
    log.info("refresh «%s» @ «%s» : %d offres, erreurs=%s",
             search["q"] or "*", search["location"] or "France", len(offers), errors or "aucune")
    return errors


async def background_loop() -> None:
    """Boucle de fond : toutes les minutes, rafraîchit les recherches dont
    le dernier scrape date de plus de SCRAPE_INTERVAL_MINUTES."""
    log.info("planificateur démarré (intervalle %d min, %d offres/site)",
             SCRAPE_INTERVAL_MINUTES, SCRAPE_LIMIT)
    while True:
        try:
            db.prune_searches(PRUNE_DAYS)
            for search in db.searches_to_refresh(SCRAPE_INTERVAL_MINUTES, ACTIVE_DAYS):
                try:
                    await refresh_search(search)
                except Exception:
                    log.exception("échec du rafraîchissement de la recherche %s", search["id"])
                await asyncio.sleep(5)  # politesse entre deux recherches
        except Exception:
            log.exception("erreur dans la boucle de rafraîchissement")
        await asyncio.sleep(60)
