# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for human-settlement.emergency.copernicus.eu
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="human-settlement.emergency.copernicus.eu",
    aliases=[],
    has_api=True,
    is_reviewed=False,
    auditor_notes="AI 初始判定",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_human_settlement_emergency_copernicus_eu(self, **kwargs):
    """自动生成的抓取方法: human-settlement.emergency.copernicus.eu"""
    url = "https://data.jrc.ec.europa.eu/api/3/action/package_show?id={id}"
    params = kwargs.get("extracted_api_params") or {}
    val_id = params.get("id") or kwargs.get("dataset_shortname") or kwargs.get("official_website_id") or kwargs.get("id")
    if not val_id:
        val_id = kwargs.get("doi", "").split("/")[-1] if kwargs.get("doi") else ""
    if not val_id:
        raise ValueError("Missing required parameter: id")
    url = url.replace("{id}", str(val_id))
    try:
        response = self._get_with_retry(url, self.headers)
        return {"source": "human-settlement.emergency.copernicus.eu-AutoGen", "data": response.json()}
    except Exception as e:
        return {"error": str(e)}
