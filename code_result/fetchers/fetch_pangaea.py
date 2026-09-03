# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for PANGAEA
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="PANGAEA", aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="人工初始审核",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_pangaea(self, **kwargs):
    """Fetch PANGAEA dataset-level metadata via the official OAI-PMH provider."""
    import re

    doi = kwargs.get("doi")
    dataset_url = kwargs.get("dataset_url")
    doi_landing_page = kwargs.get("doi_landing_page")

    candidates = []
    if doi:
        candidates.append(doi)
    if doi_landing_page:
        candidates.append(doi_landing_page)
    if dataset_url:
        candidates.append(dataset_url)

    doi_value = None
    doi_pattern = re.compile(r"10\.1594/PANGAEA\.\d+", re.IGNORECASE)
    for candidate in candidates:
        if candidate:
            match = doi_pattern.search(candidate)
            if match:
                doi_value = match.group(0)
                break

    if not doi_value:
        return {
            "error": "缺少关键参数，无法解析出 PANGAEA DOI "
                     "(需要 doi / dataset_url / doi_landing_page 之一)"
        }

    identifier = "oai:pangaea.de:doi:" + doi_value
    base_url = "https://ws.pangaea.de/oai/provider"
    api_url = (
        base_url
        + "?verb=GetRecord"
        + "&metadataPrefix=iso19139"
        + "&identifier="
        + identifier
    )

    response = self._get_with_retry(api_url)

    return {
        "source": "PANGAEA",
        "format": "xml",
        "data": response.text,
    }
