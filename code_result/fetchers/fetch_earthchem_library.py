# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for EarthChem Library
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="EarthChem Library",
    aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="AI 初始判定",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_earthchem_library(self, **kwargs):
    api_url = None
    import re
    import json

    # 1. 解析 DOI（生产环境优先传入 doi，否则从落地页/原始链接中正则提取）
    doi = (kwargs.get('doi') or '').strip()
    if not doi:
        for key in ('doi_landing_page', 'dataset_url'):
            raw = (kwargs.get(key) or '')
            if raw:
                m = re.search(r'10\.\d{4,9}/[-._;()/:a-zA-Z0-9]+', raw)
                if m:
                    doi = m.group(0)
                    break

    if not doi:
        return {'error': '缺少关键参数，无法解析出 DataONE PID', 'api_url': api_url}

    # 去掉可能存在的 https://doi.org/ 前缀
    doi_clean = re.sub(r'^https?://(dx\.)?doi\.org/', '', doi).strip()
    if not doi_clean:
        return {'error': 'DOI 格式无效', 'api_url': api_url}

    # DataONE 中的 PID 必须形如 doi:10.1594/IEDA/111241
    if doi_clean.startswith('doi:'):
        pid = doi_clean
    else:
        pid = 'doi:' + doi_clean

    api_url = 'https://cn.dataone.org/cn/v2/resolve/' + pid
    headers = {
        'Accept': 'application/ld+json, application/json;q=0.9, */*;q=0.8',
        'User-Agent': 'Mozilla/5.0 (compatible; EarthChemCollectionHarvester/1.0)'
    }

    resp = self._get_with_retry(api_url, headers=headers)
    if resp is None:
        return {'error': 'DataONE 无响应', 'api_url': api_url}

    status_code = getattr(resp, 'status_code', None)
    if status_code is not None and status_code >= 400:
        return {'error': f'DataONE API 请求失败，HTTP {status_code}', 'url': api_url, 'raw': (resp.text or '')[:500], 'api_url': api_url}

    try:
        data = resp.json()
    except Exception:
        raw_text = getattr(resp, 'text', '') or ''
        try:
            import json as _json
            _json.loads(raw_text)
            return {'source': 'DataONE (EarthChem Library Central Catalog)', 'format': 'json', 'data': raw_text, 'api_url': api_url}
        except Exception:
            return {'error': '响应不是合法 JSON，且无法透传为结构化文本', 'raw': raw_text[:500], 'api_url': api_url}

    return {'source': 'DataONE (EarthChem Library Central Catalog)', 'format': 'json', 'data': data, 'api_url': api_url}
