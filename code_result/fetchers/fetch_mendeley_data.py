# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for Mendeley Data
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="Mendeley Data",
    aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="人工精修恢复",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_mendeley_data(self, **kwargs):

    import time
    """
        抓取 Mendeley Data 
        【核心修正】：使用 Mendeley 正式的 public-api，完美解决旧版获取和数据匹配错误的问题，不再需要网页爬虫。
        """
    doi = kwargs.get('doi')
    dataset_url = kwargs.get('dataset_url')
    doi_landing_page = kwargs.get('doi_landing_page')
    dataset_name = kwargs.get('dataset_name')
    
    print(f'\n[Mendeley Data] 正在解析 DOI: {doi}')
    if not doi:
        return {'error': '缺少可供查询的 Mendeley DOI'}
    clean_doi = doi.replace('https://doi.org/', '').replace('http://doi.org/', '')
    match = re.search('10\\.17632/([^.]+)(?:\\.(\\d+))?', clean_doi)
    if not match:
        print(f'   ❌ 无法从 DOI ({doi}) 中提取 dataset_id。')
        return None
    dataset_id = match.group(1)
    version = match.group(2)
    try:
        from curl_cffi import requests as cf_requests
        api_url = f'https://data.mendeley.com/public-api/datasets/{dataset_id}'
        if version:
            api_url += f'?version={version}'
        print(f'   👉 [官方 API 模式] 请求 Mendeley Data API: {api_url}')
        response = None
        for attempt in range(3):
            try:
                response = cf_requests.get(api_url, impersonate='chrome110', timeout=15)
                if response.status_code in [403, 429, 500, 502, 503, 504]:
                    time.sleep(2 ** attempt)
                    continue
                response.raise_for_status()
                break
            except Exception as req_err:
                if attempt == 2:
                    raise req_err
                time.sleep(2 ** attempt)
        if response:
            data = response.json()
            print(f'   ✅ Mendeley 官方原生 API 抓取成功 (已获取精确版本)！')
            return {
                "source": "Mendeley Data",
                "format": "json",
                "data": data
            }
    except ImportError:
        print(f"   ⚠️ 未安装 curl_cffi 库，无法绕过 Cloudflare。请使用 'pip install curl_cffi' 安装。")
    except Exception as e:
        print(f'   ❌ Mendeley 数据抓取失败: {e}')
