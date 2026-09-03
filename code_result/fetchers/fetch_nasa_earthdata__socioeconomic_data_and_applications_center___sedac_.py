# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for NASA Earthdata (Socioeconomic Data and Applications Center – SEDAC)
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="NASA Earthdata / NASA Earthdata(Socioeconomic Data and Applications Center – SEDAC)", aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="人工初始审核",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_nasa_earthdata__socioeconomic_data_and_applications_center___sedac_(self, **kwargs):
    """
    Fetch collection-level metadata from NASA Earthdata CMR for SEDAC datasets.

    Uses the CMR (Common Metadata Repository) API: 
    - Resolves DOI or URL to a concept ID via CMR search
    - Retrieves full UMM-JSON metadata via the concept endpoint
    """
    import re
    import urllib.parse

    doi = kwargs.get('doi')
    dataset_url = kwargs.get('dataset_url') or kwargs.get('doi_landing_page')

    concept_id = None

    # --- Polymorphic parameter resolution: resolve concept ID ---
    # Path 1: Use DOI to search CMR collections
    if doi:
        search_url = (
            "https://cmr.earthdata.nasa.gov/search/collections.umm_json"
            f"?doi={urllib.parse.quote(doi, safe='')}"
        )
        try:
            search_resp = self._get_with_retry(search_url)
            search_data = search_resp.json()
            items = search_data.get('items', [])
            if items and len(items) > 0:
                concept_id = items[0].get('meta', {}).get('concept-id')
        except Exception:
            pass

    # Path 2: If no DOI, extract slug from URL and search CMR by entry_id
    if not concept_id and dataset_url:
        # Extract the last meaningful path segment from Earthdata catalog URL
        # e.g. ".../catalog/sedac-ciesin-sedac-gpwv4-popdens-r11-4.11"
        match = re.search(
            r'/catalog/(?:sedac-)?([a-zA-Z0-9]+(?:-[a-zA-Z0-9]+)+'
            r'(?:-r\d+)?(?:-\d+\.\d+)?)',
            dataset_url
        )
        if match:
            raw_slug = match.group(1)
            # Transform to CMR entry_id format: lowercase with underscores
            entry_id = raw_slug.upper().replace('-', '_')
            search_url = (
                "https://cmr.earthdata.nasa.gov/search/collections.umm_json"
                f"?entry_id={entry_id}"
            )
            try:
                search_resp = self._get_with_retry(search_url)
                search_data = search_resp.json()
                items = search_data.get('items', [])
                if items and len(items) > 0:
                    concept_id = items[0].get('meta', {}).get('concept-id')
            except Exception:
                pass

    # Path 3: Try broader URL extraction - just grab the catalog slug portion
    if not concept_id and dataset_url:
        match = re.search(r'/catalog/([^/\s?#]+)', dataset_url)
        if match:
            raw_slug = match.group(1)
            # Remove leading 'sedac-' if present, then transform
            if raw_slug.lower().startswith('sedac-'):
                raw_slug = raw_slug[6:]
            # Try entry_id and short_name searches
            candidate = raw_slug.upper().replace('-', '_')
            for param in ['entry_id', 'short_name']:
                search_url = (
                    "https://cmr.earthdata.nasa.gov/search/collections.umm_json"
                    f"?{param}={candidate}"
                )
                try:
                    search_resp = self._get_with_retry(search_url)
                    search_data = search_resp.json()
                    items = search_data.get('items', [])
                    if items and len(items) > 0:
                        concept_id = items[0].get('meta', {}).get('concept-id')
                        break
                except Exception:
                    continue

    if not concept_id:
        return {
            "error": (
                "无法解析出 CMR concept ID。请提供有效的 DOI 或包含 "
                "Earthdata catalog slug 的 dataset_url。"
            )
        }

    # --- Final API: CMR Concept endpoint (UMM-JSON) ---
    # This is the most data-rich, native RESTful API for a single collection
    concept_url = (
        "https://cmr.earthdata.nasa.gov/search/concepts"
        f"/{concept_id}.umm_json"
    )
    resp = self._get_with_retry(concept_url)

    return {
        "source": "NASA Earthdata CMR",
        "format": "json",
        "data": resp.json()
    }
