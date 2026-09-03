# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for ICGEM
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="ICGEM", aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="人工初始审核",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_icgem(self, **kwargs):

    import urllib
    import re
    from urllib.parse import quote_plus

    doi = kwargs.get('doi') or ''
    dataset_url = kwargs.get('dataset_url') or ''
    doi_landing_page = kwargs.get('doi_landing_page') or ''
    dataset_name = kwargs.get('dataset_name') or ''

    if not any([doi, dataset_url, doi_landing_page, dataset_name]):
        return {"error": "缺少有效参数"}

    # 若外部未直接提供 DOI，则尝试从原始链接/落地页 URL 中正则提取 DOI
    if not doi:
        m = re.search(r'10\.\d{4,9}/[^\s"\']+', (dataset_url + ' ' + doi_landing_page), re.IGNORECASE)
        if m:
            doi = m.group(0).rstrip(';,.)')
    if not doi:
        return {"error": "缺少 DOI，无法映射内部 OAI 记录 ID"}

    oai_base = 'http://doidb.wdc-terra.org/oaip/oai'
    oai_id = None

    # 第一步：在 DOIDB.ICGEM 集合的 ListRecords 流中，用 DOI 定位内部数字 OAI 标识符
    url = oai_base + '?verb=ListRecords&metadataPrefix=oai_dc&set=DOIDB.ICGEM'
    for _ in range(10):
        try:
            resp = self._get_with_retry(url)
        except Exception:
            break
        text = resp.text
        for block in text.split('<record>'):
            if doi.lower() in block.lower():
                m = re.search(r'<identifier>\s*(oai:[^<\s]+)\s*</identifier>', block)
                if m:
                    oai_id = m.group(1)
                    break
        if oai_id:
            break
        m = re.search(r'<resumptionToken[^>]*>\s*([^<\s]+)\s*</resumptionToken>', text)
        if not m:
            break
        token = m.group(1)
        if not token or token.lower() == 'none':
            break
        url = oai_base + '?verb=ListRecords&resumptionToken=' + quote_plus(token)

    if not oai_id:
        return {"error": "无法在 ICGEM 集合中检索到目标 DOI 对应的内部记录 ID"}

    # 第二步：用定位到的内部 ID 请求 ISO19139 数据集级元数据（唯一最终出口，原样透传）
    final_url = oai_base + '?verb=GetRecord&metadataPrefix=iso19139&identifier=' + quote_plus(oai_id)
    resp = self._get_with_retry(final_url)
    return {
        "source": "GFZ Data Services (ICGEM / DOIDB OAI-PMH)",
        "format": "xml",
        "data": resp.text,
    }
