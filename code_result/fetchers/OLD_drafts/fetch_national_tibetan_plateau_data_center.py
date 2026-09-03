# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for National Tibetan Plateau Data Center
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="National Tibetan Plateau Data Center",
    aliases=[],
    has_api=True,
    is_reviewed=False,
    auditor_notes="AI 初始判定",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_national_tibetan_plateau_data_center(self, **kwargs):
    """自动生成的抓取方法: National Tibetan Plateau Data Center"""
    url = "https://data.tpdc.ac.cn/view/export/exportJsonMetadata?metadataId={dataset_id}"
    params = kwargs.get("extracted_api_params") or {}
    val_dataset_id = params.get("dataset_id") or kwargs.get("dataset_shortname") or kwargs.get("official_website_id") or kwargs.get("dataset_id")
    if not val_dataset_id:
        val_dataset_id = kwargs.get("doi", "").split("/")[-1] if kwargs.get("doi") else ""
    if not val_dataset_id:
        raise ValueError("Missing required parameter: dataset_id")
    url = url.replace("{dataset_id}", str(val_dataset_id))
    try:
        response = self._get_with_retry(url, self.headers)
        return {"source": "National Tibetan Plateau Data Center-AutoGen", "data": response.json()}
    except Exception as e:
        return {"error": str(e)}
