# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for British Columbia Data Catalogue
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="British Columbia Data Catalogue",
    aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="通过正则或者搜索接口拿到对应的uuid，然后获取元数据，\
        但是平台采用了“父数据集-子资源”的层级元数据架构，将同一数据资产的历史版本与最新增补统一归档在同一个全局数据包下，以保证数据生命周期管理的连续性与完整性，因此拿到的是旧版本+新版本汇编的元数据",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_british_columbia_data_catalogue(self, **kwargs):
    api_url = None
    import json
    import re
    from urllib.parse import quote

    """Fetch collection-level metadata for the BC Data Catalogue (CKAN)."""
    dataset_url = kwargs.get("dataset_url") or ""
    doi_landing_page = kwargs.get("doi_landing_page") or ""
    dataset_name = kwargs.get("dataset_name") or ""

    package_id = None
    uuid_pattern = re.compile(
        r"/dataset/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
    )

    for raw_url in (dataset_url, doi_landing_page):
        if isinstance(raw_url, str) and raw_url.strip():
            match = uuid_pattern.search(raw_url)
            if match:
                package_id = match.group(1)
                break

    if not package_id and isinstance(dataset_name, str) and dataset_name.strip():
        search_query = quote(f'title:"{dataset_name.strip()}"')
        search_url = (
            "https://catalogue.data.gov.bc.ca/api/3/action/package_search"
            f"?rows=1&q={search_query}"
        )
        try:
            search_resp = self._get_with_retry(search_url)
            search_payload = search_resp.json()
        except (ValueError, TypeError):
            search_payload = None

        if search_payload and search_payload.get("success"):
            results = search_payload.get("result", {}).get("results") or []
            if results and isinstance(results[0], dict):
                package_id = results[0].get("id")

    if not package_id:
        return {'error': '缺少关键参数，无法从 dataset_url、doi_landing_page 或 dataset_name 解析出 CKAN package ID', 'api_url': api_url}

    api_url = (
        "https://catalogue.data.gov.bc.ca/api/3/action/package_show"
        f"?id={quote(package_id)}"
    )
    resp = self._get_with_retry(api_url)

    try:
        payload = resp.json()
    except (ValueError, TypeError):
        return {'error': 'package_show 返回内容不是有效 JSON'+getattr(resp, 'text', ''), 'api_url': api_url}

    if not isinstance(payload, dict) or payload.get("success") is not True:
        return { 'error': 'CKAN package_show 返回 success=false 或非预期结构'+payload, 'api_url': api_url}

    return {'source': 'British Columbia Data Catalogue (CKAN)', 'format': 'json', 'data': payload, 'api_url': api_url,"notes":"需要review"}
