# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for USDA NAL GeoData
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="USDA NAL GeoData",
    aliases=[],
    has_api=True,
    is_reviewed=False,
    auditor_notes="AI 初始判定",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_usda_nal_geodata(self, **kwargs):
    """自动生成的抓取方法: USDA NAL GeoData"""
    import re
    import urllib.parse
    
    dataset_name = kwargs.get('dataset_name', '')
    dataset_url = kwargs.get('dataset_url', '')
    
    if not dataset_name and not dataset_url:
        return {"error": "缺少 dataset_name 和 dataset_url 参数，无法解析搜索关键词"}
    
    # Step 1: 确定搜索关键词 (多态解析)
    search_term = None
    if dataset_name:
        cleaned = re.sub(r'\s*\(.*?\)\s*', ' ', dataset_name)
        cleaned = re.sub(r'\b(19|20)\d{2}\b', ' ', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        if cleaned and ('Cropland Data Layer' in cleaned or 'CDL' in cleaned):
            search_term = 'Cropland Data Layer'
        elif cleaned:
            words = cleaned.split()
            search_term = ' '.join(words[:4])
    
    if not search_term and dataset_url:
        if dataset_url and 'croplandcros' in dataset_url.lower():
            search_term = 'Cropland Data Layer'
    
    if not search_term:
        return {"error": "无法从传入参数中提取搜索关键词"}
    
    # Step 2: CSW 搜索获取内部 UUID
    constraint_raw = "\"dc:title\" LIKE '%" + search_term + "%'"
    encoded_constraint = urllib.parse.quote(constraint_raw, safe='')
    csw_url = (
        "https://geodata.nal.usda.gov/geonetwork/srv/eng/csw"
        "?service=CSW&version=2.0.2&request=GetRecords"
        "&resultType=results&elementSetName=full"
        "&typenames=csw:Record"
        "&constraintLanguage=CQL_TEXT&constraint_language_version=1.1.0"
        "&constraint=" + encoded_constraint
    )
    
    try:
        csw_resp = self._get_with_retry(csw_url)
        csw_text = csw_resp if isinstance(csw_resp, str) else csw_resp.text
    except Exception as e:
        return {"error": "CSW搜索请求失败: " + str(e)}
    
    if not csw_text:
        return {"error": "CSW搜索返回空响应"}
    
    # 正则提取第一个 UUID
    uuid = None
    m = re.search(r'([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})', csw_text)
    if m:
        uuid = m.group(1)
    
    if not uuid:
        return {"error": "CSW搜索结果中未找到有效UUID"}
    
    # Step 3: 获取 ISO 19115-3 XML 元数据 (最优原生 API)
    metadata_url = (
        "https://geodata.nal.usda.gov/geonetwork/srv/api/records/"
        + uuid + "/formatters/xml"
    )
    
    try:
        meta_resp = self._get_with_retry(metadata_url)
        meta_text = meta_resp if isinstance(meta_resp, str) else meta_resp.text
    except Exception as e:
        return {"error": "元数据API请求失败: " + str(e)}
    
    if not meta_text:
        return {"error": "元数据API返回空响应"}
    
    return {
        "source": "USDA NAL GeoData (GeoNetwork)",
        "format": "xml",
        "data": meta_text
    }
