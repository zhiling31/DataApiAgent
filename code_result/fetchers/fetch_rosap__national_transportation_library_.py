# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for ROSAP (National Transportation Library)
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="ROSAP (National Transportation Library)", aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="人工初始审核",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_rosap__national_transportation_library_(self, **kwargs):

    import requests
    import re

    # 获取入参
    dataset_url = kwargs.get('dataset_url', '')
    doi_landing_page = kwargs.get('doi_landing_page', '')
    doi = kwargs.get('doi', '')

    # 内部数字ID
    internal_numeric_id = None

    # 瀑布流1: 从 doi_landing_page 正则提取
    if doi_landing_page:
        match = re.search(r'/view/dot/(\d+)', doi_landing_page)
        if match:
            internal_numeric_id = match.group(1)

    # 瀑布流2: 从 dataset_url 正则提取
    if not internal_numeric_id and dataset_url:
        match = re.search(r'/view/dot/(\d+)', dataset_url)
        if match:
            internal_numeric_id = match.group(1)

    # 瀑布流3: 通过DOI解析获取ROSAP落地页URL
    if not internal_numeric_id and doi:
        doi_resolve_url = f'https://doi.org/{doi}'
        try:
            resp = self._get_with_retry(doi_resolve_url, headers={'Accept': 'text/html'})
            # self._get_with_retry 返回的是 requests.Response 对象
            final_url = ''
            if hasattr(resp, 'url'):
                final_url = resp.url
            elif hasattr(resp, 'headers'):
                final_url = resp.headers.get('Location', '')
            if final_url:
                match = re.search(r'/view/dot/(\d+)', final_url)
                if match:
                    internal_numeric_id = match.group(1)
        except Exception:
            pass

    if not internal_numeric_id:
        return {"error": "缺少关键参数，无法解析出内部ID。需要包含 rosap.ntl.bts.gov/view/dot/{id} 格式的URL或有效DOI。"}

    # 构建OAI-PMH identifier: oai:dot.stacks:dot:{numeric_id}
    oai_identifier = f"oai:dot.stacks:dot:{internal_numeric_id}"

    # 请求OAI-PMH GetRecord
    api_url = f"https://rosap.ntl.bts.gov/fedora/oai?verb=GetRecord&identifier={oai_identifier}&metadataPrefix=oai_dc"

    response = self._get_with_retry(api_url)

    return {
        "source": "ROSAP (National Transportation Library)",
        "format": "xml",
        "data": response.text
    }
