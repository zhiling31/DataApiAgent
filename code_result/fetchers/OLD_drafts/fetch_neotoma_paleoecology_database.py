# -*- coding: utf-8 -*-
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="Neotoma Paleoecology Database",
    aliases=[],
    has_api=False,
    is_reviewed=False,
    auditor_notes="系统判定无API",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_neotoma_paleoecology_database(**kwargs):
    return {"error": "KNOWN_NO_API_PLATFORM", "reason": "系统判定无API"}
