# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for Open Yukon / Government of Yukon
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="Open Yukon / Government of Yukon",
    aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="AI 初始判定",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_open_yukon___government_of_yukon(self, **kwargs):
    api_url = None
    import re
    import json
    from urllib.parse import quote

    def extract_package_uuid(text):
        if not text:
            return None

        m = re.search(
            r'/record/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})',
            text
        )
        if m:
            return m.group(1)

        m = re.search(
            r'/data/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/resource/',
            text
        )
        if m:
            return m.group(1)

        m = re.search(
            r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}',
            text
        )
        if m:
            return m.group(0)

        return None

    def resolve_package_uuid_by_name(name):
        if not name:
            return None

        search_url = 'https://open.yukon.ca/api/3/action/package_search?q={}&rows=10'.format(quote(name))
        try:
            search_resp = self._get_with_retry(search_url)
            payload = search_resp.json()
        except Exception:
            return None

        if not isinstance(payload, dict) or not payload.get('success'):
            return None

        results = payload.get('result', {}).get('results') or []
        if not isinstance(results, list):
            return None

        name_lower = name.strip().lower()
        fallback_id = None

        for item in results:
            if not isinstance(item, dict):
                continue
            item_id = item.get('id')
            item_name = item.get('name') or ''
            item_title = item.get('title') or ''
            if not item_id:
                continue
            if item_name.strip().lower() == name_lower or item_title.strip().lower() == name_lower:
                return item_id
            if fallback_id is None and name_lower and name_lower in item_name.strip().lower():
                fallback_id = item_id

        return fallback_id

    dataset_url = kwargs.get('dataset_url')
    doi_landing_page = kwargs.get('doi_landing_page')
    dataset_name = kwargs.get('dataset_name')

    package_id = None

    for candidate_text in (dataset_url, doi_landing_page):
        package_id = extract_package_uuid(candidate_text)
        if package_id:
            break

    if not package_id:
        package_id = resolve_package_uuid_by_name(dataset_name)

    if not package_id:
        return {'error': '缺少关键参数，无法解析出内部 package ID', 'api_url': api_url}

    api_url = 'https://open.yukon.ca/api/3/action/package_show?id={}'.format(package_id)
    headers = {
        'Accept': 'application/json',
        'User-Agent': 'Mozilla/5.0 (metadata-harvester)',
    }

    resp = self._get_with_retry(api_url, headers=headers)

    try:
        data = resp.json()
    except Exception as exc:
        return {'error': 'CKAN API 未返回有效 JSON: {}'.format(exc), 'api_url': api_url}

    if isinstance(data, dict) and data.get('success') is False:
        return {'error': 'CKAN API 返回 success=false', 'data': data, 'api_url': api_url}

    return {'source': 'Open Yukon / Government of Yukon CKAN API', 'format': 'json', 'data': data, 'api_url': api_url}
