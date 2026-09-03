# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for LAADS DAAC
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="LAADS DAAC", aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="人工初始审核",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_laads_daac(self, **kwargs):
    import re

    dataset_url = kwargs.get('dataset_url', '')
    doi_landing_page = kwargs.get('doi_landing_page', '')
    dataset_name = kwargs.get('dataset_name', '')

    short_name = None

    # 路径1: 从 dataset_url 提取 short_name
    if dataset_url:
        m = re.search(r'/products/([A-Za-z0-9_-]+)', dataset_url)
        if m:
            short_name = m.group(1)

    # 路径2: 从 doi_landing_page 提取 short_name
    if not short_name and doi_landing_page:
        m = re.search(r'/products/([A-Za-z0-9_-]+)', doi_landing_page)
        if m:
            short_name = m.group(1)

    # 路径3: 直接使用 dataset_name 作为 short_name
    if not short_name and dataset_name:
        short_name = dataset_name.strip()

    if not short_name:
        return {"error": "缺少关键参数，无法解析出产品 short_name。请提供 dataset_url、doi_landing_page 或 dataset_name。"}

    # 使用 CMR UMM-JSON 格式 API 获取集合级元数据
    # CMR 是 NASA EOSDIS 的中央元数据仓库，LAADS DAAC 的所有产品元数据均注册于此
    url = f"https://cmr.earthdata.nasa.gov/search/collections.umm_json?short_name={short_name}"

    response = self._get_with_retry(url)

    return {
        "source": "NASA CMR (LAADS DAAC)",
        "format": "json",
        "data": response.json()
    }
