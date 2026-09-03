# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for Open Government Portal
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="Open Government Portal", aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="人工初始审核",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_open_government_portal(self, **kwargs):
    import re
    import json
    import urllib.parse

    dataset_url = kwargs.get("dataset_url") or ""
    landing_page = kwargs.get("doi_landing_page") or ""
    dataset_name = kwargs.get("dataset_name") or ""
    doi = kwargs.get("doi") or ""

    dataset_id = None

    uuid_re = re.compile(r"/dataset/([0-9a-fA-F-]{36})")
    for candidate_url in (dataset_url, landing_page, doi):
        if candidate_url:
            match = uuid_re.search(candidate_url)
            if match:
                dataset_id = match.group(1)
                break

    if not dataset_id and dataset_name:
        search_query = urllib.parse.urlencode(
            {"q": 'name:"%s"' % dataset_name, "rows": 1}
        )
        search_url = (
            "https://open.canada.ca/data/api/3/action/package_search?"
            + search_query
        )
        try:
            search_resp = self._get_with_retry(search_url)
            try:
                search_json = search_resp.json()
            except (json.JSONDecodeError, AttributeError):
                search_json = {}
            results = (
                search_json.get("result", {}).get("results", [])
                if isinstance(search_json, dict)
                else []
            )
            if results and len(results) > 0:
                dataset_id = results[0].get("id")
        except Exception:
            dataset_id = None

    if not dataset_id:
        return {"error": "缺少关键参数，无法解析出内部 ID"}

    api_url = (
        "https://open.canada.ca/data/api/3/action/package_show?id="
        + urllib.parse.quote(dataset_id, safe="")
    )
    resp = self._get_with_retry(api_url)

    try:
        data = resp.json()
    except (json.JSONDecodeError, AttributeError):
        data = resp.text

    return {
        "source": "Open Government Portal (open.canada.ca)",
        "format": "json",
        "data": data,
    }
