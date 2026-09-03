# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for GFZ Data Services
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="GFZ Data Services", aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="人工初始审核",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_gfz_data_services(self, **kwargs):
    import re

    doi = kwargs.get('doi')
    dataset_url = kwargs.get('dataset_url')
    dlp = kwargs.get('doi_landing_page')
    dataset_name = kwargs.get('dataset_name')

    if not any([doi, dataset_url, dlp, dataset_name]):
        return {"error": "缺少关键参数：doi/dataset_url/doi_landing_page/dataset_name 均为空"}

    uuid_pat = re.compile(r'(?:id=|item=)([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})')

    def _extract_uuid(text):
        if not text:
            return None
        m = uuid_pat.search(text)
        return m.group(1) if m else None

    uuid = None

    if dlp:
        uuid = _extract_uuid(dlp)

    if not uuid and dataset_url:
        uuid = _extract_uuid(dataset_url)

    if not uuid and doi:
        try:
            doi_resp = self._get_with_retry('https://doi.org/' + doi.strip())
            uuid = _extract_uuid(getattr(doi_resp, 'text', ''))
        except Exception:
            uuid = None

    if not uuid:
        return {"error": "无法从提供的 DOI/URL 解析出 GFZ panmetaworks 内部数据集 UUID",
                "hint": "需要 doi_landing_page 或 dataset_url 包含 showshort.php?id=<uuid> 格式"}

    api_url = ('https://dataservices.gfz-potsdam.de/panmetaworks/download.php'
               '?item={uuid}&mdrecord=iso19139'.format(uuid=uuid))
    resp = self._get_with_retry(api_url)
    text = getattr(resp, 'text', None) if resp is not None else None
    if not text or not text.strip():
        return {"error": "原生 API 返回了空内容"}

    return {
        "source": "GFZ Data Services",
        "format": "xml",
        "data": text,
        "api_url":api_url
    }
