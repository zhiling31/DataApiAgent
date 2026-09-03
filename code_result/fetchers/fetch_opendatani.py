# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for OpenDataNI
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="OpenDataNI", aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="人工初始审核",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_opendatani(self, **kwargs):

    import urllib
    import re
    import json
    from urllib.parse import urlencode

    API_BASE = 'https://admin.opendatani.gov.uk'
    dataset_url = kwargs.get('dataset_url') or ''
    doi_landing_page = kwargs.get('doi_landing_page') or ''
    dataset_name = kwargs.get('dataset_name') or ''

    package_id = None

    # 1) 从 dataset_url / doi_landing_page 中提取 CKAN package UUID
    uuid_pattern = re.compile(
        r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
    )
    for candidate in (dataset_url, doi_landing_page):
        if candidate:
            m = uuid_pattern.search(candidate)
            if m:
                package_id = m.group(0)
                break

    # 2) 兜底：若 URL 是形如 .../dataset/<slug> 的数据集页面，则取末段作为 CKAN name/slug
    if not package_id:
        for candidate in (dataset_url, doi_landing_page):
            if candidate and re.search(r'/(dataset|data|datasets)/', candidate, re.IGNORECASE):
                cleaned = candidate.rstrip('/')
                parts = cleaned.split('/')
                if parts:
                    slug = parts[-1]
                    if slug and not slug.lower().endswith(('.zip', '.json', '.xml', '.csv', '.tif', '.tiff', '.geotiff')):
                        package_id = slug
                        break

    # 3) 兜底：用 dataset_name 通过 package_search 精确匹配 title/name 解析出 UUID
    if not package_id and dataset_name:
        search_url = API_BASE + '/api/3/action/package_search?' + urlencode({
            'q': dataset_name,
            'rows': 20,
        })
        try:
            search_resp = self._get_with_retry(search_url, headers={'Accept': 'application/json'})
            search_json = search_resp.json()
            results = (search_json.get('result') or {}).get('results') or []
            for item in results:
                if (item.get('title') == dataset_name) or (item.get('name') == dataset_name):
                    package_id = item.get('id')
                    break
        except Exception:
            package_id = None

    if not package_id:
        return {"error": "缺少关键参数，无法解析出内部 ID"}

    final_url = API_BASE + '/api/3/action/package_show?' + urlencode({'id': package_id})
    headers = {'Accept': 'application/json'}
    resp = self._get_with_retry(final_url, headers=headers)

    try:
        data = resp.json()
    except Exception:
        data = resp.text

    return {
        "source": "OpenDataNI",
        "format": "json",
        "data": data,
    }
