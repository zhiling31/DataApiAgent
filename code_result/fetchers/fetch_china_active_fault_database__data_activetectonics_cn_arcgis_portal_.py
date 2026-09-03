# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for China Active Fault Database (data.activetectonics.cn ArcGIS Portal)
from code_result.fetcher_decorator import register_api

import re
import json
@register_api(
    publisher="China Active Fault Database (data.activetectonics.cn ArcGIS Portal)",
    aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="AI 初始判定",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_china_active_fault_database__data_activetectonics_cn_arcgis_portal_(self, **kwargs):
    api_url = None
    """获取中国活动断层数据库(CN-faults)的 ArcGIS Portal 原生集合级 XML 元数据。"""
    doi = kwargs.get('doi')
    doi_landing_page = kwargs.get('doi_landing_page')
    dataset_url = kwargs.get('dataset_url')
    dataset_name = kwargs.get('dataset_name')

    item_id = None

    # ----- 路径 1：优先从 URL / DOI 落地页提取 ArcGIS Portal item id -----
    candidate_texts = []
    for raw in (doi_landing_page, dataset_url):
        if isinstance(raw, str) and raw.strip():
            candidate_texts.append(raw)

    id_patterns = [
        r'[?&]id=([0-9a-fA-F]{32})',
        r'/home/item\.html\?id=([0-9a-fA-F]{32})',
        r'/items/([0-9a-fA-F]{32})',
    ]

    for text in candidate_texts:
        for pattern in id_patterns:
            m = re.search(pattern, text)
            if m:
                item_id = m.group(1)
                break
        if item_id:
            break

    # ----- 路径 2：用 DOI 后缀动态构造平台原生 Search 查询，完成 DOI -> item id 映射 -----
    if not item_id and isinstance(doi, str) and doi.strip():
        suffix_m = re.search(r'^10\.\d{4,5}/(.+)$', doi.strip())
        if suffix_m:
            doi_suffix = suffix_m.group(1)
            tokens = [t for t in doi_suffix.split('.') if t]
            alpha_tokens = [t for t in tokens if re.fullmatch(r'[A-Za-z_-]+', t)]
            if alpha_tokens:
                search_words = ' '.join(alpha_tokens[:2])
                years = re.findall(r'(?:19|20)\d{2}', doi_suffix)
                year = years[-1] if years else None

                try:
                    encoded_query = search_words.replace(' ', '%20')
                    search_url = (
                        'http://data.activetectonics.cn/arcportal/sharing/rest/search?q='
                        + encoded_query
                        + '&f=json'
                    )
                    search_resp = self._get_with_retry(
                        search_url, headers={'Accept': 'application/json'}
                    )

                    try:
                        if hasattr(search_resp, 'json'):
                            search_data = search_resp.json()
                        else:
                            search_data = json.loads(
                                getattr(search_resp, 'text', '') or '{}'
                            )
                    except (json.JSONDecodeError, TypeError, ValueError):
                        search_data = {}
                    except Exception:
                        search_data = {}

                    results = search_data.get('results') or []
                    if isinstance(results, list) and results:
                        if year:
                            for result in results:
                                if not isinstance(result, dict):
                                    continue
                                title = str(result.get('title', '') or '')
                                name = str(result.get('name', '') or '')
                                if year in title or year in name:
                                    item_id = result.get('id')
                                    break
                        if not item_id:
                            item_id = results[0].get('id')
                except Exception:
                    item_id = None

    # ----- 路径 3：如有 dataset_name，走平台原生 Search 接口兜底解析 item id -----
    if not item_id and isinstance(dataset_name, str) and dataset_name.strip():
        try:
            encoded_query = dataset_name.strip().replace(' ', '%20')
            search_url = (
                'http://data.activetectonics.cn/arcportal/sharing/rest/search?q='
                + encoded_query
                + '&f=json'
            )
            search_resp = self._get_with_retry(
                search_url, headers={'Accept': 'application/json'}
            )
            try:
                if hasattr(search_resp, 'json'):
                    search_data = search_resp.json()
                else:
                    search_data = json.loads(
                        getattr(search_resp, 'text', '') or '{}'
                    )
            except (json.JSONDecodeError, TypeError, ValueError):
                search_data = {}
            except Exception:
                search_data = {}

            results = search_data.get('results') or []
            if isinstance(results, list) and results:
                item_id = results[0].get('id')
        except Exception:
            item_id = None

    # 防御：参数残缺时宁可不返回元数据，也不编写编造逻辑。
    if not item_id:
        return {'error': '无法从 doi/dataset_url/doi_landing_page/dataset_name 中解析出 ArcGIS Portal 内部 item id', 'api_url': api_url}

    # ----- 最终唯一元数据出口：ArcGIS Portal 原生 itemInfo.xml 端点 -----
    api_url = (
        'http://data.activetectonics.cn/arcportal/sharing/rest/content/items/'
        + item_id
        + '/info/itemInfo.xml'
    )
    response = self._get_with_retry(
        api_url,
        headers={'Accept': 'application/xml, text/xml, */*'},
    )

    if hasattr(response, 'text'):
        raw_text = response.text
    elif hasattr(response, 'content'):
        raw_text = response.content
        if isinstance(raw_text, bytes):
            raw_text = raw_text.decode('utf-8', errors='ignore')
    else:
        raw_text = str(response)

    if raw_text is None or not str(raw_text).strip():
        return {'error': '目标 API 返回了空响应', 'api_url': api_url}

    return {'source': 'China Active Fault Database (ArcGIS Portal itemInfo.xml)', 'format': 'xml', 'data': raw_text, 'api_url': api_url}
