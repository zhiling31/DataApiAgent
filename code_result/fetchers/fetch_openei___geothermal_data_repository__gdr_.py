# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for OpenEI / Geothermal Data Repository (GDR)
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="OpenEI / Geothermal Data Repository (GDR)", aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="人工初始审核",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_openei___geothermal_data_repository__gdr_(self, **kwargs):
    import json
    import re
    import requests
    LOCAL_GDR_DATA_PATH = r'D:\地学\doi\git\code_result\GDR-data.json'

    """抓取 DOE Geothermal Data Repository (OSTI API -> 语义网 JSON-LD 提取)"""
    dataset_url = kwargs.get("dataset_url") or ""
    doi_landing_page = kwargs.get("doi_landing_page") or ""
    dataset_name = kwargs.get("dataset_name") or ""
    doi = kwargs.get("doi") or ""
    gdr_id = None
    osti_data = None
    if dataset_url:
        m = re.search(r'(?<=submissions\/)\d+', dataset_url)
        if m:
            gdr_id = m.group(0)

    if (not gdr_id) and (not doi):
        for candidate in (doi_landing_page, dataset_url, dataset_name):
            if candidate:
                m = re.search(r'10\.\d{4,9}/[^\s"\'<>]+', candidate)
                if m:
                    doi = m.group(0).rstrip('.,;')
                    break

        if not doi:
            return {"error": "缺少关键参数，无法解析出 GDR_ID或者DOI"}

        print(f'\n[DOE GDR] 正在解析 DOI: {doi}')
        match = re.search(r'10\.15121/(\d+)', doi, re.IGNORECASE)
        if not match:
            return {'error': '不是标准的 DOE (OSTI) DOI'}
        osti_id = match.group(1)
        api_url = f'https://www.osti.gov/api/v1/records/{osti_id}'
        print(f'[DOE GDR] 🚀 第一级：请求 DOE 官方 OSTI API 查询真实 ID...')
        request_headers = {'Accept': 'application/json', 'User-Agent': 'curl/7.88.1'}
        response = requests.get(api_url, headers=request_headers, timeout=15)
        response.raise_for_status()
        response_json = response.json()
        osti_data = response_json[0] if isinstance(response_json, list) and len(response_json) > 0 else response_json
        gdr_id = osti_data.get('report_number')
    
    local_data_json_path = LOCAL_GDR_DATA_PATH
    
    try:
        if gdr_id and gdr_id.isdigit():
            print(f'[DOE GDR] 🎯 成功拿到 GDR 内部 ID: {gdr_id}')
            
            dcat_data = None
            print(f'[DOE GDR] 🚀 尝试从本地 {local_data_json_path} 读取 DCAT-US 数据...')
            try:
                with open(local_data_json_path, 'r', encoding='utf-8') as f:
                    local_json = json.load(f)
                    datasets = local_json.get('dataset', []) if isinstance(local_json, dict) else local_json
                    target_id = f"https://gdr.openei.org/submissions/{gdr_id}"
                    for ds in datasets:
                        if ds.get('identifier') == target_id or (ds.get('DOI') and ds.get('DOI').lower() == doi.lower()):
                            dcat_data = ds
                            print(f'[DOE GDR] ✅ 成功从本地匹配到 DCAT-US 数据！')
                            break
                    if not dcat_data:
                        print(f'[DOE GDR] ⚠️ 本地 data.json 未匹配到对应数据集')
            except Exception as local_e:
                print(f'[DOE GDR] ⚠️ 读取本地 data.json 失败: {str(local_e)}')
            
            print(f'[DOE GDR] 🚀 第二级：执行语义网收割 (提取网页端专为机器渲染的 JSON-LD 数据)...')
            gdr_url = f'https://gdr.openei.org/submissions/{gdr_id}'
            html_headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8', 'Accept-Language': 'en-US,en;q=0.5'}
            
            gdr_data = None
            try:
                gdr_res = requests.get(gdr_url, headers=html_headers, timeout=20)
                gdr_res.raise_for_status()
                ld_json_match = re.search('<script[^>]*type=["\\\']application/ld\\+json["\\\'][^>]*>(.*?)</script>', gdr_res.text, re.DOTALL | re.IGNORECASE)
                if ld_json_match:
                    gdr_data = json.loads(ld_json_match.group(1).strip())
                    print('[DOE GDR] ✅ 完美！成功提取标准的 JSON-LD 语义网机器数据！')
                else:
                    print('[DOE GDR] ⚠️ 网页中未包含 JSON-LD 结构化数据。')
            except Exception as fallback_e:
                print(f'[DOE GDR] ❌ JSON-LD 提取失败 ({str(fallback_e)})。')

            if dcat_data or gdr_data:
                final_result = []
                if dcat_data:
                    final_result.append({
                        "source": "Geothermal Data Repository (GDR)-DCAT-US-api",
                        "format": "json",
                        "data": dcat_data
                    })
                if gdr_data:
                    final_result.append({
                        "source": "Geothermal Data Repository (GDR)-submissions-api",
                        "format": "json",
                        "data": gdr_data
                    })
                return final_result
            if osti_data:
                print('[DOE GDR] ⚠️ 仅能返回 OSTI 基础数据。')
                return {'source': 'OSTI-Fallback', 'data': osti_data, 'extracted_gdr_id': gdr_id}
        else:
            if osti_data:
                print('[DOE GDR] ⚠️ OSTI 数据中未包含有效 GDR ID。仅返回 OSTI 基础数据。')
                return {'source': 'OSTI-Fallback', 'data': osti_data}
        return {'error': '未找到有效数据'}
    except Exception as e:
        return {'error': f'请求或解析失败: {str(e)}'}
