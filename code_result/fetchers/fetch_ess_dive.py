# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for ESS-DIVE
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="ESS-DIVE",
    aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="人工精修恢复",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_ess_dive(self, **kwargs):

    import requests
    """从 ESS-DIVE 获取指定 DOI 的公开数据记录"""
    doi = kwargs.get('doi')
    dataset_url = kwargs.get('dataset_url')
    doi_landing_page = kwargs.get('doi_landing_page')
    dataset_name = kwargs.get('dataset_name')
    
    print(f'\n[ESS-DIVE] 正在解析 DOI: {doi}')
    if not doi:
        return {'error': '缺少可供查询的 ESS-DIVE DOI'}
    clean_doi = doi.replace('https://doi.org/', '').replace('http://doi.org/', '')
    solr_q = f'id:"doi:{clean_doi}" OR seriesId:"doi:{clean_doi}" OR identifier:"doi:{clean_doi}"'
    import urllib
    safe_query = urllib.parse.quote(solr_q)
    urls_to_try = [f'https://cn.dataone.org/cn/v2/query/solr/?q={safe_query}&wt=json']
    for url in urls_to_try:
        print(f'   👉 尝试请求 DataONE 全球总枢纽: {url}')
        try:
            headers = {'User-Agent': 'curl/7.88.1', 'Accept': 'application/json'}
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            docs = data.get('response', {}).get('docs', [])
            if docs:
                dataset = docs[0]
                print(f"   ✅ 成功获取到数据集宏观元数据! 标题: {dataset.get('title')}")
                return {
                    "source": "ESS-DIVE",
                    "format": "json",
                    "data": dataset
                }
        except Exception as e:
            print(f'   ⚠️ 节点请求异常或无数据 ({e})，尝试备用方案...')
    print(f'   ⚠️ DataONE 节点未找到匹配的数据集。')
    return None
