# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for WorldPop
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="WorldPop",
    aliases=[],
    has_api=True,
    is_reviewed=False,
    auditor_notes="AI 初始判定",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_worldpop(self, **kwargs):
    """自动生成的抓取方法: WorldPop"""
    url = "https://api.worldpop.org/v1/data"
    params = kwargs.get("extracted_api_params") or {}
    try:
        response = self._get_with_retry(url, self.headers)
        return {"source": "WorldPop-AutoGen", "data": response.json()}
    except Exception as e:
        return {"error": str(e)}
