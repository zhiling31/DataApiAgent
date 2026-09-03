# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for NSW Resources
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="NSW Resources", aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="人工初始审核",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_nsw_resources(self, **kwargs):

    import urllib
    import re
    from urllib.parse import quote

    dataset_url = kwargs.get('dataset_url') or ''
    landing = kwargs.get('doi_landing_page') or ''
    name = kwargs.get('dataset_name') or ''

    base = 'https://geonetwork.geoscience.nsw.gov.au/geonetwork'

    # ---- Step 1: derive a search keyword from available inputs ----
    keyword = None
    if dataset_url:
        m = re.search(r'([^/]+)\.(?:zip|tif|ers|img|asc|bin)$', dataset_url, re.IGNORECASE)
        if m:
            stem = m.group(1)
            stem = re.sub(r'[_-](?:GDA\d+|MGA\d+|EPSG\d+).*$', '', stem, flags=re.IGNORECASE)
            keyword = stem.replace('_', ' ').strip()
    if not keyword and landing:
        m = re.search(r'/([^/]+?)(?:\.html?)?/?$', landing)
        if m:
            keyword = m.group(1).replace('-', ' ').replace('_', ' ').strip()
    if not keyword and name:
        keyword = name.strip()

    if not keyword:
        return {'error': '缺少关键参数，无法解析出检索关键词'}

    # ---- Step 2: dynamic mapping (keyword -> catalogue UUID) ----
    search_url = base + '/srv/eng/q?any=' + quote(keyword) + '&resultType=results&fast=index'
    search_resp = self._get_with_retry(search_url)
    search_text = search_resp.text if hasattr(search_resp, 'text') else str(search_resp)

    uuid_m = re.search(r'<uuid>([0-9a-fA-F-]{36})</uuid>', search_text)
    print("uuid",uuid_m)
    if not uuid_m:
        uuid_m = re.search(r'uuid="([0-9a-fA-F-]{36})"', search_text)
    if not uuid_m:
        return {'error': '未能在 GeoNetwork 目录中检索到匹配的元数据记录', 'search_response': search_text[:500]}

    record_uuid = uuid_m.group(1)

    # ---- Step 3: fetch native ISO 19115 (19139) metadata ----
    meta_url = base + '/srv/api/records/' + record_uuid + '/formatters/iso19139'
    resp = self._get_with_retry(meta_url)
    body = resp.text if hasattr(resp, 'text') else str(resp)

    return {
        'source': 'NSW Geoscience Metadata (GeoNetwork)',
        'format': 'xml',
        'data': body
    }
