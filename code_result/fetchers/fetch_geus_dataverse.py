# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for GEUS Dataverse
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="GEUS Dataverse", aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="人工初始审核",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_geus_dataverse(self, **kwargs):
    import re
    import json
    import urllib.parse

    doi = kwargs.get('doi')
    dataset_url = kwargs.get('dataset_url')
    doi_landing_page = kwargs.get('doi_landing_page')

    persistent_id = None

    # ---- 路径 1：由 DOI 构造 persistentId ----
    if doi and isinstance(doi, str):
        d = doi.strip()
        if d:
            d = re.sub(r'^https?://(dx\.)?doi\.org/', '', d, flags=re.IGNORECASE).strip()
        if d:
            if not d.lower().startswith('doi:'):
                d = 'doi:' + d
            persistent_id = d

    # ---- 路径 2：从落地页/下载页 URL 正则提取 persistentId ----
    if not persistent_id:
        for url in (dataset_url, doi_landing_page):
            if url and isinstance(url, str):
                m = re.search(
                    r'persistentId\s*=\s*doi[%3A:]+([^&"\s]+)',
                    url,
                    flags=re.IGNORECASE,
                )
                if m:
                    raw = urllib.parse.unquote(m.group(1)).strip()
                    if raw:
                        if not raw.lower().startswith('doi:'):
                            raw = 'doi:' + raw
                        persistent_id = raw
                        break

    if not persistent_id:
        return {
            "error": "缺少关键参数，无法解析出内部 persistentId（需 doi / dataset_url / doi_landing_page 之一）"
        }

    # Dataverse 原生数据集元数据 API（第一优先级：官方标准 RESTful 接口）
    encoded_pid = urllib.parse.quote(persistent_id, safe='')
    api_url = (
        "https://dataverse.geus.dk/api/datasets/:persistentId/"
        f"?persistentId={encoded_pid}"
    )

    resp = self._get_with_retry(api_url)
    if resp is None:
        return {"error": "请求失败，未获得响应"}

    # 结构化数据绝对透传：JSON 原样返回，绝不二次拆解/清洗
    try:
        data = resp.json()
        return {"source": "GEUS Dataverse", "format": "json", "data": data}
    except (json.JSONDecodeError, AttributeError, ValueError):
        return {"source": "GEUS Dataverse", "format": "text", "data": resp.text}
