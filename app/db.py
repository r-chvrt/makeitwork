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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS searches (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                q               TEXT NOT NULL,
                location        TEXT NOT NULL,
                radius_km       INTEGER NOT NULL,
                created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                last_used_at    TEXT NOT NULL DEFAULT (datetime('now')),
                last_scraped_at TEXT,
                last_errors     TEXT NOT NULL DEFAULT '{}',
                UNIQUE (q, location, radius_km)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS offers (
                search_id     INTEGER NOT NULL,
                url           TEXT NOT NULL,
                source        TEXT NOT NULL,
                published_at  TEXT,
                relevance     INTEGER NOT NULL DEFAULT 0,
                offer         TEXT NOT NULL,   -- JobOffer sérialisé en JSON
                first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (search_id, url)
            )
        """)


# ---- Recherches suivies (scrapées en tâche de fond) -------------------------

def get_or_create_search(q: str, location: str, radius_km: int) -> dict:
    """Retourne la recherche suivie (créée si besoin) et marque son utilisation."""
    q, location = q.strip().lower(), location.strip().lower()
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT OR IGNORE INTO searches (q, location, radius_km) VALUES (?, ?, ?)",
            (q, location, radius_km),
        )
        conn.execute(
            "UPDATE searches SET last_used_at = datetime('now') "
            "WHERE q = ? AND location = ? AND radius_km = ?",
            (q, location, radius_km),
        )
        row = conn.execute(
            "SELECT * FROM searches WHERE q = ? AND location = ? AND radius_km = ?",
            (q, location, radius_km),
        ).fetchone()
    return dict(row)


def searches_to_refresh(interval_minutes: int, active_days: int = 7) -> list[dict]:
    """Recherches utilisées récemment dont le scrape date de plus de `interval_minutes`."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
            SELECT * FROM searches
            WHERE last_used_at >= datetime('now', ?)
              AND (last_scraped_at IS NULL
                   OR last_scraped_at <= datetime('now', ?))
            ORDER BY last_scraped_at IS NOT NULL, last_scraped_at
            """,
            (f"-{active_days} days", f"-{interval_minutes} minutes"),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_scraped(search_id: int, errors: dict) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE searches SET last_scraped_at = datetime('now'), last_errors = ? "
            "WHERE id = ?",
            (json.dumps(errors, ensure_ascii=False), search_id),
        )


def replace_offers(search_id: int, offers: list[JobOffer]) -> None:
    """Remplace les offres d'une recherche en préservant leur date de découverte."""
    with closing(_connect()) as conn, conn:
        existing = {
            r["url"]: r["first_seen_at"]
            for r in conn.execute(
                "SELECT url, first_seen_at FROM offers WHERE search_id = ?",
                (search_id,),
            ).fetchall()
        }
        conn.execute("DELETE FROM offers WHERE search_id = ?", (search_id,))
        conn.executemany(
            "INSERT OR REPLACE INTO offers "
            "(search_id, url, source, published_at, relevance, offer, first_seen_at) "
            "VALUES (?, ?, ?, ?, ?, ?, COALESCE(?, datetime('now')))",
            [
                (search_id, o.url, o.source, o.published_at, o.relevance,
                 json.dumps(o.model_dump(exclude={"pin_status"}), ensure_ascii=False),
                 existing.get(o.url))
                for o in offers
            ],
        )


def load_offers(search_id: int) -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT offer FROM offers WHERE search_id = ?", (search_id,),
        ).fetchall()
    return [json.loads(r["offer"]) for r in rows]


def prune_searches(unused_days: int = 30) -> None:
    """Supprime les recherches délaissées et leurs offres (les épinglés ont leur propre table)."""
    with closing(_connect()) as conn, conn:
        old = [r["id"] for r in conn.execute(
            "SELECT id FROM searches WHERE last_used_at < datetime('now', ?)",
            (f"-{unused_days} days",),
        ).fetchall()]
        for search_id in old:
            conn.execute("DELETE FROM offers WHERE search_id = ?", (search_id,))
            conn.execute("DELETE FROM searches WHERE id = ?", (search_id,))


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
