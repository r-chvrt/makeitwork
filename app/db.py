# -*- coding: utf-8 -*-
"""Persistance des offres épinglées — SQLite côté serveur.

Pas de gestion de compte : l'utilisateur vient de l'en-tête X-Forwarded-User
injecté par le SSO (Traefik forward-auth). Sans en-tête, tout va dans "default".
"""
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .models import JobOffer

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "makeitwork.db"

STATUSES = ("a_postuler", "postule", "entretien")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pins (
                user       TEXT NOT NULL,
                url        TEXT NOT NULL,
                status     TEXT NOT NULL,
                offer      TEXT NOT NULL,   -- instantané JSON de l'offre
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (user, url)
            )
        """)


def list_pins(user: str) -> list[dict]:
    """Toutes les offres épinglées de l'utilisateur, la plus récente d'abord."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT url, status, offer, updated_at FROM pins "
            "WHERE user = ? ORDER BY updated_at DESC", (user,),
        ).fetchall()
    pins = []
    for r in rows:
        offer = json.loads(r["offer"])
        offer["pin_status"] = r["status"]
        offer["pinned_at"] = r["updated_at"]
        pins.append(offer)
    return pins


def get_statuses(user: str, urls: list[str]) -> dict[str, str]:
    """Statut d'épinglage pour une liste d'URLs (pour enrichir les résultats de recherche)."""
    if not urls:
        return {}
    placeholders = ",".join("?" * len(urls))
    with closing(_connect()) as conn:
        rows = conn.execute(
            f"SELECT url, status FROM pins WHERE user = ? AND url IN ({placeholders})",
            (user, *urls),
        ).fetchall()
    return {r["url"]: r["status"] for r in rows}


def upsert_pin(user: str, offer: JobOffer, status: str) -> None:
    data = offer.model_dump(exclude={"pin_status"})
    with closing(_connect()) as conn, conn:
        conn.execute(
            """
            INSERT INTO pins (user, url, status, offer, updated_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT (user, url) DO UPDATE SET
                status = excluded.status,
                offer = excluded.offer,
                updated_at = excluded.updated_at
            """,
            (user, offer.url, status, json.dumps(data, ensure_ascii=False)),
        )


def delete_pin(user: str, url: str) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM pins WHERE user = ? AND url = ?", (user, url))
