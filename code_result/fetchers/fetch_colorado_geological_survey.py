# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for Colorado Geological Survey
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="Colorado Geological Survey", aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="人工初始审核",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_colorado_geological_survey(self, **kwargs):

    import urllib
    import re
    import json
    from urllib.parse import urlencode, quote

    dataset_url = kwargs.get('dataset_url') or ''
    doi_landing_page = kwargs.get('doi_landing_page') or ''
    dataset_name = kwargs.get('dataset_name') or ''

    slug = None

    # Path 1/2: extract publication slug from landing page URLs
    for candidate_url in (dataset_url, doi_landing_page):
        if not candidate_url:
            continue
        match = re.search(r'/publications/([^/?#]+)', candidate_url)
        if match and match.group(1):
            slug = match.group(1).strip('/')
            break

    # Path 3: resolve slug by exact-title match via the native search API
    if not slug and dataset_name:
        query = urlencode({
            'search': dataset_name,
            'per_page': 50,
            '_fields': 'slug,title',
        })
        search_url = 'https://coloradogeologicalsurvey.org/wp-json/wp/v2/publications?' + query
        try:
            search_resp = self._get_with_retry(search_url)
            search_data = search_resp.json()
        except Exception:
            search_data = None
        if isinstance(search_data, list):
            target = dataset_name.strip().lower()
            for item in search_data:
                if not isinstance(item, dict):
                    continue
                title_obj = item.get('title') or {}
                title = (title_obj.get('rendered') or '').strip().lower()
                if title and target and title == target:
                    slug = item.get('slug')
                    break

    if not slug:
        return {"error": "缺少关键参数，无法解析出内部 slug"}

    final_url = (
        'https://coloradogeologicalsurvey.org/wp-json/wp/v2/publications'
        '?slug=' + quote(slug)
    )
    resp = self._get_with_retry(final_url)
    try:
        data = resp.json()
    except Exception:
        data = resp.text

    return {
        "source": "Colorado Geological Survey",
        "format": "json",
        "data": data,
    }
