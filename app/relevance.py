# -*- coding: utf-8 -*-
"""Scoring de pertinence : écarte les offres sans rapport avec les mots-clés.

Les sites renvoient parfois des offres hors-sujet quand ils manquent de vrais
résultats (ex : « administratif » → « Ingénieur Réseau »). On note chaque offre
selon la présence des mots-clés dans le titre (fort), l'entreprise (moyen) ou
le résumé (faible), et on écarte celles sous le seuil.
"""
from .dedup import _normalize
from .models import JobOffer

_STOPWORDS = {
    "de", "la", "le", "les", "des", "du", "un", "une", "et", "en", "d", "l",
    "a", "au", "aux", "pour", "avec", "sur", "chez", "dans", "ou", "the", "of",
}

_PREFIX_LEN = 6  # « administratif » ~ « administrative », « réseau » ~ « réseaux »


def _tokens(text: str | None) -> list[str]:
    return [t for t in _normalize(text or "").split()
            if len(t) >= 2 and t not in _STOPWORDS]


def _match(a: str, b: str) -> bool:
    if a == b:
        return True
    return (len(a) >= _PREFIX_LEN and len(b) >= _PREFIX_LEN
            and a[:_PREFIX_LEN] == b[:_PREFIX_LEN])


def _score(offer: JobOffer, query_tokens: list[str]) -> int:
    title = _tokens(offer.title)
    company = _tokens(offer.company)
    summary = _tokens(offer.summary)
    score = 0
    for qt in query_tokens:
        if any(_match(qt, t) for t in title):
            score += 3
        elif any(_match(qt, t) for t in company):
            score += 2
        elif any(_match(qt, t) for t in summary):
            score += 1
    return score


def apply_relevance(offers: list[JobOffer], query: str) -> list[JobOffer]:
    """Note chaque offre et écarte les hors-sujet.

    Seuil : 2 (au moins un mot-clé dans le titre ou l'entreprise). Si le seuil
    vide tout, on assouplit à 1 puis on abandonne le filtre — mieux vaut des
    résultats moyens que rien.
    """
    query_tokens = _tokens(query)
    if not query_tokens:
        return offers
    for offer in offers:
        offer.relevance = _score(offer, query_tokens)
    for threshold in (2, 1):
        kept = [o for o in offers if o.relevance >= threshold]
        if kept:
            return kept
    return offers
