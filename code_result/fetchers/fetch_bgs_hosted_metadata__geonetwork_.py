# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for BGS Hosted Metadata (GeoNetwork)
from code_result.fetcher_decorator import register_api

import re
@register_api(
    publisher="BGS Hosted Metadata (GeoNetwork)",
    aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="AI 初始判定",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_bgs_hosted_metadata__geonetwork_(self, **kwargs):
    api_url = None
    """从 BGS hosted GeoNetwork 获取 ISO 19139 数据集元数据。

    生产环境仅提供 doi / dataset_url / doi_landing_page / dataset_name 四种入口，
    本函数内部会从中动态解析出 GeoNetwork 内部的记录 UUID，再请求原生 REST API。
    """
    dataset_url = kwargs.get("dataset_url") or ""
    doi_landing_page = kwargs.get("doi_landing_page") or ""
    doi = kwargs.get("doi") or ""
    dataset_name = kwargs.get("dataset_name") or ""

    # 顺序尝试所有可行来源
    candidates = [dataset_url, doi_landing_page, doi, dataset_name]
    record_id = None

    # 路径 1：优先匹配 /records/<uuid> 或 URL 查询串中的 id=<uuid>
    for text in candidates:
        if not text:
            continue
        m = re.search(r"(?:/records/|(?:^|[?&;])id=)([0-9a-fA-F-]{32,40})", text)
        if m:
            record_id = m.group(1).strip()
            break

    # 路径 2：兜底匹配独立的 40 位十六进制 UUID（BGS GeoNetwork 常用格式）
    if not record_id:
        for text in candidates:
            if not text:
                continue
            m = re.search(r"\b([0-9a-fA-F]{40})\b", text)
            if m:
                record_id = m.group(1)
                break

    if not record_id:
        return {'error': '缺少关键参数，无法从输入中解析出 GeoNetwork 内部记录 ID', 'api_url': api_url}

    # 官方原生 GeoNetwork REST API：直接输出 ISO 19139 XML
    api_url = (
        "https://hosted-metadata.bgs.ac.uk/geonetwork/srv/api/records/"
        + record_id
        + "/formatters/xml"
    )
    headers = {"Accept": "application/xml, text/xml, */*;q=0.8"}

    try:
        response = self._get_with_retry(api_url, headers=headers)
        content = getattr(response, "text", None)
        if content is None:
            content = str(response)
        return {'source': 'BGS Hosted Metadata (GeoNetwork)', 'format': 'xml', 'data': content, 'api_url': api_url}
    except Exception as exc:
        return {'error': f'元数据请求失败: {exc}', 'api_url': api_url}
