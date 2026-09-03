# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for Geoscience Australia
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="Geoscience Australia", aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="人工初始审核",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_geoscience_australia(self, **kwargs):
    import re

    doi = kwargs.get('doi') or ''
    dataset_url = kwargs.get('dataset_url') or ''
    landing_page = kwargs.get('doi_landing_page') or ''

    ecat_id = None
    if doi:
        m = re.search(r'10\.26186/(\d+)', doi)
        if m:
            ecat_id = m.group(1)
    if not ecat_id and landing_page:
        m = re.search(r'/metadata/(\d+)', landing_page)
        if m:
            ecat_id = m.group(1)
    if not ecat_id and dataset_url:
        m = re.search(r'cloudfront\.net/(\d+)/', dataset_url)
        if m:
            ecat_id = m.group(1)
    if not ecat_id and dataset_url:
        m = re.search(r'/(\d+)_\d+_\d+\.zip', dataset_url)
        if m:
            ecat_id = m.group(1)
    if not ecat_id and dataset_url:
        m = re.search(r'/dataset/([^/?#]+)', dataset_url)
        if m and re.fullmatch(r'\d+', m.group(1)):
            ecat_id = m.group(1)
    if not ecat_id and dataset_url:
        m = re.search(r'dataset/ga/([^/?#]+)', dataset_url)
        if m and re.fullmatch(r'\d+', m.group(1)):
            ecat_id = m.group(1)
    # ecat_id = '146111'
    if not ecat_id:
        return {"error": "缺少关键参数，无法解析出内部 eCat ID"}

    csw_search_url = (
        "https://ecat.ga.gov.au/geonetwork/srv/eng/csw"
        "?service=CSW"
        "&version=2.0.2"
        "&request=GetRecords"
        "&resultType=results"
        "&outputSchema=http%3A%2F%2Fwww.isotc211.org%2F2005%2Fgmd"
        "&elementSetName=brief"
        "&typenames=gmd%3AMD_Metadata"
        "&constraintLanguage=CQL_TEXT"
        "&constraint_language_version=1.1.0"
        "&constraint=AnyText%20=%20%27" + ecat_id + "%27"
    )
    csw_resp = self._get_with_retry(csw_search_url)
    csw_text = csw_resp.text if hasattr(csw_resp, 'text') else str(csw_resp)

    if not csw_text:
        return {"error": "CSW 检索返回空报文"}

    uuid = None
    blocks = re.split(r'<gmd:MD_Metadata\b', csw_text)
    for block in blocks[1:]:
        full_block = '<gmd:MD_Metadata' + block
        if ('eCatId/' + ecat_id) in full_block or ('>' + ecat_id + '<') in full_block:
            m = re.search(
                r'<gmd:fileIdentifier>\s*<gco:CharacterString>([^<]+)</gco:CharacterString>'
                r'\s*</gmd:fileIdentifier>',
                full_block,
            )
            if m:
                uuid = m.group(1).strip()
                break
    if not uuid:
        m = re.search(
            r'<gmd:fileIdentifier>\s*<gco:CharacterString>([^<]+)</gco:CharacterString>'
            r'\s*</gmd:fileIdentifier>',
            csw_text,
        )
        if m:
            uuid = m.group(1).strip()

    if not uuid:
        return {"error": "无法通过 CSW 将 eCat ID 映射到 UUID"}

    final_url = (
        "https://ecat.ga.gov.au/geonetwork/srv/api/records/"
        + uuid
        + "/formatters/xml"
    )
    final_resp = self._get_with_retry(final_url, headers={'Accept': 'application/xml'})
    final_text = final_resp.text if hasattr(final_resp, 'text') else str(final_resp)

    if not final_text:
        return {"error": "最终元数据 API 返回空报文"}

    return {
        "source": "Geoscience Australia eCat",
        "format": "xml",
        "data": final_text,
    }
