# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for OSTI
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="OSTI", aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="人工初始审核",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_osti(self, **kwargs):
    import re

    doi = kwargs.get('doi')
    dataset_url = kwargs.get('dataset_url') or ''
    doi_landing_page = kwargs.get('doi_landing_page') or ''
    dataset_name = kwargs.get('dataset_name') or ''

    # Polymorphic DOI resolution: prefer the explicit DOI argument, then
    # attempt to extract a DOI from the landing page URL or dataset URL.
    if not doi:
        for candidate in (doi_landing_page, dataset_url, dataset_name):
            if candidate:
                m = re.search(r'10\.\d{4,9}/[^\s"\'<>]+', candidate)
                if m:
                    doi = m.group(0).rstrip('.,;')
                    break

    if not doi:
        return {"error": "缺少关键参数，无法解析出 DOI"}

    # OSTI DOE Data Explorer native REST API: query the dataset record by DOI.
    api_url = "https://www.osti.gov/dataexplorer/api/v1/records?doi=" + doi
    headers = {"Accept": "application/json"}

    resp = self._get_with_retry(api_url, headers=headers)

    # Pass through the native structured metadata untouched.
    try:
        data = resp.json()
    except Exception:
        return {
            "source": "OSTI DOE Data Explorer",
            "format": "json",
            "data": resp.text,
        }

    return {
        "source": "OSTI DOE Data Explorer",
        "format": "json",
        "data": data,
    }
