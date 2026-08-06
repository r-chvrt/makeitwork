# -*- coding: utf-8 -*-
"""Déduplication des offres publiées sur plusieurs sites.

Deux offres sont considérées identiques si leurs titres normalisés sont très
proches ET que leurs entreprises correspondent (ou que l'une des deux est
inconnue, avec un seuil de titre plus strict). Le groupe est fusionné en une
seule carte : on garde l'offre la plus complète et on complète ses champs
manquants avec ceux des doublons ; les autres sites restent accessibles via
« Aussi sur … ».
"""
import re
import unicodedata
from difflib import SequenceMatcher

from .models import AltLink, JobOffer

# mentions de genre et décorations fréquentes dans les titres
_NOISE = re.compile(
    r"\(?\b(h/f/x|h/f|f/h|m/f|f/m|h-f|f-h|hf|fh)\b\)?|\(cdi\)|\(cdd\)", re.I)


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    # décomposer les accents puis les retirer
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = _NOISE.sub(" ", text.lower())
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _same_location(a: JobOffer, b: JobOffer) -> bool:
    """Vrai si les lieux sont compatibles (ou si l'un des deux est inconnu)."""
    la, lb = _normalize(a.location), _normalize(b.location)
    if not la or not lb:
        return True
    ta = {w for w in la.split() if not w.isdigit()}
    tb = {w for w in lb.split() if not w.isdigit()}
    return bool(ta & tb)


def _same_offer(a: JobOffer, b: JobOffer) -> bool:
    if not _same_location(a, b):
        return False
    ta, tb = _normalize(a.title), _normalize(b.title)
    if not ta or not tb:
        return False
    ca, cb = _normalize(a.company), _normalize(b.company)

    if ca and cb:
        company_match = ca == cb or ca in cb or cb in ca or _ratio(ca, cb) >= 0.85
        return company_match and (ta == tb or _ratio(ta, tb) >= 0.85)
    # entreprise inconnue d'un côté : on exige un titre quasi identique
    return ta == tb or _ratio(ta, tb) >= 0.93


def _completeness(o: JobOffer) -> int:
    """Score de richesse d'une offre, pour choisir laquelle garder en principal."""
    return sum((
        o.salary is not None,
        o.remote is not None,
        o.summary is not None,
        o.published_at is not None,
        o.contract is not None,
        o.logo is not None,
        o.company is not None,
    ))


def _merge(group: list[JobOffer]) -> JobOffer:
    group = sorted(group, key=_completeness, reverse=True)
    primary = group[0]
    for dup in group[1:]:
        # compléter les infos manquantes du principal avec celles des doublons
        for field in ("salary", "remote", "summary", "contract",
                      "published_at", "logo", "company", "location"):
            if getattr(primary, field) is None and getattr(dup, field) is not None:
                setattr(primary, field, getattr(dup, field))
        # si le doublon est épinglé mais pas le principal, garder le statut visible
        if primary.pin_status is None and dup.pin_status is not None:
            primary.pin_status = dup.pin_status
        primary.also_on.append(AltLink(source=dup.source, url=dup.url))
    return primary


def dedup_offers(offers: list[JobOffer]) -> list[JobOffer]:
    groups: list[list[JobOffer]] = []
    for offer in offers:
        for group in groups:
            if any(_same_offer(offer, member) for member in group):
                group.append(offer)
                break
        else:
            groups.append([offer])
    return [_merge(g) for g in groups]
