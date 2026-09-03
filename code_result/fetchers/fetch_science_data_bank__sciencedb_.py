# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for Science Data Bank (ScienceDB)
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="Science Data Bank (ScienceDB)",
    aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="人工精修恢复",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_science_data_bank__sciencedb_(self, **kwargs):

    import requests
    """抓取 Science Data Bank (ScienceDB) (使用官方 Open API)"""
    doi = kwargs.get('doi')
    dataset_url = kwargs.get('dataset_url')
    doi_landing_page = kwargs.get('doi_landing_page')
    dataset_name = kwargs.get('dataset_name')
    
    print(f'\n[ScienceDB] 正在解析 DOI: {doi}')
    if not doi:
        return {'error': '缺少可供查询的 ScienceDB DOI'}
    clean_doi = doi.replace('https://doi.org/', '').replace('http://doi.org/', '')
    api_url = f'https://www.scidb.cn/api/sdb-openapi-service/json?doi={clean_doi}'
    print(f'[ScienceDB] 组装的官方 Open API URL: {api_url}')
    request_headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', 'Accept': 'application/json'}
    try:
        response = requests.get(api_url, headers=request_headers, timeout=15, verify=False)
        response.raise_for_status()
        return {
            "source": "Science Data Bank (ScienceDB)",
            "format": "json",
            "data": response.json()
        }
    except requests.exceptions.HTTPError as e:
        return {'error': f'HTTP错误: {str(e)}', 'details': e.response.text[:200]}
    except requests.exceptions.RequestException as e:
        return {'error': f'网络请求失败: {str(e)}'}
