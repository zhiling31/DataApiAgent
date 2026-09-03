# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for Geochron
from code_result.fetcher_decorator import register_api

import re
@register_api(
    publisher="Geochron",
    aliases=[],
    has_api=False,
    is_reviewed=True,
    auditor_notes="KML 接口仅返回样本点坐标列表，缺乏数据集级宏观描述，无可用 RESTful API",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_geochron(self, **kwargs):
    return {"error": "KNOWN_NO_API_PLATFORM", "reason": "Geochron 的 KML 接口仅返回样本点坐标列表，缺乏数据集级宏观描述，无可用 RESTful API"}
