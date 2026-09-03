# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for U.S. Geological Survey (USGS)
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="U.S. Geological Survey (USGS)", aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="人工初始审核",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_usgs_(self, **kwargs):
    import re

    dataset_url = kwargs.get('dataset_url') or ''
    doi_landing_page = kwargs.get('doi_landing_page') or ''

    # 入参可能是复合字符串，例如 "落地页url:...;下载页url:..."，先提取出真正的 URL。
    url_re = re.compile(r'https?://[^\s;，,]+')
    candidate_urls = []
    for raw in (dataset_url, doi_landing_page):
        if raw:
            candidate_urls.extend(url_re.findall(raw))

    if not candidate_urls:
        return {"error": "缺少关键参数：无法从入参中解析出任何 URL"}

    pid_re = re.compile(r'USGS[_.]?([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})')

    metadata_uuid = None

    # 1) 先尝试从 URL 字符串本身直接提取 PID。
    for u in candidate_urls:
        m = pid_re.search(u)
        if m:
            metadata_uuid = m.group(1)
            break

    # 2) 否则请求落地页/下载页，从页面源码中提取隐藏 PID。
    if not metadata_uuid:
        for u in candidate_urls:
            try:
                resp = self._get_with_retry(u)
                text = getattr(resp, 'text', None)
                if text is None:
                    text = str(resp)
            except Exception:
                continue
            if text:
                m = pid_re.search(text)
                if m:
                    metadata_uuid = m.group(1)
                    break

    if not metadata_uuid:
        return {"error": "缺少关键参数，无法解析出内部 PID"}

    api_url = "https://data.usgs.gov/datacatalog/metadata/USGS.{}.xml".format(metadata_uuid)
    try:
        resp = self._get_with_retry(api_url)
        text = getattr(resp, 'text', None)
        if text is None:
            text = str(resp)
    except Exception as e:
        return {"error": "USGS Science Data Catalog 元数据 API 请求失败: {}".format(e)}

    return {
        "source": "U.S. Geological Survey Science Data Catalog",
        "format": "xml",
        "data": text
    }
