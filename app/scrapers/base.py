# -*- coding: utf-8 -*-
"""Utilitaires communs aux scrapers."""
import html
import re
from typing import Optional

from curl_cffi.requests import AsyncSession


def clean_text(html_or_text: str, max_len: int = 380) -> str:
    """Nettoie un texte (entités HTML, espaces multiples) et le tronque proprement."""
    text = re.sub(r"\s+", " ", html.unescape(html_or_text)).strip()
    if len(text) <= max_len:
        return text
    cut = text[:max_len]
    # couper au dernier espace pour ne pas trancher un mot
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut + "…"


def format_salary(minimum, maximum, currency: str = "EUR", period: Optional[str] = None) -> Optional[str]:
    """Formate une fourchette de salaire en texte lisible. Retourne None si rien n'est indiqué."""
    if not minimum and not maximum:
        return None
    symbol = {"EUR": "€", "USD": "$", "GBP": "£"}.get((currency or "EUR").upper(), currency or "€")
    per = {
        "yearly": "an", "year": "an", "YEAR": "an",
        "monthly": "mois", "month": "mois", "MONTH": "mois",
        "daily": "jour", "day": "jour", "DAY": "jour",
        "hourly": "heure", "hour": "heure", "HOUR": "heure",
    }.get(period or "", None)

    def fmt(n):
        return f"{int(n):,}".replace(",", " ")

    if minimum and maximum and minimum != maximum:
        txt = f"{fmt(minimum)} – {fmt(maximum)} {symbol}"
    else:
        txt = f"{fmt(minimum or maximum)} {symbol}"
    return f"{txt} / {per}" if per else txt


async def geocode_fr(session: AsyncSession, query: str) -> Optional[tuple[float, float, str]]:
    """Géocode une localité française via l'API Adresse (data.gouv.fr).

    Retourne (lat, lng, libellé) ou None.
    """
    r = await session.get(
        "https://api-adresse.data.gouv.fr/search/",
        params={"q": query, "limit": 1},
        timeout=10,
    )
    if r.status_code != 200:
        return None
    feats = r.json().get("features") or []
    if not feats:
        return None
    f = feats[0]
    lng, lat = f["geometry"]["coordinates"]
    label = f["properties"].get("label", query)
    return lat, lng, label
