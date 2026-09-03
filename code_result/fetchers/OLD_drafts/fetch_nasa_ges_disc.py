# -*- coding: utf-8 -*-
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="NASA GES DISC",
    aliases=[],
    has_api=False,
    is_reviewed=False,
    auditor_notes="系统判定无API",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_nasa_ges_disc(**kwargs):
    """
    通过 NASA CMR API 获取 GES DISC 数据集的 Collection-level 元数据。
    
    兼容新旧两种 GES DISC URL 格式:
        旧: .../datacollection/GLDAS_NOAH025_M_2.1.html
        新: .../datasets/GLDAS_NOAH025_3H_2.1/summary
    
    入参（由外部系统注入）:
        - doi: 官方 DOI (如 10.5067/E7TYRXPJKWOQ)
        - dataset_url: 数据集原始链接
        - dataset_name: 数据集名称
        - doi_landing_page: DOI 解析落地页
    
    返回:
        dict: {"source": "NASA CMR (GES DISC)", "format": "json", "data": {...}}
    """
    import re
    import json
    import xml.etree.ElementTree as ET
    
    doi = kwargs.get('doi')
    dataset_url = kwargs.get('dataset_url', '')
    dataset_name = kwargs.get('dataset_name', '')
    doi_landing_page = kwargs.get('doi_landing_page', '')
    
    concept_id = None
    
    # =========================================================
    # Path 1: 使用 DOI 在 CMR 中搜索 (最高优先级)
    # =========================================================
    if doi:
        try:
            search_url = f"https://cmr.earthdata.nasa.gov/search/collections?doi={doi}"
            resp = self._get_with_retry(search_url)
            if resp is not None and resp.status_code == 200:
                root = ET.fromstring(resp.text)
                ref = root.find('.//reference')
                if ref is not None:
                    id_elem = ref.find('id')
                    if id_elem is not None and id_elem.text:
                        concept_id = id_elem.text.strip()
        except Exception:
            pass
    
    # =========================================================
    # Path 2: 从 dataset_url / doi_landing_page 中提取标识符
    # 兼容新旧两种 URL 格式
    # =========================================================
    if not concept_id:
        # 收集所有可用于解析的 URL 源
        url_sources = []
        if dataset_url:
            url_sources.append(dataset_url)
        if doi_landing_page and doi_landing_page != dataset_url:
            url_sources.append(doi_landing_page)
        
        for src_url in url_sources:
            if not src_url:
                continue
            
            short_name = None
            full_entry_name = None
            
            # --- 2a: 旧格式 - datacollection/NAME_VERSION.html ---
            try:
                m = re.search(r'datacollection/([A-Za-z0-9_]+?)(?:_\d+\.\d+)?\.html', src_url)
                if not m:
                    # 更宽松的匹配：URL 中以大写字母开头、.html 结尾的片段
                    m = re.search(r'/([A-Z][A-Za-z0-9_]+?)(?:_\d+\.\d+)?\.html', src_url)
                    if m:
                        short_name = m.group(1)
            except Exception:
                pass
            
            # --- 2b: 新格式 - datasets/NAME_VERSION/summary 或 datasets/NAME_VERSION ---
            if not short_name:
                try:
                    m = re.search(r'/datasets/([A-Za-z0-9_]+)', src_url)
                    if m:
                        full_entry_name = m.group(1)
                except Exception:
                    pass
            
            # --- 用 short_name 搜索 (针对旧格式) ---
            if short_name:
                try:
                    search_url = f"https://cmr.earthdata.nasa.gov/search/collections?short_name={short_name}"
                    resp = self._get_with_retry(search_url)
                    if resp is not None and resp.status_code == 200:
                        root = ET.fromstring(resp.text)
                        ref = root.find('.//reference')
                        if ref is not None:
                            id_elem = ref.find('id')
                            if id_elem is not None and id_elem.text:
                                concept_id = id_elem.text.strip()
                except Exception:
                    pass
            
            # --- 用 full_entry_name 作为 keyword 搜索 (针对新格式，含版本号更精确) ---
            if full_entry_name and not concept_id:
                try:
                    search_url = f"https://cmr.earthdata.nasa.gov/search/collections?keyword={full_entry_name}"
                    resp = self._get_with_retry(search_url)
                    if resp is not None and resp.status_code == 200:
                        root = ET.fromstring(resp.text)
                        ref = root.find('.//reference')
                        if ref is not None:
                            id_elem = ref.find('id')
                            if id_elem is not None and id_elem.text:
                                concept_id = id_elem.text.strip()
                except Exception:
                    pass
            
            # 如果找到了就跳出循环
            if concept_id:
                break
    
    # =========================================================
    # Path 3: 使用 dataset_name 作为 keyword 在 CMR 中搜索
    # =========================================================
    if not concept_id and dataset_name:
        try:
            search_url = f"https://cmr.earthdata.nasa.gov/search/collections?keyword={dataset_name}"
            resp = self._get_with_retry(search_url)
            if resp is not None and resp.status_code == 200:
                root = ET.fromstring(resp.text)
                ref = root.find('.//reference')
                if ref is not None:
                    id_elem = ref.find('id')
                    if id_elem is not None and id_elem.text:
                        concept_id = id_elem.text.strip()
        except Exception:
            pass
    
    # =========================================================
    # 如果所有路径都无法解析出 concept_id，返回错误
    # =========================================================
    if not concept_id:
        return {"error": "无法从提供的参数解析出 CMR concept_id，请提供有效的 DOI、dataset_url 或 dataset_name"}
    
    # =========================================================
    # 使用 concept_id 获取完整 UMM JSON 元数据
    # =========================================================
    umm_url = f"https://cmr.earthdata.nasa.gov/search/concepts/{concept_id}.umm_json"
    resp = self._get_with_retry(umm_url)
    
    if resp is None or resp.status_code != 200:
        return {"error": f"获取 UMM JSON 元数据失败，HTTP 状态码: {resp.status_code if resp else 'N/A'}"}
    
    try:
        data = resp.json()
    except json.JSONDecodeError as e:
        return {"error": f"响应无法解析为 JSON: {str(e)}", "raw": resp.text[:500]}
    
    return {
        "source": "NASA CMR (GES DISC)",
        "format": "json",
        "data": data
    }
