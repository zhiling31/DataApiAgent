# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for Zenodo
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="Zenodo", aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="人工初始审核",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_zenodo(self, **kwargs):
    import re

    dataset_url = kwargs.get('dataset_url') or ''
    doi_landing_page = kwargs.get('doi_landing_page') or ''
    doi = kwargs.get('doi') or ''

    record_id = None

    # 路径1：从 dataset_url 提取 record ID（兼容 /records/{id} 或 /record/{id}）
    if dataset_url:
        m = re.search(r'/records?/(\d+)', dataset_url)
        if m:
            record_id = m.group(1)

    # 路径2：从 DOI 解析落地页提取 record ID
    if not record_id and doi_landing_page:
        m = re.search(r'/records?/(\d+)', doi_landing_page)
        if m:
            record_id = m.group(1)

    # 路径3：从 DOI 字符串提取 record ID（10.5281/zenodo.4544550）
    if not record_id and doi:
        m = re.search(r'zenodo[./](\d+)', doi)
        if m:
            record_id = m.group(1)
        else:
            m = re.search(r'(\d{4,})', doi)
            if m:
                record_id = m.group(1)

    if not record_id:
        return {"error": "缺少关键参数，无法解析出 Zenodo 内部记录 ID"}

    api_url = "https://zenodo.org/api/records/" + record_id
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; MetadataHarvester/1.0; +https://example.org/harvester)"
    }

    resp = self._get_with_retry(api_url, headers=headers)

    try:
        data = resp.json()
        return {"source": "Zenodo", "format": "json", "data": data}
    except Exception:
        # 极端情况下服务器未返回合法 JSON，则原样透传文本
        return {"source": "Zenodo", "format": "json", "data": resp.text}
