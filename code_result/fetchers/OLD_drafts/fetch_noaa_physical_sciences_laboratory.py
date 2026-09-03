# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for NOAA Physical Sciences Laboratory
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="NOAA Physical Sciences Laboratory",
    aliases=[],
    has_api=True,
    is_reviewed=False,
    auditor_notes="AI 初始判定",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_noaa_physical_sciences_laboratory(self, **kwargs):
    """自动生成的抓取方法: NOAA Physical Sciences Laboratory"""
    url = "https://psl.noaa.gov/thredds/catalog/Datasets/{collection_name}/catalog.xml"
    params = kwargs.get("extracted_api_params") or {}
    val_collection_name = params.get("collection_name") or kwargs.get("dataset_shortname") or kwargs.get("official_website_id") or kwargs.get("collection_name")
    if not val_collection_name:
        val_collection_name = kwargs.get("doi", "").split("/")[-1] if kwargs.get("doi") else ""
    if not val_collection_name:
        raise ValueError("Missing required parameter: collection_name")
    url = url.replace("{collection_name}", str(val_collection_name))
    try:
        response = self._get_with_retry(url, self.headers)
        return {"source": "NOAA Physical Sciences Laboratory-AutoGen", "data": response.json()}
    except Exception as e:
        return {"error": str(e)}
