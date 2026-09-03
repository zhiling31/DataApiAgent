# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for BC Data Catalogue
from code_result.fetcher_decorator import register_api

import json
import re
import urllib.parse
@register_api(
    publisher="BC Data Catalogue",
    aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="AI 初始判定",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_bc_data_catalogue(self, **kwargs):
    package_url = None
    """Fetch collection-level metadata for BC Geochronology from the BC Data Catalogue CKAN API."""
    dataset_name = kwargs.get("dataset_name")
    dataset_url = kwargs.get("dataset_url")
    doi_landing_page = kwargs.get("doi_landing_page")

    package_id = None

    # Helper: extract a 36-char CKAN dataset UUID from known catalogue URL patterns.
    def extract_package_id(text):
        if not text:
            return None
        # Prefer the canonical BC Data Catalogue path.
        m = re.search(r"catalogue\.data\.gov\.bc\.ca/dataset/([0-9a-fA-F-]{36})", text)
        if m:
            return m.group(1)
        # Fallback to any /dataset/<uuid>-style path.
        m = re.search(r"/dataset/([0-9a-fA-F-]{36})", text)
        if m:
            return m.group(1)
        return None

    # 1) Try extracting a CKAN UUID from the supplied URL(s).
    for text in (dataset_url, doi_landing_page):
        package_id = extract_package_id(text)
        if package_id:
            break

    # 2) If no ID was found, query the catalogue's native search API by dataset name.
    if not package_id and dataset_name:
        q = urllib.parse.quote(dataset_name.strip().replace('"', ' '), safe="")
        search_url = (
            "https://catalogue.data.gov.bc.ca/api/3/action/package_search?q=" + q
        )
        resp = self._get_with_retry(
            search_url, headers={"Accept": "application/json"}
        )
        try:
            search_payload = json.loads(resp.text)
        except (json.JSONDecodeError, AttributeError) as exc:
            return {'error': f'BC Data Catalogue search returned non-JSON: {exc}'}

        # Defensive list boundary checks: only index if the result list is non-empty.
        if search_payload and search_payload.get("success"):
            results = (
                search_payload.get("result", {}).get("results") or []
            )
            if results and len(results) > 0:
                package_id = results[0].get("id")

    # 3) Fail gracefully if we still do not have an internal ID.
    if not package_id:
        return {'error': '缺少关键参数，无法解析出内部 ID；请提供 catalogue.data.gov.bc.ca/dataset/<UUID> 链接或 dataset_name。'}

    # 4) Request the authoritative collection-level metadata from the native CKAN API.
    package_url = (
        "https://catalogue.data.gov.bc.ca/api/3/action/package_show?id=" + package_id
    )
    resp = self._get_with_retry(
        package_url, headers={"Accept": "application/json"}
    )

    # Return the raw native JSON unchanged. Downstream cleaning is deliberate.
    try:
        data = json.loads(resp.text)
    except (json.JSONDecodeError, AttributeError) as exc:
        return {'error': f'BC Data Catalogue package_show returned non-JSON: {exc}', 'api_url': package_url}

    return {'source': 'BC Data Catalogue', 'format': 'json', 'data': data, 'api_url': package_url}
