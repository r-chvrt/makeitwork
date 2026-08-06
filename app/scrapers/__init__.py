# -*- coding: utf-8 -*-
from .wttj import search_wttj
from .indeed import search_indeed
from .hellowork import search_hellowork

SCRAPERS = {
    "wttj": search_wttj,
    "indeed": search_indeed,
    "hellowork": search_hellowork,
}
