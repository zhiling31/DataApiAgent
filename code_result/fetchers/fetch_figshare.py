# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for figshare
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="figshare", aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="人工初始审核",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_figshare(self, **kwargs):

    import urllib
    import re
    import json
    from urllib.parse import quote

    """通过 figshare 官方原生 RESTful API 获取文章/数据集级集合元数据。

    生产环境唯一可靠入参为 kwargs 中的 doi / dataset_url / doi_landing_page / dataset_name。
    代码内部以多态瀑布流方式解析 figshare 内部 article_id：
      1) figshare DOI 尾部数字（形如 10.6084/m9.figshare.<ID>）
      2) figshare 文章落地页 URL（形如 .../articles/dataset/<title>/<ID> 或 .../articles/<ID>）
      3) 通用 URL 尾部数字段兜底
      4) 调用 figshare 公共列表接口按 DOI 反查内部 ID（最后手段）
    最终仅请求一条最优原生元数据 API：
      GET https://api.figshare.com/v2/articles/{article_id}
    """
    doi = kwargs.get('doi')
    dataset_url = kwargs.get('dataset_url')
    doi_landing_page = kwargs.get('doi_landing_page')

    article_id = None

    # --- 多态解析：内部 ID 提取瀑布流 ---
    if doi:
        m = re.search(r'figshare\.(\d+)', doi)
        if m:
            article_id = m.group(1)

    if not article_id and doi_landing_page:
        m = re.search(r'/articles/(?:[^/]+/)*(\d+)', doi_landing_page)
        if m:
            article_id = m.group(1)

    if not article_id and dataset_url:
        m = re.search(r'/(\d+)(?:[/?#]|$)', dataset_url)
        if m:
            article_id = m.group(1)

    if not article_id and doi:
        # figshare 公共列表接口支持按 doi 过滤，用于反查内部 article_id
        try:
            search_url = 'https://api.figshare.com/v2/articles?doi=' + quote(doi, safe='')
            resp = self._get_with_retry(search_url, headers={'Accept': 'application/json'})
            if resp is not None:
                records = resp.json()
                if isinstance(records, list) and len(records) > 0 and isinstance(records[0], dict):
                    found_id = records[0].get('id')
                    if found_id is not None:
                        article_id = str(found_id)
        except Exception:
            article_id = None

    if not article_id:
        return {"error": "缺少关键参数，无法从 DOI/URL 中解析出 figshare article_id"}

    api_url = 'https://api.figshare.com/v2/articles/' + str(article_id)
    resp = self._get_with_retry(api_url, headers={'Accept': 'application/json'})
    if resp is None:
        return {"error": "figshare API 无响应: " + api_url}

    try:
        data = resp.json()
    except (json.JSONDecodeError, ValueError):
        data = None

    if data is None:
        raw_text = resp.text if hasattr(resp, 'text') else ''
        return {"source": "figshare", "format": "text", "data": raw_text}

    return {"source": "figshare", "format": "json", "data": data}
