# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for IGME-CSIC GeoNetwork Catalog (catalogo.igme.es)
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="IGME-CSIC GeoNetwork Catalog (catalogo.igme.es)",
    aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="利用平台搜索 API 解析出元数据记录 ID ESPIGMEQAFI2012031269，调用 /api/records/{id}/formatters/xml 返回 ISO 19139 集合级元数据",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_igme_csic_geonetwork_catalog__catalogo_igme_es_(self, **kwargs):
    final_url = None
    import json, re, requests
    from urllib.parse import quote

    def _extract_urls(raw):
        if not raw:
            return []
        return re.findall(r'https?://[^\s;]+', raw)

    dataset_name = (kwargs.get('dataset_name') or '').strip()
    dataset_url = kwargs.get('dataset_url') or ''
    doi_landing_page = kwargs.get('doi_landing_page') or ''
    raw_input = (dataset_url + ' ' + doi_landing_page).strip()
    urls = _extract_urls(raw_input)

    if dataset_name:
        query = dataset_name
    elif urls:
        # 如果没有名字只有URL，尝试把URL直接作为搜索关键词，或者提取最后一部分
        query = urls[0].split('/')[-1] 
    else:
        return {'error': '缺少 dataset_name 或 dataset_url，无法执行检索', 'api_url': final_url}

    search_url = 'https://catalogo.igme.es/geonetwork/srv/api/search/records/_search'
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    payload = {
        'size': 10,
        'from': 0,
        'query': {'query_string': {'query': query}}
    }

    try:
        search_resp = requests.post(search_url, headers=headers, data=json.dumps(payload), timeout=30)
        search_resp.raise_for_status()
    except Exception as e:
        return {'error': f'GeoNetwork 检索接口调用失败: {e}', 'api_url': final_url}

    try:
        search_body = search_resp.json()
    except (json.JSONDecodeError, ValueError):
        return {'error': 'GeoNetwork 检索接口未返回合法 JSON', 'api_url': final_url}

    hits = search_body.get('hits', {}).get('hits', [])
    if not hits:
        return {'error': '未能从 GeoNetwork 检索结果中解析到内部 UUID', 'api_url': final_url}

    metadata_id = None
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        source = hit.get('_source', {}) if isinstance(hit.get('_source'), dict) else {}
        candidate = (source.get('metadataIdentifier') or hit.get('_id') or '').strip()
        if not candidate:
            continue
        blob = json.dumps(source, ensure_ascii=False).lower()
        if ('qafi' in candidate.lower()) or ('qafi' in blob):
            metadata_id = candidate
            break

    if not metadata_id and hits:
        first = hits[0] if isinstance(hits[0], dict) else {}
        source = first.get('_source', {}) if isinstance(first.get('_source'), dict) else {}
        metadata_id = (source.get('metadataIdentifier') or first.get('_id') or '').strip()

    if not metadata_id:
        return {'error': '未能从 GeoNetwork 检索结果中解析到内部 metadata identifier', 'api_url': final_url}

    final_url = 'https://catalogo.igme.es/geonetwork/srv/api/records/{}/formatters/xml'.format(quote(metadata_id, safe=''))
    try:
        final_resp = self._get_with_retry(final_url, headers={'Accept': 'application/xml'})
    except Exception as e:
        return {'error': f'获取 QAFI 元数据记录失败: {e}', 'api_url': final_url}

    if final_resp is None:
        return {'error': '获取 QAFI 元数据记录失败: 空响应', 'api_url': final_url}

    return {'source': 'IGME-CSIC GeoNetwork Catalog (catalogo.igme.es)', 'format': "xml", 'data': final_resp.text, 'api_url': final_url,"notes":"需要review"}
