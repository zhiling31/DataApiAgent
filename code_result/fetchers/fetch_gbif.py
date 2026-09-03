# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for GBIF
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="GBIF",
    aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="无全库级别的元数据接口",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_gbif(self, **kwargs):
    import requests,re
    """
        1. 抓取 GBIF (全球生物多样性信息网络)
        支持直接传入 UUID，或传入 DOI 进行自动映射。
        """
    doi = kwargs.get('doi')
    dataset_url = kwargs.get('dataset_url')
    doi_landing_page = kwargs.get('doi_landing_page')
    dataset_name = kwargs.get('dataset_name')
    
    if not dataset_url:
        m = re.search(r'dataset/([a-fA-F0-9\-]{36})', dataset_url)
        if m:
            identifier = m.group(1)
    if (not doi) or (not identifier):
        return {'error': '缺少可供查询的 GBIF DOI 或 UUID'}

    if doi:
        print('   👉 检测到输入为 DOI，正在通过全局映射接口寻找底层数据集...')
        api_url = f'https://api.gbif.org/v1/dataset/doi/{doi}'
    else:
        api_url = f'https://api.gbif.org/v1/dataset/{identifier}'
    try:
        response = requests.get(api_url, headers=self.headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        if doi:
            results = data.get('results', [])
            if not results:
                print(f'   ⚠️ GBIF 中未找到映射该 DOI ({doi}) 的数据集。')
                return None
            dataset = results[0]
            print(f"   ✅ GBIF DOI 映射成功！底层 UUID 为: {dataset.get('key')}")
        else:
            dataset = data
        print(f"   ✅ GBIF 抓取成功！数据集标题: {dataset.get('title', '未知')}")
        return {
            "source": "GBIF",
            "format": "json",
            "data": dataset
        }
    except Exception as e:
        print(f'   ❌ GBIF 抓取失败: {e}')
        return None
