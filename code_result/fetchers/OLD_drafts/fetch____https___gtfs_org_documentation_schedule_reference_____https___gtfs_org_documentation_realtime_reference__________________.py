# -*- coding: utf-8 -*-
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="规范：https://gtfs.org/documentation/schedule/reference/；实时：https://gtfs.org/documentation/realtime/reference/；数据需到各交通机构开放平台获取。",
    aliases=[],
    has_api=False,
    is_reviewed=False,
    auditor_notes="系统判定无API",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch____https___gtfs_org_documentation_schedule_reference_____https___gtfs_org_documentation_realtime_reference__________________(**kwargs):
    return {"error": "KNOWN_NO_API_PLATFORM", "reason": "系统判定无API"}
