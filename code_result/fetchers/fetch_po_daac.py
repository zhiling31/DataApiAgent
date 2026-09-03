# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for PO.DAAC
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="PO.DAAC", aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="人工初始审核",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_po_daac(self, **kwargs):
    import json
    import re

    """
    Fetch PO.DAAC dataset-level metadata via NASA CMR (Common Metadata Repository) API.

    PO.DAAC datasets are registered in NASA's CMR, which provides the authoritative
    UMM-JSON metadata via its RESTful search API. This is the official API used by
    PO.DAAC for programmatic metadata access.

    Parsing strategy (waterfall):
      1. DOI -> CMR search by doi parameter (most reliable)
      2. dataset_url -> extract short_name from /dataset/{short_name}
      3. Fallback to dataset_name as short_name
    """
    doi = kwargs.get('doi')
    dataset_url = kwargs.get('dataset_url')
    doi_landing_page = kwargs.get('doi_landing_page')
    dataset_name = kwargs.get('dataset_name')

    cmr_base = "https://cmr.earthdata.nasa.gov/search/collections.umm_json"

    # --- Path 1: Search by DOI (preferred) ---
    if doi:
        # DOI may contain '/' which needs URL encoding
        doi_safe = doi.replace('/', '%2F')
        url = f"{cmr_base}?doi={doi_safe}&page_size=1"
        resp = self._get_with_retry(url)
        try:
            data = resp.json()
        except json.JSONDecodeError:
            return {"error": "CMR returned non-JSON response for DOI search", "source": "NASA CMR (PO.DAAC)"}
        if data and data.get('hits', 0) > 0:
            return {"source": "NASA CMR (PO.DAAC)", "format": "json", "data": data}

    # --- Path 2: Extract short_name from dataset_url ---
    short_name = None
    if dataset_url:
        m = re.search(r'/dataset/([^/?#]+)', dataset_url)
        if m:
            short_name = m.group(1).strip()

    # --- Path 3: Use dataset_name as fallback ---
    if not short_name and dataset_name:
        short_name = dataset_name.strip()

    # --- Search CMR by short_name ---
    if short_name:
        url = f"{cmr_base}?short_name={short_name}&page_size=1"
        resp = self._get_with_retry(url)
        try:
            data = resp.json()
        except json.JSONDecodeError:
            return {"error": "CMR returned non-JSON response for short_name search", "source": "NASA CMR (PO.DAAC)"}
        if data and data.get('hits', 0) > 0:
            return {"source": "NASA CMR (PO.DAAC)", "format": "json", "data": data}

    # --- Nothing found ---
    return {"error": "Could not find dataset in CMR. Provide a valid DOI or dataset URL containing short_name.", "source": "NASA CMR (PO.DAAC)"}
