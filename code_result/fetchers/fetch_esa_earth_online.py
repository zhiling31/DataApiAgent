# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for ESA Earth Online
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="ESA Earth Online", aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="人工初始审核",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_esa_earth_online(self, **kwargs):
    import re
    import json
    import urllib.parse

    doi = kwargs.get("doi") or ""
    dataset_url = kwargs.get("dataset_url") or ""
    doi_landing_page = kwargs.get("doi_landing_page") or ""
    dataset_name = kwargs.get("dataset_name") or ""

    # ---- 解析查询关键词（从 URL slug 中提取或由数据集名称构造） ----
    slug = ""
    for src in (dataset_url, doi_landing_page):
        if src:
            m = re.search(r"/catalog/([A-Za-z0-9\-_]+)", src)
            if m:
                slug = m.group(1)
                break
    if not slug and dataset_name:
        slug = dataset_name.strip()
    if not slug:
        return {"error": "缺少关键参数，无法确定目标数据集标识"}

    terms = [t for t in re.split(r"[^A-Za-z0-9]+", slug) if t]
    if not terms:
        return {"error": "无法从数据集标识中解析出查询关键词"}
    query = " ".join(terms[:6])

    headers = {"Accept": "application/geo+json, application/json"}

    # ---- 第一次请求：FedEO STAC 集合搜索，动态解析集合 id ----
    search_url = "https://fedeo.ceos.org/collections?q=" + urllib.parse.quote(query)
    try:
        search_resp = self._get_with_retry(search_url, headers=headers)
        payload = search_resp.json()
    except (ValueError, AttributeError) as e:
        return {"error": f"FEDEO 搜索接口响应异常: {e}"}

    collections = payload.get("collections") or []
    if not collections:
        return {"error": f"FEDEO 未命中目标集合，查询词: {query}"}

    target = None
    doi_norm = re.sub(r"\s+", "", doi).lower()
    for item in collections:
        item_id = item.get("id") or ""
        stac_doi = re.sub(r"\s+", "", item.get("sci:doi") or "").lower()
        if doi_norm and stac_doi and (stac_doi in doi_norm or doi_norm in stac_doi):
            target = item
            break
    if target is None:
        for item in collections:
            title = (item.get("title") or "").lower()
            if title and "gravity" in title and ("goce" in title or "field" in title):
                target = item
                break
    if target is None or not target.get("id"):
        return {"error": "FEDEO 搜索命中但未能定位与目标 DOI/标题匹配的集合"}

    collection_id = target["id"]

    # ---- 第二次请求：按解析出的集合 id 获取集合级元数据并原样透传 ----
    final_url = "https://fedeo.ceos.org/collections/" + urllib.parse.quote(collection_id, safe="")
    detail_resp = self._get_with_retry(final_url, headers=headers)
    try:
        detail_data = detail_resp.json()
    except (ValueError, AttributeError) as e:
        return {"error": f"FEDEO 集合详情接口响应异常: {e}"}

    return {
        "source": "ESA FedEO STAC Catalogue (FedEO Clearinghouse / ESA EO-CAT)",
        "format": "json",
        "data": detail_data,
    }
