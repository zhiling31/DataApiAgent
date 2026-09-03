# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for British Columbia Geological Survey (BC Data Catalogue)
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="British Columbia Geological Survey (BC Data Catalogue)",
    aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="通过正则或者搜索接口拿到对应的uuid，然后获取元数据，\
        但是平台采用了“父数据集-子资源”的层级元数据架构，将同一数据资产的历史版本与最新增补统一归档在同一个全局数据包下，以保证数据生命周期管理的连续性与完整性，因此拿到的是旧版本+新版本汇编的元数据",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_british_columbia_geological_survey__bc_data_catalogue_(self, **kwargs):
    import json
    import re
    import urllib.parse
    from urllib.parse import quote

    api_url = None
    dataset_url = kwargs.get("dataset_url") or ""
    doi_landing_page = kwargs.get("doi_landing_page") or ""
    dataset_name = kwargs.get("dataset_name") or ""

    package_id = None
    
    # 策略 1: 使用用户提供的 UUID 正则提取 (优先尝试用户原本写的“老逻辑”)
    uuid_pattern = re.compile(
        r"/dataset/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
    )
    for raw_url in (dataset_url, doi_landing_page):
        if isinstance(raw_url, str) and raw_url.strip():
            match = uuid_pattern.search(raw_url)
            if match:
                package_id = match.group(1)
                break

    # 策略 2: 使用 title:"dataset_name" 搜索 (优先尝试用户原本写的“老逻辑”)
    if not package_id and isinstance(dataset_name, str) and dataset_name.strip():
        search_query = quote(f'title:"{dataset_name.strip()}"')
        search_url = (
            "https://catalogue.data.gov.bc.ca/api/3/action/package_search"
            f"?rows=1&q={search_query}"
        )
        try:
            search_resp = self._get_with_retry(search_url)
            search_payload = search_resp.json()
            if search_payload and search_payload.get("success"):
                results = search_payload.get("result", {}).get("results") or []
                if results and isinstance(results[0], dict):
                    package_id = results[0].get("id")
        except (ValueError, TypeError):
            pass

    # 策略 3: 使用 GF 标识提取与通用关键词搜索 (我最初写的，作为兜底“新逻辑”)
    if not package_id:
        query = None
        for candidate in (dataset_url, doi_landing_page):
            if not candidate:
                continue
            m = re.search(r'GF\s*(\d{4})\s*[-_]\s*(\d{1,3})', str(candidate), re.I)
            if m:
                query = "GeoFile {}-{}".format(m.group(1), m.group(2))
                break
        
        if not query and isinstance(dataset_name, str) and dataset_name.strip():
            query = str(dataset_name).strip()

        if query:
            search_url = (
                "https://catalogue.data.gov.bc.ca/api/3/action/package_search?q="
                + urllib.parse.quote(query)
                + "&rows=1"
            )
            try:
                search_resp = self._get_with_retry(search_url)
                search_data = search_resp.json()
                results = (search_data.get("result") or {}).get("results") or []
                
                # 优先匹配 title 或 name
                if dataset_name and str(dataset_name).strip():
                    needle = str(dataset_name).strip().lower()
                    for item in results:
                        title = (item.get("title") or "").strip().lower()
                        slug = (item.get("name") or "").strip().lower()
                        if needle and (needle in title or needle in slug):
                            package_id = item.get("id")
                            break
                if not package_id and results:
                    package_id = results[0].get("id")
            except (ValueError, TypeError):
                pass

    if not package_id:
        return {'error': '缺少关键参数，无法从 dataset_url、doi_landing_page 或 dataset_name 解析出 CKAN package ID', 'api_url': api_url}

    # 公共逻辑：统一合并到这里，通过 package_show 获取最终元数据
    api_url = (
        "https://catalogue.data.gov.bc.ca/api/3/action/package_show"
        f"?id={quote(str(package_id))}"
    )
    resp = self._get_with_retry(api_url)

    try:
        payload = resp.json()
    except (ValueError, TypeError):
        return {'error': 'package_show 返回内容不是有效 JSON: ' + getattr(resp, 'text', ''), 'api_url': api_url}

    if not isinstance(payload, dict) or payload.get("success") is not True:
        return {'error': 'CKAN package_show 返回 success=false 或非预期结构: ' + str(payload), 'api_url': api_url}

    return {
        'source': 'British Columbia Data Catalogue (CKAN)', 
        'format': 'json', 
        'data': payload, 
        'api_url': api_url, 
        "notes": "需要review"
    }
