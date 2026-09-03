# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for MobilityDatabase
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="MobilityDatabase",
    aliases=[],
    has_api=True,
    is_reviewed=False,
    auditor_notes="AI 初始判定",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_mobilitydatabase(self, **kwargs):
    """自动生成的抓取方法: MobilityDatabase"""
    url = "https://api.mobilitydatabase.org/v1/feeds/{feed_id}"
    params = kwargs.get("extracted_api_params") or {}
    val_feed_id = params.get("feed_id") or kwargs.get("dataset_shortname") or kwargs.get("official_website_id") or kwargs.get("feed_id")
    if not val_feed_id:
        val_feed_id = kwargs.get("doi", "").split("/")[-1] if kwargs.get("doi") else ""
    if not val_feed_id:
        raise ValueError("Missing required parameter: feed_id")
    url = url.replace("{feed_id}", str(val_feed_id))
    try:
        response = self._get_with_retry(url, self.headers)
        return {"source": "MobilityDatabase-AutoGen", "data": response.json()}
    except Exception as e:
        return {"error": str(e)}
