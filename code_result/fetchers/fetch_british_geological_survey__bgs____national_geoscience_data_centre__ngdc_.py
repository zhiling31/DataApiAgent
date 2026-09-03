# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for British Geological Survey (BGS) - National Geoscience Data Centre (NGDC)
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="British Geological Survey (BGS) - National Geoscience Data Centre (NGDC)", aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="人工初始审核",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_british_geological_survey__bgs____national_geoscience_data_centre__ngdc_(self, **kwargs):
    """Fetch collection-level metadata from BGS NGDC via GeoNetwork OGC API Records + ISO19139 formatter."""
    import re
    import urllib.parse

    doi = kwargs.get('doi') or ''
    dataset_url = kwargs.get('dataset_url') or ''
    doi_landing_page = kwargs.get('doi_landing_page') or ''
    dataset_name = kwargs.get('dataset_name') or ''

    # Step 1: Extract a UUID-like DOI suffix from any available identifier field.
    candidate_uuid = None
    uuid_re = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')
    for raw in (doi, dataset_url, doi_landing_page):
        if raw:
            m = uuid_re.search(raw)
            if m:
                candidate_uuid = m.group(0).lower()
                break

    def _normalise(s):
        return re.sub(r'[^a-z0-9]+', '', (s or '').lower())

    search_base = 'https://metadata.bgs.ac.uk/geonetwork/api/collections/main/items'
    internal_uuid = None

    search_terms = []
    if dataset_name and dataset_name.strip():
        search_terms.append(' '.join(dataset_name.strip().split()))
    if candidate_uuid:
        search_terms.append(candidate_uuid)

    search_terms = list(dict.fromkeys(search_terms))

    if not search_terms:
        return {"error": "缺少关键参数，无法解析出内部记录 ID"}

    norm_name = _normalise(dataset_name) if dataset_name and dataset_name.strip() else None

    for term in search_terms:
        try:
            q = urllib.parse.quote(term)
            url = f"{search_base}?f=json&limit=10&q={q}"
            resp = self._get_with_retry(url)
            payload = resp.json()
            features = payload.get('features') or []
            if not features:
                continue

            chosen = None
            if norm_name:
                for f in features:
                    props = f.get('properties') or {}
                    title = props.get('title') or ''
                    norm_title = _normalise(title)
                    if norm_title and (norm_title == norm_name or norm_name in norm_title):
                        chosen = f
                        break
            else:
                chosen = features[0]

            if chosen and chosen.get('id'):
                internal_uuid = chosen.get('id')
                break
        except Exception:
            continue

    if not internal_uuid:
        return {"error": "无法通过名称或 DOI 后缀解析出内部记录 UUID"}

    xml_url = f"https://metadata.bgs.ac.uk/geonetwork/srv/api/records/{internal_uuid}/formatters/xml"
    try:
        xml_resp = self._get_with_retry(xml_url, headers={'Accept': 'application/xml'})
        if xml_resp.status_code >= 400:
            return {"error": f"ISO19139 元数据请求失败，HTTP {xml_resp.status_code}"}
        return {
            "source": "British Geological Survey (BGS) - National Geoscience Data Centre (NGDC)",
            "format": "xml",
            "data": xml_resp.text,
        }
    except Exception as e:
        return {"error": f"ISO19139 元数据获取异常: {e}"}
