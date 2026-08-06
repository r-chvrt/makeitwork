# -*- coding: utf-8 -*-
"""API FastAPI : agrège les résultats des scrapers, gère les épinglés, sert l'interface web."""
import asyncio
import time
from pathlib import Path

from curl_cffi.requests import AsyncSession
from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .categorize import categorize, salary_to_annual
from .dedup import dedup_offers
from .models import PinRequest, SearchResponse
from .relevance import apply_relevance
from .scrapers import SCRAPERS

app = FastAPI(title="MakeItWork — agrégateur d'offres d'emploi")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

db.init_db()


def _user(request: Request) -> str:
    """Identité pour les épinglés : pseudo choisi dans l'interface (X-Pseudo),
    sinon identité SSO (Traefik forward-auth), sinon liste partagée."""
    pseudo = (request.headers.get("x-pseudo") or "").strip().lower()
    if pseudo:
        return pseudo[:40]
    return request.headers.get("x-forwarded-user") or "default"


@app.get("/api/search", response_model=SearchResponse)
async def search(
    request: Request,
    q: str = Query("", description="Métier / mots-clés (vide = toutes les offres de la zone)"),
    location: str = Query("", description="Zone géographique (ville, département...)"),
    sources: str = Query("wttj,indeed,hellowork", description="Sources séparées par des virgules"),
    limit: int = Query(15, ge=1, le=30, description="Nombre max d'offres par source"),
    radius_km: int = Query(30, ge=5, le=100, description="Rayon de recherche en km"),
):
    q = q.strip()
    if not q and not location.strip():
        return SearchResponse(results=[], errors={}, took_ms=0)

    wanted = [s.strip() for s in sources.split(",") if s.strip() in SCRAPERS]
    started = time.perf_counter()

    tasks = [SCRAPERS[name](q, location, limit, radius_km) for name in wanted]
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    results, errors = [], {}
    for name, outcome in zip(wanted, outcomes):
        if isinstance(outcome, BaseException):
            errors[name] = f"{type(outcome).__name__}: {outcome}"
        else:
            results.extend(outcome)

    # marquer les offres déjà épinglées par cet utilisateur (avant fusion,
    # pour qu'un doublon épinglé garde son statut sur la carte fusionnée)
    statuses = db.get_statuses(_user(request), [o.url for o in results])
    for offer in results:
        offer.pin_status = statuses.get(offer.url)

    # fusionner les offres publiées sur plusieurs sites
    results = dedup_offers(results)

    # écarter les offres sans rapport avec les mots-clés
    results = apply_relevance(results, q)

    # catégorie de métier et salaire annualisé (pour les filtres du front)
    for offer in results:
        offer.category = categorize(offer)
        offer.salary_annual = salary_to_annual(offer.salary)

    # tri par date décroissante, offres sans date à la fin
    results.sort(key=lambda o: o.published_at or "0000-00-00", reverse=True)

    return SearchResponse(
        results=results,
        errors=errors,
        took_ms=int((time.perf_counter() - started) * 1000),
    )


@app.get("/api/cities")
async def cities(q: str = Query(..., min_length=1)):
    """Autocomplétion de communes françaises : par nom (« cae » → Caen)
    ou par code postal (« 14000 » → Caen), via geo.api.gouv.fr."""
    q = q.strip()
    params = {"limit": "6", "fields": "nom,codesPostaux,codeDepartement", "boost": "population"}
    if q.isdigit():
        if len(q) != 5:
            return {"cities": []}
        params["codePostal"] = q
    else:
        params["nom"] = q
    async with AsyncSession() as session:
        r = await session.get("https://geo.api.gouv.fr/communes", params=params, timeout=10)
    r.raise_for_status()
    return {"cities": [
        {
            "nom": c["nom"],
            "cp": (c.get("codesPostaux") or [""])[0],
            "dep": c.get("codeDepartement", ""),
        }
        for c in r.json()
    ]}


@app.get("/api/pins")
async def get_pins(request: Request):
    return {"pins": db.list_pins(_user(request))}


@app.put("/api/pins")
async def put_pin(body: PinRequest, request: Request):
    db.upsert_pin(_user(request), body.offer, body.status)
    return {"ok": True}


@app.delete("/api/pins")
async def remove_pin(request: Request, url: str = Query(...)):
    db.delete_pin(_user(request), url)
    return {"ok": True}


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
