# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for Utah Geospatial Resource Center (UGRC)
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="Utah Geospatial Resource Center (UGRC)",
    aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="AI 初始判定",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_utah_geospatial_resource_center__ugrc_(self, **kwargs):
    import re
    import json
    dataset_url = kwargs.get("dataset_url")
    doi_landing_page = kwargs.get("doi_landing_page")

    if not dataset_url and not doi_landing_page:
        return {"error": "缺少关键参数 dataset_url / doi_landing_page，无法解析出 ArcGIS REST 服务 URL"}

    raw_candidates = []
    if dataset_url:
        raw_candidates.append(dataset_url)
    if doi_landing_page:
        raw_candidates.append(doi_landing_page)

    arcgis_url = None
    arcgis_pattern = re.compile(r'https?://[^\s;"]+/arcgis/rest/services/[^\s;"]+', re.IGNORECASE)

    for raw in raw_candidates:
        if not raw:
            continue
        for part in raw.split(";"):
            part = part.strip()
            if not part:
                continue
            match = arcgis_pattern.search(part)
            if match:
                arcgis_url = match.group(0)
                break
        if arcgis_url:
            break

    if not arcgis_url:
        return {"error": "无法从 dataset_url / doi_landing_page 中解析出 ArcGIS REST 服务 URL"}

    arcgis_url = arcgis_url.split("?")[0].split("#")[0].rstrip("/")
    api_url = f"{arcgis_url}?f=json"

    try:
        response = self._get_with_retry(api_url, headers={"Accept": "application/json"})
    except Exception as exc:
        return {"error": f"HTTP 请求失败: {exc}","api_url": api_url}

    if response is None:
        return {"error": "HTTP 请求返回空响应","api_url": api_url}


    return {
        "source": "Utah Geospatial Resource Center (UGRC)",
        "format": "json",
        "data": response.json(),
        "api_url": api_url
    }
