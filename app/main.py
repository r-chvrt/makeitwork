# -*- coding: utf-8 -*-
"""API FastAPI : recherche dans les offres scrapées en tâche de fond,
gestion des épinglés, autocomplétion de villes, interface web.

Le scraping ne se fait plus à la volée : un planificateur (app/refresh.py)
rafraîchit les recherches suivies toutes les SCRAPE_INTERVAL_MINUTES.
Seule une recherche jamais vue déclenche un scrape immédiat.
"""
import asyncio
import json
import logging
import math
import time
from contextlib import asynccontextmanager
from pathlib import Path

from curl_cffi.requests import AsyncSession
from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db, refresh
from .models import JobOffer, PinRequest, SearchResponse
from .scrapers import SCRAPERS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

db.init_db()


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(refresh.background_loop())
    yield
    task.cancel()


app = FastAPI(title="MakeItWork — agrégateur d'offres d'emploi", lifespan=lifespan)


def _user(request: Request) -> str:
    """Identité pour les épinglés : pseudo choisi dans l'interface (X-Pseudo),
    sinon identité SSO (Traefik forward-auth), sinon liste partagée."""
    pseudo = (request.headers.get("x-pseudo") or "").strip().lower()
    if pseudo:
        return pseudo[:40]
    return request.headers.get("x-forwarded-user") or "default"


def _facets(offers: list[JobOffer]) -> dict[str, list[tuple[str, int]]]:
    def count(values):
        counts: dict[str, int] = {}
        for v in values:
            if v:
                counts[v] = counts.get(v, 0) + 1
        return sorted(counts.items(), key=lambda kv: -kv[1])

    return {
        "categories": count(o.category for o in offers),
        "contracts": count(o.contract for o in offers),
    }


@app.get("/api/search", response_model=SearchResponse)
async def search(
    request: Request,
    q: str = Query("", description="Métier / mots-clés (vide = toutes les offres de la zone)"),
    location: str = Query("", description="Zone géographique"),
    sources: str = Query("wttj,indeed,hellowork"),
    radius_km: int = Query(30, ge=5, le=100),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=5, le=50),
    sort: str = Query("date", pattern="^(date|relevance)$"),
    category: str = Query(""),
    contract: str = Query(""),
    salary_range: str = Query("", description="ex : 30-40 (k€/an)"),
    remote_only: bool = Query(False),
    salary_only: bool = Query(False),
):
    q = q.strip()
    if not q and not location.strip():
        return SearchResponse(results=[], total=0, page=1, pages=0,
                              facets={"categories": [], "contracts": []},
                              errors={}, took_ms=0)

    started = time.perf_counter()

    row = db.get_or_create_search(q, location, radius_km)
    errors = json.loads(row.get("last_errors") or "{}")
    if row["last_scraped_at"] is None:
        # recherche jamais scrapée : premier scrape en direct
        errors = await refresh.refresh_search(row)
        row = db.get_or_create_search(q, location, radius_km)

    offers = [JobOffer(**o) for o in db.load_offers(row["id"])]

    # filtre par site
    wanted = {s.strip() for s in sources.split(",") if s.strip() in SCRAPERS}
    offers = [o for o in offers if o.source in wanted]

    # facettes calculées avant les autres filtres (pour garder toutes les options visibles)
    facets = _facets(offers)

    if category:
        offers = [o for o in offers if o.category == category]
    if contract:
        offers = [o for o in offers if o.contract == contract]
    if remote_only:
        offers = [o for o in offers if o.remote and o.remote != "non"]
    if salary_only:
        offers = [o for o in offers if o.salary]
    if salary_range:
        try:
            lo, hi = (int(x) for x in salary_range.split("-", 1))
            offers = [o for o in offers if o.salary_annual is not None
                      and lo * 1000 <= o.salary_annual < hi * 1000]
        except ValueError:
            pass

    if sort == "relevance":
        offers.sort(key=lambda o: -o.relevance)
    else:
        offers.sort(key=lambda o: o.published_at or "0000-00-00", reverse=True)

    total = len(offers)
    pages = max(1, math.ceil(total / per_page)) if total else 0
    page = min(page, pages) if pages else 1
    page_offers = offers[(page - 1) * per_page: page * per_page]

    # statuts d'épinglage (page affichée uniquement)
    statuses = db.get_statuses(_user(request), [o.url for o in page_offers])
    for offer in page_offers:
        offer.pin_status = statuses.get(offer.url)

    return SearchResponse(
        results=page_offers,
        total=total,
        page=page,
        pages=pages,
        facets=facets,
        errors=errors,
        last_scraped_at=row.get("last_scraped_at"),
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
