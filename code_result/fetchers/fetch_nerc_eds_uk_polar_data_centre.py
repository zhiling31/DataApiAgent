# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for NERC EDS UK Polar Data Centre
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="NERC EDS UK Polar Data Centre", aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="人工初始审核",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_nerc_eds_uk_polar_data_centre(self, **kwargs):

    import urllib
    """Fetch collection-level metadata from UK Polar Data Centre CSW API.

    The UK PDC (BAS) Discovery Metadata System exposes an OGC CSW 2.0.2
    endpoint (pycsw) at api.bas.ac.uk. A dataset's Discovery Metadata System
    identifier (e.g. GB/NERC/BAS/PDC/01669) is embedded in the landing page
    URL / DOI landing page. This function polymorphically extracts that
    identifier and retrieves the native ISO 19139 metadata record.
    """
    import re
    from urllib.parse import unquote, quote

    dataset_url = kwargs.get("dataset_url") or ""
    doi_landing_page = kwargs.get("doi_landing_page") or ""

    candidate_sources = []
    if dataset_url:
        candidate_sources.append(dataset_url)
    if doi_landing_page:
        candidate_sources.append(doi_landing_page)

    dms_id = None
    for src in candidate_sources:
        if not isinstance(src, str) or not src.strip():
            continue
        decoded = unquote(src)
        m = re.search(r"(GB/NERC/BAS/PDC/\d+)", decoded, flags=re.IGNORECASE)
        if m:
            dms_id = m.group(1).upper()
            break

    if not dms_id:
        doi = kwargs.get("doi") or ""
        if doi and isinstance(doi, str):
            m = re.search(r"(GB/NERC/BAS/PDC/\d+)", doi, flags=re.IGNORECASE)
            if m:
                dms_id = m.group(1).upper()

    if not dms_id:
        return {
            "error": (
                "缺少关键参数，无法解析出内部 ID。请提供 dataset_url 或 "
                "doi_landing_page，其中需包含 GB/NERC/BAS/PDC/XXXXX 形式的标识符。"
            )
        }

    api_url = (
        "https://api.bas.ac.uk/data/metadata/csw/v2"
        "?service=CSW"
        "&version=2.0.2"
        "&request=GetRecordById"
        "&id=" + quote(dms_id, safe="") +
        "&elementSetName=full"
        "&outputSchema=http://www.isotc211.org/2005/gmd"
    )

    headers = {"Accept": "application/xml"}

    response = self._get_with_retry(api_url, headers=headers)

    return {
        "source": "NERC EDS UK Polar Data Centre",
        "format": "xml",
        "data": response.text,
    }
