# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for NERC EDS National Geoscience Data Centre
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="NERC EDS National Geoscience Data Centre", aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="人工初始审核",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_nerc_eds_national_geoscience_data_centre(self, **kwargs):

    import urllib
    import re
    from urllib.parse import urlencode

    doi = kwargs.get('doi') or ''
    dataset_url = kwargs.get('dataset_url') or ''
    doi_landing_page = kwargs.get('doi_landing_page') or ''

    # --- 1. Extract the DOI suffix UUID (ed322978-...) from doi / url / landing page ---
    doi_uuid = None
    if doi:
        m = re.search(r'10\.5285/([0-9a-fA-F-]{36})', doi)
        if m:
            doi_uuid = m.group(1)
    uuid_re = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')
    if not doi_uuid:
        for candidate in (dataset_url, doi_landing_page):
            if candidate:
                m = uuid_re.search(candidate)
                if m:
                    doi_uuid = m.group(0)
                    break
    if not doi_uuid:
        return {"error": "缺少关键参数，无法解析出内部 ID（DOI UUID）"}

    # --- 2. Dynamic mapping: DOI UUID -> GeoNetwork internal fileIdentifier via CSW ---
    # The CSW/Lucene index tokenises hyphenated strings, so use the first UUID segment
    # as the search token (it is the leading DOI suffix segment and is highly selective).
    search_token = doi_uuid.split('-')[0] if '-' in doi_uuid else doi_uuid
    csw_params = {
        'service': 'CSW',
        'version': '2.0.2',
        'request': 'GetRecords',
        'resultType': 'results',
        'outputSchema': 'http://www.isotc211.org/2005/gmd',
        'elementSetName': 'full',
        'constraintLanguage': 'CQL_TEXT',
        'constraint_language_version': '1.1.0',
        'constraint': "AnyText like '%{}%'".format(search_token),
    }
    csw_url = 'https://data-search.nerc.ac.uk/geonetwork/srv/eng/csw?' + urlencode(csw_params)
    csw_resp = self._get_with_retry(csw_url, headers={'Accept': 'application/xml'})
    csw_text = csw_resp.text

    file_id = None
    m = re.search(r'<gco:CharacterString>([0-9a-fA-F-]{36})</gco:CharacterString>', csw_text)
    if m:
        file_id = m.group(1)
    if not file_id:
        return {"error": "CSW 搜索响应中未找到 GeoNetwork 内部记录 ID，无法完成映射"}

    # --- 3. Final single native RESTful API: GeoNetwork records formatters/xml ---
    rest_url = 'https://data-search.nerc.ac.uk/geonetwork/srv/api/records/{}/formatters/xml'.format(file_id)
    rest_resp = self._get_with_retry(rest_url, headers={'Accept': 'application/xml'})
    return {
        'source': 'NERC EDS National Geoscience Data Centre (via NERC Data Catalogue Service GeoNetwork)',
        'format': 'xml',
        'data': rest_resp.text,
    }
