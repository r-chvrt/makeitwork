# -*- coding: utf-8 -*-
"""Modèle unifié d'une offre d'emploi, quelle que soit la source."""
from typing import Literal, Optional
from pydantic import BaseModel

PinStatus = Literal["a_postuler", "postule", "entretien"]


class AltLink(BaseModel):
    """Lien vers la même offre sur un autre site."""
    source: str
    url: str


class JobOffer(BaseModel):
    source: str                       # wttj | indeed | hellowork
    title: str
    company: Optional[str] = None
    location: Optional[str] = None
    url: str
    published_at: Optional[str] = None   # date ISO (YYYY-MM-DD)
    salary: Optional[str] = None         # texte formaté, None = non indiqué
    remote: Optional[str] = None         # "total" | "partiel" | "occasionnel" | "non" | None (non précisé)
    contract: Optional[str] = None       # CDI, CDD, Stage...
    summary: Optional[str] = None
    logo: Optional[str] = None
    pin_status: Optional[PinStatus] = None   # rempli côté serveur selon les épinglés
    also_on: list[AltLink] = []              # même offre trouvée sur d'autres sites
    relevance: int = 0                       # score de pertinence vs mots-clés
    category: Optional[str] = None           # catégorie de métier (classifieur)
    salary_annual: Optional[int] = None      # salaire mini annualisé en €, pour les filtres


class PinRequest(BaseModel):
    status: PinStatus
    offer: JobOffer


class SearchResponse(BaseModel):
    results: list[JobOffer]              # la page demandée uniquement
    total: int                           # nb d'offres après filtres
    page: int
    pages: int
    facets: dict[str, list[tuple[str, int]]]  # catégories / contrats disponibles (avec compteurs)
    errors: dict[str, str]               # source -> message d'erreur (dernier scrape)
    last_scraped_at: Optional[str] = None  # UTC « YYYY-MM-DD HH:MM:SS »
    took_ms: int
