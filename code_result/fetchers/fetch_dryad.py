# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for Dryad
from code_result.fetcher_decorator import register_api

import json
import re
import urllib.parse
@register_api(
    publisher="Dryad",
    aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="AI 初始判定",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_dryad(self, **kwargs):
    api_url = None
    """通过 Dryad 官方 REST API v2 获取数据集级元数据。

    生产环境仅可靠传入 doi / dataset_url / doi_landing_page / dataset_name，
    其中 doi 优先级最高；若缺失则尝试从 URL 中正则抽取 Dryad DOI。
    最终请求 https://datadryad.org/api/v2/datasets/{url_encoded_doi}
    并原样透传返回的 JSON。
    """
    doi_raw = (kwargs.get('doi') or '').strip()

    # 瀑布流 1：直接从 doi 参数获取
    if not doi_raw:
        for key in ('doi_landing_page', 'dataset_url'):
            page = kwargs.get(key) or ''
            if not page:
                continue
            # 优先匹配已经 URL 编码的 doi: 形式
            m = re.search(r'doi(?:%3A|:)\s*(10\.\d{4,9}/[^\s;?#&]+)', page, re.IGNORECASE)
            if not m:
                # 退而匹配裸 DOI
                m = re.search(r'(10\.\d{4,9}/[^\s;?#&]+)', page)
            if m:
                doi_raw = m.group(1).strip()
                break

    if not doi_raw:
        return {'error': '缺少关键参数，无法解析出 Dryad DOI', 'api_url': api_url}

    # 归一化为纯 DOI（去掉前缀、结尾标点）
    doi_clean = doi_raw.strip().rstrip('.,;')
    if doi_clean.lower().startswith('doi:'):
        doi_clean = doi_clean[4:].lstrip('/')

    if not doi_clean:
        return {'error': '解析到的 Dryad DOI 为空', 'api_url': api_url}

    # Dryad 官方 API 文档说明：API 中的 DOI 必须 URL 编码。
    # 以官方 self 链接中的 doi: 前缀形式拼接。
    encoded_doi = urllib.parse.quote('doi:' + doi_clean, safe='')
    api_url = 'https://datadryad.org/api/v2/datasets/' + encoded_doi

    headers = {'Accept': 'application/json'}
    resp = self._get_with_retry(api_url, headers=headers)

    # 兼容 requests.Response 或其他返回对象的获取文本方式
    if hasattr(resp, 'text'):
        text = resp.text
    elif isinstance(resp, str):
        text = resp
    else:
        text = str(resp)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return {'source': 'Dryad', 'format': 'json', 'data': text, 'warning': '无法将响应解析为 JSON: {}'.format(exc), 'api_url': api_url}

    return {'source': 'Dryad', 'format': 'json', 'data': data, 'api_url': api_url}
