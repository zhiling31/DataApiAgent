# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for NOAA Science On a Sphere
from code_result.fetcher_decorator import register_api

import json
import re
@register_api(
    publisher="NOAA Science On a Sphere",
    aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="返回的是全站元数据，然后从中检索出对应的数据集",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_noaa_science_on_a_sphere(self, **kwargs):
    catalog_url = None
    # 1) Resolve target dataset slug from the only guaranteed external inputs.
    raw_url = kwargs.get('dataset_url') or kwargs.get('doi_landing_page') or ''
    dataset_name = kwargs.get('dataset_name') or ''

    if not raw_url and not dataset_name:
        return {'error': '缺少 dataset_url/doi_landing_page/dataset_name，无法解析 SOS 数据集 slug'}

    slug = None

    # 2) Prefer the /catalog/datasets/<slug>/ path from a landing/DOI URL.
    if raw_url:
        urls = re.findall(r'https?://[^\s;"]+', raw_url)
        for url in urls:
            if not url:
                continue
            m = re.search(r'/catalog/datasets/([^/?#]+)', url)
            if m and m.group(1):
                slug = m.group(1).strip('/')
                break

    # 3) Fallback: slugify dataset_name.
    if not slug and dataset_name:
        slug = re.sub(r'[^a-z0-9]+', '-', dataset_name.lower()).strip('-')

    if not slug:
        return {'error': '无法从入参中解析出 SOS 数据集 slug', 'api_url': catalog_url}

    catalog_url = "https://sos.noaa.gov/catalog/datasets/catalog.json"

    # 4) Request the official static catalog JSON exposed by the SOS dataset browser.
    resp = self._get_with_retry(catalog_url, headers={"Accept": "application/json"})
    if not resp:
        return {'error': 'catalog.json 请求失败', 'api_url': catalog_url}

    try:
        data = resp.json()
    except Exception as e:
        return {'error': f'catalog.json 不是合法 JSON: {e}', 'api_url': catalog_url}

    if not isinstance(data, list) or len(data) == 0:
        return {'error': 'catalog.json 数据结构异常', 'api_url': catalog_url}

    # 5) Select the exact dataset record; do not clean/rename any of its fields.
    candidates = [d for d in data if isinstance(d, dict)]
    selected = None

    for item in candidates:
        item_slug = item.get('slug')
        item_url = item.get('url')
        if item_url is None:
            item_url = ''
        if slug and item_slug == slug:
            selected = item
            break
        candidate_path = item_url.rstrip('/') if item_url else ''
        expected_path = f"/catalog/datasets/{slug}"
        if slug and candidate_path == expected_path:
            selected = item
            break

    # Last-resort exact-name match within the same native catalog JSON record set.
    if selected is None and dataset_name:
        expected_name = dataset_name.strip()
        for item in candidates:
            item_name = item.get('name')
            if expected_name and item_name == expected_name:
                selected = item
                break

    if selected is None:
        return {'error': f'未在 catalog.json 中找到目标数据集: slug={slug}', 'api_url': catalog_url}

    return {'source': 'NOAA Science On a Sphere', 'format': 'json', 'data': selected, 'api_url': catalog_url}
