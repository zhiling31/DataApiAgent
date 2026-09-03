# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for Oregon GEOHub
from code_result.fetcher_decorator import register_api

import re
@register_api(
    publisher="Oregon GEOHub",
    aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="AI 初始判定",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_oregon_geohub(self, **kwargs):
    api_url = None
    """Fetch Oregon GEOHub / ArcGIS Online dataset metadata via the native ArcGIS Sharing REST API."""
    dataset_url = kwargs.get("dataset_url") or ""
    doi_landing_page = kwargs.get("doi_landing_page") or ""

    item_id = None

    # 1) Try to extract the ArcGIS Online item ID directly from the supplied URLs.
    for text in (dataset_url, doi_landing_page):
        if text:
            m = re.search(r"/items/([0-9a-fA-F]{32})", text)
            if m:
                item_id = m.group(1)
                break

    # 2) If only a landing page was supplied (e.g. catalog.data.gov), fetch the page
    #    only to discover the hidden ArcGIS item ID; never use HTML as final metadata.
    if not item_id and dataset_url:
        try:
            resp = self._get_with_retry(dataset_url, headers={"Accept": "text/html"})
            if resp is not None and getattr(resp, "text", None):
                m = re.search(r"/items/([0-9a-fA-F]{32})", resp.text)
                if m:
                    item_id = m.group(1)
        except Exception:
            pass

    if not item_id:
        return {'error': '缺少关键参数，无法解析出内部 item ID', 'api_url': api_url}

    api_url = "https://www.arcgis.com/sharing/rest/content/items/{item_id}?f=json".format(item_id=item_id)
    resp = self._get_with_retry(api_url, headers={"Accept": "application/json"})

    if resp is None:
        return {'error': 'ArcGIS Sharing REST API 请求失败', 'api_url': api_url}

    try:
        data = resp.json()
        return {'source': 'ArcGIS Online Sharing REST API', 'format': 'json', 'data': data, 'api_url': api_url}
    except Exception:
        return {'source': 'ArcGIS Online Sharing REST API', 'format': 'text', 'data': resp.text, 'api_url': api_url}
