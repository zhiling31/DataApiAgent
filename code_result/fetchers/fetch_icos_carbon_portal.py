# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for ICOS Carbon Portal
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="ICOS Carbon Portal",
    aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="人工精修恢复",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_icos_carbon_portal(self, **kwargs):
    """处理 ICOS Carbon Portal 复杂的 PID 解析问题"""
    print(f"\n[ICOS Carbon Portal] 开始智能匹配抓取")
    doi = kwargs.get('doi')
    dataset_url = kwargs.get('dataset_url')
    doi_landing_page = kwargs.get('doi_landing_page')
    dataset_name = kwargs.get('dataset_name')
    

    base_url = "https://meta.icos-cp.eu/objects"
    
    if doi:
        print(f"   💡 当前仅有 DOI ({doi})。将尝试通过 ICOS SPARQL 接口解析内部 PID...")
        sparql_url = "https://meta.icos-cp.eu/sparql"
        query = f'''
        PREFIX cpmeta: <http://meta.icos-cp.eu/ontologies/cpmeta/>
        SELECT ?dobj WHERE {{
          ?dobj cpmeta:hasDoi ?doi .
          FILTER (lcase(str(?doi)) = lcase("{doi}"))
        }} LIMIT 1
        '''
        try:
            import requests
            requests.packages.urllib3.disable_warnings()
            custom_headers = self.headers.copy()
            custom_headers["Accept"] = "application/sparql-results+json"
            resp = requests.post(sparql_url, data={'query': query}, headers=custom_headers, verify=False, timeout=15)
            data = resp.json()
            bindings = data.get("results", {}).get("bindings", [])
            if bindings:
                pid_uri = bindings[0].get("dobj", {}).get("value")
                print(f"   ✅ SPARQL 解析成功！找到内部 PID: {pid_uri}")
                if pid_uri:
                    # 请求真实的 JSON 数据
                    json_headers = self.headers.copy()
                    json_headers["Accept"] = "application/json"
                    response = requests.get(pid_uri, headers=json_headers, verify=False, timeout=15)
                    return {
                        "source": "ICOS Carbon Portal",
                        "format": "json",
                        "data": response.json()
                    }
            else:
                print(f"   ⚠️ SPARQL 未找到 DOI ({doi}) 对应的单体数据对象 (可能是 Collection 或是仅在 DataCite 注册)。")
        except Exception as e:
            print(f"   ❌ SPARQL 解析异常: {str(e)}")
            
        return {"error": f"ICOS API 需要内部 PID，且通过 SPARQL 未能通过 DOI ({doi}) 找到对应实体，已交由 DataCite 处理兜底。"}
        
    return {"error": "缺少可供查询的 ICOS PID 或 DOI"}
