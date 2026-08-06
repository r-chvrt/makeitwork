# -*- coding: utf-8 -*-
"""Enrichissement des offres : catégorie de métier et salaire annualisé.

Seul WTTJ fournit une catégorie ; pour avoir un filtre homogène sur les trois
sites, on classe toutes les offres avec le même classifieur par mots-clés du
titre (préfixes avec frontière de mot, sur texte normalisé sans accents).
"""
import re

from .dedup import _normalize
from .models import JobOffer

# (catégorie, préfixes de mots-clés cherchés dans le titre)
_CATEGORIES: list[tuple[str, list[str]]] = [
    ("Informatique / Tech", [
        "developpeu", "developpement", "devops", "sre", "data", "informatiqu",
        "logiciel", "software", "sysadmin", "systeme", "reseau", "cyber",
        "cloud", "fullstack", "full stack", "frontend", "front end", "backend",
        "back end", "python", "java", "php", " net ", "dotnet", "web",
        "ingenieur etude", "architecte si", "urbaniste si", "dba", "big data",
        "intelligence artificielle", " ia ", "machine learning", "devsecops",
        "testeur", "qa ", "scrum", "product owner", "product manager", "cto",
        "support technique", "helpdesk", "technicien informatique", "integrateur",
    ]),
    ("Commercial / Vente", [
        "commercial", "vente", "vendeu", "business developer", "biz dev",
        "account manager", "account executive", "conseiller client",
        "teleconseiller", "telemarketing", "sales", "chasseur d affaires",
        "charge d affaires", "responsable de magasin", "caissier", "caisse",
    ]),
    ("Administratif / RH", [
        "administrati", "assistant", "secretaire", "office manager",
        "ressources humaines", " rh", "recruteu", "paie", "gestionnaire",
        "accueil", "standardiste",
    ]),
    ("Finance / Comptabilité", [
        "comptab", "finance", "financier", "audit", "controleur de gestion",
        "tresorerie", "fiscalist", "credit", "risque", "actuair", "analyste m a",
    ]),
    ("Marketing / Communication", [
        "marketing", "communication", "community", "seo", "sea ", "contenu",
        "content", "redacteur", "brand", "growth", "acquisition", "crm",
        "graphiste", "designer", "ux", "ui ", "motion", "webdesign",
    ]),
    ("Santé / Social", [
        "infirmier", "aide soignant", "medecin", "sante", "pharmacien",
        "auxiliaire", "educateur", "psychologue", "kinesitherapeute",
        "dentaire", "veterinaire", "ambulancier", "social",
    ]),
    ("BTP / Industrie", [
        "chantier", "btp", "macon", "electricien", "plombier", "soudeu",
        "usine", "production", "maintenance", "mecanicien", "usinage",
        "conducteur de travaux", "ouvrier", "menuisier", "peintre", "couvreur",
        "chaudronnier", "fraiseur", "cariste atelier", "agent de fabrication",
        "qualite industrielle", "methodes", "genie civil", "geometre",
    ]),
    ("Logistique / Transport", [
        "logistique", "cariste", "chauffeur", "livreur",
        "preparateur de commande", "magasinier", "transport", "supply chain",
        "approvisionne", "conducteur routier", "manutention",
    ]),
    ("Hôtellerie / Restauration", [
        "cuisinier", "serveu", "restauration", "hotel", "barman", "commis",
        "chef de partie", "patissier", "boulanger", "receptionniste", "traiteur",
    ]),
    ("Juridique", ["juriste", "avocat", "juridique", "judiciaire", "notaire",
                   "notarial", "contentieux", "mandataire", "huissier", "greffier"]),
    ("Éducation / Formation", [
        "professeur", "enseignant", "formateur", "formation", "pedagog",
        "moniteur", "animateur",
    ]),
]

_COMPILED = [
    (name, [re.compile(r"\b" + re.escape(kw.strip())) for kw in kws])
    for name, kws in _CATEGORIES
]

DEFAULT_CATEGORY = "Autre"


def categorize(offer: JobOffer) -> str:
    title = " " + _normalize(offer.title) + " "
    for name, patterns in _COMPILED:
        if any(p.search(title) for p in patterns):
            return name
    return DEFAULT_CATEGORY


# ---- Salaire annualisé ------------------------------------------------------

_NUM = re.compile(r"\d+(?:[\s  ]\d{3})*(?:[.,]\d+)?")
_PERIOD_FACTOR = [
    (("an", "annee", "year", "annuel"), 1),
    (("mois", "month", "mensuel"), 12),
    (("jour", "day", "jj"), 218),      # ~218 jours travaillés / an
    (("heure", "hour", "h"), 1607),    # base 35 h
]


def salary_to_annual(salary_text: str | None) -> int | None:
    """« 2 500 – 3 000 € / mois » → 30000. None si pas exploitable."""
    if not salary_text:
        return None
    nums = []
    for m in _NUM.finditer(salary_text):
        raw = re.sub(r"[\s  ]", "", m.group()).replace(",", ".")
        try:
            nums.append(float(raw))
        except ValueError:
            continue
    nums = [n for n in nums if n > 0]
    if not nums:
        return None
    value = min(nums)
    text_norm = _normalize(salary_text)
    factor = None
    for keywords, f in _PERIOD_FACTOR:
        if any(re.search(r"\b" + k + r"\b", text_norm) for k in keywords):
            factor = f
            break
    if factor is None:
        # pas de période : on devine selon l'ordre de grandeur
        factor = 1 if value >= 8000 else (12 if value >= 800 else 1607)
    annual = value * factor
    return int(annual) if annual >= 5000 else None
