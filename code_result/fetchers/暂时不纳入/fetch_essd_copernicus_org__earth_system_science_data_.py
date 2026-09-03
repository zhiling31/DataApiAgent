# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for essd.copernicus.org (Earth System Science Data)
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="essd.copernicus.org (Earth System Science Data)",
    aliases=[],
    has_api=True,
    is_reviewed=False,
    auditor_notes="AI 初始判定",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_essd_copernicus_org__earth_system_science_data_(self, **kwargs):
    """自动生成的抓取方法: essd.copernicus.org (Earth System Science Data)"""
    url = "https://essd.copernicus.org/articles/{vol}/{article_id}/{year}/essd-{vol}-{article_id}-{year}.xml"
    params = kwargs.get("extracted_api_params") or {}
    val_vol = params.get("vol") or kwargs.get("dataset_shortname") or kwargs.get("official_website_id") or kwargs.get("vol")
    if not val_vol:
        val_vol = kwargs.get("doi", "").split("/")[-1] if kwargs.get("doi") else ""
    if not val_vol:
        raise ValueError("Missing required parameter: vol")
    url = url.replace("{vol}", str(val_vol))
    val_article_id = params.get("article_id") or kwargs.get("dataset_shortname") or kwargs.get("official_website_id") or kwargs.get("article_id")
    if not val_article_id:
        val_article_id = kwargs.get("doi", "").split("/")[-1] if kwargs.get("doi") else ""
    if not val_article_id:
        raise ValueError("Missing required parameter: article_id")
    url = url.replace("{article_id}", str(val_article_id))
    val_year = params.get("year") or kwargs.get("dataset_shortname") or kwargs.get("official_website_id") or kwargs.get("year")
    if not val_year:
        val_year = kwargs.get("doi", "").split("/")[-1] if kwargs.get("doi") else ""
    if not val_year:
        raise ValueError("Missing required parameter: year")
    url = url.replace("{year}", str(val_year))
    val_vol = params.get("vol") or kwargs.get("dataset_shortname") or kwargs.get("official_website_id") or kwargs.get("vol")
    if not val_vol:
        val_vol = kwargs.get("doi", "").split("/")[-1] if kwargs.get("doi") else ""
    if not val_vol:
        raise ValueError("Missing required parameter: vol")
    url = url.replace("{vol}", str(val_vol))
    val_article_id = params.get("article_id") or kwargs.get("dataset_shortname") or kwargs.get("official_website_id") or kwargs.get("article_id")
    if not val_article_id:
        val_article_id = kwargs.get("doi", "").split("/")[-1] if kwargs.get("doi") else ""
    if not val_article_id:
        raise ValueError("Missing required parameter: article_id")
    url = url.replace("{article_id}", str(val_article_id))
    val_year = params.get("year") or kwargs.get("dataset_shortname") or kwargs.get("official_website_id") or kwargs.get("year")
    if not val_year:
        val_year = kwargs.get("doi", "").split("/")[-1] if kwargs.get("doi") else ""
    if not val_year:
        raise ValueError("Missing required parameter: year")
    url = url.replace("{year}", str(val_year))
    try:
        response = self._get_with_retry(url, self.headers)
        return {"source": "essd.copernicus.org (Earth System Science Data)-AutoGen", "data": response.json()}
    except Exception as e:
        return {"error": str(e)}
