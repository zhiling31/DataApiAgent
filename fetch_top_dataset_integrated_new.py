import requests
import re
import json
import os
import urllib.parse
import xml.etree.ElementTree as ET
import xmltodict
import time

class IntegratedDataRepoFetcher:
    """
    全网纯正数据存储库 API 抓取聚合工具类。
    整合了 Zenodo, PANGAEA, ScienceDB, DOE GDR, Figshare, ESS-DIVE, LBNL(OSTI+OPTIMADE),
    GBIF, USGS ScienceBase, OpenTopography, Mendeley, 并包含独立的 OSTI 获取。
    """
    
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json"
        }

    def _is_doi(self, identifier: str):
        """简单的辅助方法，判断字符串是否为 DOI 格式"""
        return "10." in identifier and "/" in identifier

    def _clean_doi(self, doi: str):
        return doi.replace("https://doi.org/", "").replace("http://doi.org/", "")

    def _get_with_retry(self, url, headers, max_retries=3):
        """带有重试机制的 HTTP GET 请求。"""
        for attempt in range(max_retries):
            try:
                response = requests.get(url, headers=headers, timeout=15)
                if response.status_code in [403, 429, 500, 502, 503, 504]:
                    if attempt < max_retries - 1:
                        sleep_time = 2 ** attempt
                        print(f"   ⚠️ 遇到 HTTP {response.status_code}，等待 {sleep_time} 秒后重试...")
                        time.sleep(sleep_time)
                        continue
                    else:
                        response.raise_for_status()
                response.raise_for_status()
                return response
            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    sleep_time = 2 ** attempt
                    print(f"   ⚠️ 网络请求异常 ({e})，等待 {sleep_time} 秒后重试...")
                    time.sleep(sleep_time)
                else:
                    raise Exception(f"已达到最大重试次数 ({max_retries})，最终失败: {e}")

    # ==========================================
    # 0. 单独的 OSTI
    # ==========================================
    def fetch_osti(self, doi: str):
        """单独抓取 OSTI 数据"""
        print(f"\n[OSTI] 正在解析 DOI: {doi}")
        clean_doi = self._clean_doi(doi)
        
        osti_id = clean_doi.split('/')[-1]
        api_url = f"https://www.osti.gov/api/v1/records/{osti_id}"
        print(f"[OSTI] 组装的 API URL: {api_url}")
        
        headers = {"Accept": "application/json", "User-Agent": "curl/7.88.1"}
        try:
            response = self._get_with_retry(api_url, headers)
            response_json = response.json()
            osti_data = response_json[0] if isinstance(response_json, list) and len(response_json) > 0 else response_json
            print(f"   ✅ OSTI 抓取成功！标题: {osti_data.get('title', '未知')}")
            return {"source": "OSTI-API", "data": osti_data}
        except Exception as e:
            print(f"   ❌ OSTI 抓取失败: {e}")
            return {"error": str(e)}

    # ==========================================
    # 1. Zenodo
    # ==========================================
    def fetch_zenodo(self, doi: str, access_token: str = None):
        """抓取 Zenodo 数据集 (基于 REST API)"""
        print(f"\n[Zenodo] 正在解析 DOI: {doi}")
        match = re.search(r'zenodo\.(\d+)', doi, re.IGNORECASE)
        if not match:
            return {"error": "不是标准的 Zenodo DOI，无法提取 Record ID"}
        
        record_id = match.group(1)
        api_url = f"https://zenodo.org/api/records/{record_id}"
        print(f"[Zenodo] 组装的 API URL: {api_url}")
        
        request_headers = {"Accept": "application/json"}
        if access_token:
            request_headers["Authorization"] = f"Bearer {access_token}"
            
        try:
            response = self._get_with_retry(api_url, request_headers)
            return {"source": "Zenodo-REST", "data": response.json()}
        except Exception as e:
            return {"error": f"抓取失败: {str(e)}"}

    # ==========================================
    # 14. ICOS Carbon Portal (手写优化版)
    # ==========================================
    def fetch_icos_carbon_portal(self, **kwargs):
        """处理 ICOS Carbon Portal 复杂的 PID 解析问题"""
        print(f"\n[ICOS Carbon Portal] 开始智能匹配抓取")
        params = kwargs.get("extracted_api_params") or {}
        
        object_id = params.get("object_id")
        doi = kwargs.get("doi") or params.get("doi")
        
        base_url = "https://meta.icos-cp.eu/objects"
        
        # 1. 优先尝试直接使用 object_id 请求（无需人造规则判断，直接试探一次）
        if object_id:
            try:
                full_url = f"{base_url}/{object_id}"
                print(f"   👉 尝试直接请求提供的 object_id: {full_url}")
                import requests
                requests.packages.urllib3.disable_warnings()
                custom_headers = self.headers.copy()
                custom_headers["Accept"] = "application/json"
                # 仅试探一次，超时设短一点，如果是错误的 ID 往往直接返回 404
                response = requests.get(full_url, headers=custom_headers, verify=False, timeout=5)
                if response.status_code == 200:
                    print(f"   ✅ object_id 验证成功！")
                    return {"source": "ICOS-Carbon-Portal-Custom", "data": response.json()}
                else:
                    print(f"   ⚠️ object_id ({object_id}) 请求失败 (HTTP {response.status_code})，可能为大模型误提的假 ID。准备尝试回退...")
            except Exception as e:
                print(f"   ⚠️ object_id ({object_id}) 请求异常 ({str(e)})。准备尝试回退...")
        
        # 2. 如果 object_id 失败或者没给，且提供了 DOI，则走 SPARQL 尝试解析
        if doi:
            print(f"   💡 当前仅有 DOI ({doi})。将尝试通过 ICOS SPARQL 接口解析内部 PID...")
            sparql_url = "https://meta.icos-cp.eu/sparql"
            # 清理 DOI
            doi_clean = self._clean_doi(doi)
            query = f'''
            PREFIX cpmeta: <http://meta.icos-cp.eu/ontologies/cpmeta/>
            SELECT ?dobj WHERE {{
              ?dobj cpmeta:hasDoi ?doi .
              FILTER (lcase(str(?doi)) = lcase("{doi_clean}"))
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
                        return {"source": "ICOS-Carbon-Portal-SPARQL", "data": response.json()}
                else:
                    print(f"   ⚠️ SPARQL 未找到 DOI ({doi_clean}) 对应的单体数据对象 (可能是 Collection 或是仅在 DataCite 注册)。")
            except Exception as e:
                print(f"   ❌ SPARQL 解析异常: {str(e)}")
                
            return {"error": f"ICOS API 需要内部 PID，且通过 SPARQL 未能通过 DOI ({doi}) 找到对应实体，已交由 DataCite 处理兜底。"}
            
        return {"error": "缺少可供查询的 ICOS PID 或 DOI"}

    # ==========================================
    # 13. NASA LAADS DAAC (手写优化版)
    # ==========================================
    def fetch_nasa_laads_daac(self, **kwargs):
        """完美适配多种参数组合的 NASA LAADS DAAC 获取方法"""
        print(f"\n[NASA LAADS DAAC] 开始智能匹配抓取")
        params = kwargs.get("extracted_api_params") or {}
        
        # 智能搜集可用参数
        short_name = params.get("short_name") or kwargs.get("dataset_shortname")
        concept_id = params.get("concept_id")
        entry_id = params.get("entry_id")
        doi = kwargs.get("doi") or params.get("doi")
        
        base_url = "https://cmr.earthdata.nasa.gov/search/collections.json"
        query_params = {"provider": "LAADS"}
        
        # 按照优先级组装参数 (CMR 支持精准参数，也支持模糊 keyword)
        if concept_id:
            query_params["concept_id"] = concept_id
        elif short_name:
            query_params["short_name"] = short_name
        elif entry_id:
            query_params["entry_id"] = entry_id
        elif doi:
            query_params["doi"] = self._clean_doi(doi)
        else:
            # 终极兜底，用 keyword 去海搜
            fallback = kwargs.get("official_website_id") or kwargs.get("dataset_shortname")
            if fallback:
                query_params["keyword"] = fallback
            else:
                return {"error": "缺少可供查询的 NASA 参数 (concept_id/short_name/doi 等)"}
                
        try:
            import urllib.parse
            full_url = f"{base_url}?{urllib.parse.urlencode(query_params)}"
            print(f"   👉 实际请求 URL: {full_url}")
            response = self._get_with_retry(full_url, self.headers)
            return {"source": "NASA-LAADS-DAAC-Custom", "data": response.json()}
        except Exception as e:
            return {"error": f"抓取失败: {str(e)}"}

    # ==========================================
    # --- AUTOGENERATED API FETCHERS START ---
    def auto_fetch_zenodo(self, **kwargs):
        """
        Fetch collection-level metadata from Zenodo's native REST API.

        Supports multiple input strategies for resolving the Zenodo record ID:
            1. extracted_api_params['record_id'] — pre-resolved numeric ID
            2. dataset_url — e.g. https://zenodo.org/records/17260370
            3. doi — e.g. 10.5281/zenodo.17260370
            4. dataset_shortname — search by title/name

        Returns:
            dict: {"source": "Zenodo-Custom", "data": <response.json()>} on success
                  {"error": "..."} on failure
        """
        import re

        record_id = None

        # ---- Strategy 1: pre-extracted params ----
        extracted = kwargs.get('extracted_api_params', {})
        if isinstance(extracted, dict):
            candidate = extracted.get('record_id') or extracted.get('id') or extracted.get('recid')
            if candidate:
                record_id = str(candidate)

        # ---- Strategy 2: extract from dataset_url ----
        if not record_id:
            dataset_url = kwargs.get('dataset_url', '')
            if dataset_url:
                # Match Zenodo URL patterns:
                #   https://zenodo.org/records/17260370
                #   https://zenodo.org/record/17260370
                #   https://zenodo.org/api/records/17260370
                m = re.search(r'/records?/(\d+)', dataset_url)
                if m:
                    record_id = m.group(1)

        # ---- Strategy 3: extract from DOI ----
        if not record_id:
            doi = kwargs.get('doi', '')
            if doi:
                # Zenodo DOIs are of the form: 10.5281/zenodo.{record_id}
                # e.g. 10.5281/zenodo.17260370
                m = re.search(r'zenodo[./](\d+)', doi, re.IGNORECASE)
                if m:
                    record_id = m.group(1)

        # ---- Strategy 4: search by dataset name / shortname ----
        if not record_id:
            search_query = (kwargs.get('dataset_shortname', '')
                            or kwargs.get('dataset_name', '')
                            or kwargs.get('title', ''))
            if search_query:
                search_url = 'https://zenodo.org/api/records'
                search_params = {
                    'q': f'title:"{search_query}"',
                    'size': 3,
                }
                try:
                    resp = self._get_with_retry(
                        search_url,
                        params=search_params,
                        headers={'Accept': 'application/json'},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        hits = (data.get('hits', {}).get('hits', [])
                                or data.get('results', [])
                                or [])
                        if hits:
                            record_id = str(hits[0].get('id', ''))
                except Exception:
                    pass  # Fall through to error

        # ---- Execute the primary API call ----
        if not record_id:
            return {
                'error': (
                    'Could not resolve a Zenodo record ID. '
                    'Please provide one of: dataset_url (e.g. https://zenodo.org/records/17260370), '
                    'doi (e.g. 10.5281/zenodo.17260370), '
                    'extracted_api_params["record_id"], or dataset_shortname for search lookup.'
                )
            }

        api_url = f'https://zenodo.org/api/records/{record_id}'
        custom_headers = {'Accept': 'application/json'}

        try:
            response = self._get_with_retry(api_url, headers=custom_headers)
        except Exception as exc:
            return {'error': f'HTTP request failed for Zenodo record {record_id}: {str(exc)}'}

        if response.status_code == 200:
            return {
                'source': 'Zenodo-Custom',
                'data': response.json(),
            }
        elif response.status_code in (401, 403):
            return {
                'error': (
                    f'Zenodo API returned {response.status_code}. '
                    'This record may be restricted or an access token is required.'
                ),
            }
        elif response.status_code == 404:
            return {
                'error': (
                    f'Zenodo record {record_id} not found (404). '
                    'The ID may be invalid or the record has been removed.'
                ),
            }
        else:
            return {
                'error': (
                    f'Zenodo API returned unexpected status {response.status_code} '
                    f'for record {record_id}. Response: {response.text[:300]}'
                ),
            }

    def auto_fetch_bureau_of_transportation_statistics__bts_(self, **kwargs):
        """
        获取 BTS National Transportation Atlas Database (NTAD) 数据集的 ArcGIS REST 元数据。
        需要提供 kwarg 'extracted_api_params' 字典，其中包含键 'service_path'，
        其值为服务相对路径，例如 'BTS/Airports_Large_Hub_2020/MapServer'。
        """
        import json

        # 尝试从多个可能来源获取 service_path
        service_path = None
        if 'extracted_api_params' in kwargs and isinstance(kwargs['extracted_api_params'], dict):
            service_path = kwargs['extracted_api_params'].get('service_path')

        if not service_path:
            service_path = kwargs.get('dataset_shortname')

        if not service_path:
            return {'error': '缺少 service_path 参数。请提供 ArcGIS 服务路径，如 "BTS/Airports_Large_Hub_2020/MapServer"'}

        base_url = 'https://services.arcgis.com/P3ePLMYs2RVChkJx/ArcGIS/rest/services'
        url = f'{base_url}/{service_path}?f=json'

        try:
            resp = self._get_with_retry(url, headers={'Accept': 'application/json'})
            resp.raise_for_status()
            data = resp.json()
            return {'source': 'BTS-NTAD-Custom', 'data': data}
        except Exception as e:
            return {'error': str(e)}

    import re
    import urllib.parse
    from urllib.parse import urlparse


    def auto_fetch_icos_carbon_portal(self, **kwargs):
        """
        Fetch collection-level metadata from ICOS Carbon Portal.

        Strategy (multi-step resolution):
          1. If an ICOS object ID is in the URL or extracted_api_params, use it directly.
          2. If a DOI is provided, resolve it via SPARQL to get object IDs,
             then fetch metadata from the first data object.
          3. If all else fails, return an error.

        Returns:
          {"source": "ICOS-Carbon-Portal-Custom", "data": {...}}
          or {"error": "..."}
        """
        doi = kwargs.get('doi')
        dataset_url = kwargs.get('dataset_url', '')
        dataset_shortname = kwargs.get('dataset_shortname', '')
        extracted_params = kwargs.get('extracted_api_params', {})

        # ------------------------------------------------------------
        # Helper: extract object ID from an ICOS URL like
        #  https://meta.icos-cp.eu/objects/26QlKAL0-2D7QhMZ62n1R9PW
        # ------------------------------------------------------------
        def _extract_icos_object_id(url):
            if not url:
                return None
            # Pattern: /objects/{id} where id is base64url-like
            m = re.search(r'/objects/([A-Za-z0-9_\-]{10,})', url)
            if m:
                return m.group(1)
            # Also try /collections/{id}
            m = re.search(r'/collections/([A-Za-z0-9_\-]{10,})', url)
            if m:
                return m.group(1)
            return None

        # ------------------------------------------------------------
        # Helper: resolve DOI to object IDs via SPARQL
        # ------------------------------------------------------------
        def _resolve_doi_via_sparql(doi_str):
            """Return a list of object URIs that carry this DOI."""
            # Normalise DOI: uppercase and strip whitespace
            doi_normalised = doi_str.strip().upper()
            if doi_normalised.startswith('DOI:'):
                doi_normalised = doi_normalised[4:].strip()
            if doi_normalised.startswith('HTTPS://DOI.ORG/'):
                doi_normalised = doi_normalised[16:]

            sparql_query = (
                'select ?obj where {'
                '?obj <http://meta.icos-cp.eu/ontologies/cpmeta/hasDoi> '
                f'"{doi_normalised}"'
                '}'
            )
            sparql_url = (
                'https://meta.icos-cp.eu/sparql?query='
                + urllib.parse.quote(sparql_query)
            )

            custom_headers = {'Accept': 'application/json'}
            resp = self._get_with_retry(sparql_url, headers=custom_headers)
            if resp is None or resp.status_code != 200:
                return []

            try:
                data = resp.json()
            except Exception:
                return []

            bindings = data.get('results', {}).get('bindings', [])
            uris = []
            for b in bindings:
                uri = b.get('obj', {}).get('value', '')
                if uri:
                    uris.append(uri)
            return uris

        # ------------------------------------------------------------
        # Helper: fetch metadata from a single ICOS object URL
        # ------------------------------------------------------------
        def _fetch_object_metadata(object_id_or_uri):
            """Fetch JSON metadata from /objects/{id} endpoint."""
            # If it's a full URI, extract the ID
            if object_id_or_uri.startswith('http'):
                parsed = urlparse(object_id_or_uri)
                object_id_or_uri = parsed.path.rstrip('/').split('/')[-1]

            api_url = f'https://meta.icos-cp.eu/objects/{object_id_or_uri}'
            custom_headers = {'Accept': 'application/json'}
            resp = self._get_with_retry(api_url, headers=custom_headers)

            if resp is None:
                return None, f"No response from {api_url}"
            if resp.status_code == 404:
                return None, f"Object {object_id_or_uri} not found (404)"
            if resp.status_code in (401, 403):
                return None, f"Authentication required for {api_url} (HTTP {resp.status_code})"
            if resp.status_code == 500:
                return None, f"Server error for {api_url} — may be a collection without objectSpec"
            if resp.status_code != 200:
                return None, f"HTTP {resp.status_code} from {api_url}"

            try:
                return resp.json(), None
            except Exception as e:
                return None, f"Failed to parse JSON from {api_url}: {str(e)}"

        # ------------------------------------------------------------
        # Step 1: Try to derive an object ID directly
        # ------------------------------------------------------------
        icos_object_id = None

        # 1a. From extracted_api_params
        if extracted_params:
            icos_object_id = (
                extracted_params.get('object_id')
                or extracted_params.get('icosId')
                or extracted_params.get('hash')
            )

        # 1b. From dataset_url
        if not icos_object_id and dataset_url:
            icos_object_id = _extract_icos_object_id(dataset_url)

        # If we have a direct object ID, fetch immediately
        if icos_object_id:
            data, err = _fetch_object_metadata(icos_object_id)
            if data:
                return {"source": "ICOS-Carbon-Portal-Custom", "data": data}
            # If direct fetch fails, fall through to DOI resolution

        # ------------------------------------------------------------
        # Step 2: DOI resolution via SPARQL
        # ------------------------------------------------------------
        if doi:
            # Also try from extracted params
            doi_to_use = doi or extracted_params.get('doi')
            if doi_to_use:
                object_uris = _resolve_doi_via_sparql(doi_to_use)
                if object_uris:
                    # Try each URI — prefer DataObject URIs (/objects/) over Collection URIs
                    data_obj_uris = [u for u in object_uris if '/objects/' in u]
                    for uri in (data_obj_uris + object_uris):
                        data, err = _fetch_object_metadata(uri)
                        if data:
                            return {"source": "ICOS-Carbon-Portal-Custom", "data": data}
                    # If all failed, return the last error
                    return {"error": f"DOI {doi_to_use} resolved but all object fetches failed"}
                else:
                    return {"error": f"DOI {doi_to_use} not found in ICOS Carbon Portal SPARQL endpoint"}

        # ------------------------------------------------------------
        # Step 3: Last resort — try SPARQL with short name
        # ------------------------------------------------------------
        if dataset_shortname:
            sparql_query = (
                'prefix dcterms: <http://purl.org/dc/terms/> '
                'select ?obj where {'
                '?obj dcterms:title ?title . '
                f'FILTER(CONTAINS(LCASE(?title), "{dataset_shortname.lower()}"))'
                '} LIMIT 10'
            )
            sparql_url = (
                'https://meta.icos-cp.eu/sparql?query='
                + urllib.parse.quote(sparql_query)
            )
            custom_headers = {'Accept': 'application/json'}
            resp = self._get_with_retry(sparql_url, headers=custom_headers)

            if resp is not None and resp.status_code == 200:
                try:
                    data = resp.json()
                    bindings = data.get('results', {}).get('bindings', [])
                    for b in bindings:
                        uri = b.get('obj', {}).get('value', '')
                        if '/objects/' in uri:
                            result, err = _fetch_object_metadata(uri)
                            if result:
                                return {"source": "ICOS-Carbon-Portal-Custom", "data": result}
                except Exception:
                    pass

        # ------------------------------------------------------------
        # All strategies exhausted
        # ------------------------------------------------------------
        return {
            "error": (
                "Could not fetch ICOS Carbon Portal metadata. "
                "Provide a DOI (e.g., 10.18160/gcp-2025), "
                "an ICOS object URL (https://meta.icos-cp.eu/objects/{id}), "
                "or a dataset shortname."
            )
        }

    def auto_fetch_laads_daac(self, **kwargs):
        """
        LAADS DAAC - 集合级元数据获取
    
        使用 LAADS API-V2 的 /api/v2/measurements/products/{short_name} 端点
        获取产品级元数据。
    
        参数来源：
            - dataset_shortname: 如 "VNP46A2"
            - dataset_url: 如 "https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/VNP46A2/"
    
        返回：
            {"source": "LAADS_DAAC-Custom", "data": {...}}  成功
            {"error": "..."}                                 失败
        """
        import re

        # --- 第1步：提取产品 short_name ---
        short_name = kwargs.get('dataset_shortname', '').strip()
    
        if not short_name:
            dataset_url = kwargs.get('dataset_url', '').strip()
            if dataset_url:
                # 尝试从 URL 路径中提取 short_name
                # 模式: .../products/VNP46A2/ 或 .../products/VNP46A2
                match = re.search(r'/products/([A-Za-z0-9_]+)', dataset_url)
                if match:
                    short_name = match.group(1)
    
        if not short_name:
            # 最后尝试从 extracted_api_params 中获取
            extracted = kwargs.get('extracted_api_params', {})
            short_name = extracted.get('short_name', '').strip()

        if not short_name:
            return {
                "error": (
                    "无法确定产品 short_name。请提供 dataset_shortname（如 'VNP46A2'）"
                    "或 dataset_url（如包含 '/products/VNP46A2' 的 URL）。"
                )
            }

        # --- 第2步：调用 LAADS API-V2 产品元数据端点 ---
        base_url = "https://ladsweb.modaps.eosdis.nasa.gov"
        api_url = f"{base_url}/api/v2/measurements/products/{short_name}"

        custom_headers = {
            "Accept": "application/json",
        }

        try:
            response = self._get_with_retry(api_url, headers=custom_headers)
        except Exception as e:
            return {
                "error": f"请求 LAADS DAAC API 失败: {str(e)}",
                "api_url": api_url,
            }

        # --- 第3步：检查 HTTP 状态码 ---
        status_code = getattr(response, 'status_code', None)
        if status_code is not None:
            if status_code == 401 or status_code == 403:
                return {
                    "error": (
                        f"API 需要鉴权 (HTTP {status_code})。"
                        "产品元数据端点 (/api/v2/measurements/products/) 通常是公开的，"
                        "如果遇到此问题请检查是否被限流。"
                    ),
                    "api_url": api_url,
                    "is_verified": True,
                }
            if status_code == 404:
                return {
                    "error": f"产品 '{short_name}' 在 LAADS DAAC 中未找到 (HTTP 404)。",
                    "api_url": api_url,
                }
            if status_code != 200:
                return {
                    "error": f"LAADS DAAC API 返回 HTTP {status_code}。",
                    "api_url": api_url,
                }

        # --- 第4步：解析 JSON ---
        try:
            data = response.json()
        except Exception as e:
            return {
                "error": f"无法解析 LAADS DAAC API 返回的 JSON: {str(e)}",
                "api_url": api_url,
            }

        # --- 第5步：验证返回结构 ---
        if short_name not in data:
            # 可能 API 返回了不同的包裹结构
            return {
                "source": "LAADS_DAAC-Custom",
                "data": data,
                "note": f"返回的 JSON 中未找到键 '{short_name}'，返回原始响应。",
            }

        product_data = data[short_name]

        # API 不返回 short_name 本身，我们补上
        if isinstance(product_data, dict) and 'short_name' not in product_data:
            product_data['short_name'] = short_name

        return {
            "source": "LAADS_DAAC-Custom",
            "data": product_data,
        }

    def fetch_opentopography(self, identifier: str):
        """
        抓取 OpenTopography (全球高精度地形与激光雷达库)
        """
        print(f"\n[OpenTopography] 正在请求目标: '{identifier}'")
        
        is_doi_mode = self._is_doi(identifier)
        clean_id = self._clean_doi(identifier) if is_doi_mode else identifier
        
        # 官方最新版 Catalog 接口包含了所有数据集的宏观元数据
        print(f"   👉 启动 OpenTopography Catalog 官方全局扫描...")
        api_url = "https://portal.opentopography.org/API/otCatalog?detail=true"
        try:
            response = requests.get(api_url, headers=self.headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            for ds_entry in data.get("Datasets", []):
                dataset = ds_entry.get("Dataset", {})
                
                # 匹配逻辑：
                # 1. 如果传入的是 DOI，去匹配 dataset["url"] (例如: "https://doi.org/10.5069/G99P2ZV5")
                # 2. 如果传入的是内部短名称/UUID，去匹配 alternateName 或 identifier.value
                match_doi = is_doi_mode and clean_id.lower() in dataset.get("url", "").lower()
                match_id = (not is_doi_mode) and (dataset.get("alternateName") == clean_id or dataset.get("identifier", {}).get("value") == clean_id)
                
                if match_doi or match_id:
                    print(f"   ✅ 完美解析！在官方 Catalog 中成功匹配到目标。")
                    print(f"   👉 数据集标题: {dataset.get('name', '未知')}")
                    if match_doi:
                        print(f"   🎯 成功将 DOI 反向映射为官方内部短名称 (shortname): {dataset.get('alternateName')}")
                    return {"source": "OpenTopography-Catalog", "data": dataset}
                    
            print(f"   ⚠️ OT 官方库中未找到匹配项: '{clean_id}'")
            return None
            
        except Exception as e:
            print(f"   ❌ Catalog 接口请求失败: {e}")
            return None

    def fetch_pangaea(self, doi: str):
        """抓取 PANGAEA 数据集 (基于 OAI-PMH API, pan_md格式解析)"""
        print(f'\n[PANGAEA] 正在解析 DOI: {doi}')
        clean_doi = doi.replace('https://doi.org/', '').replace('http://doi.org/', '')
        api_url = f'https://ws.pangaea.de/oai/provider?verb=GetRecord&metadataPrefix=pan_md&identifier=oai:pangaea.de:doi:{clean_doi}'
        print(f'[PANGAEA] 组装的 API URL: {api_url}')
        request_headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        try:
            response = requests.get(api_url, headers=request_headers, timeout=60)
            response.raise_for_status()
            data_dict = xmltodict.parse(response.text, process_namespaces=False)
            core_data = data_dict.get('OAI-PMH', data_dict)
            return {'source': 'PANGAEA-OAI-PMH', 'data': core_data}
        except requests.exceptions.HTTPError as e:
            return {'error': f'HTTP错误: {str(e)}', 'details': e.response.text[:200]}
        except requests.exceptions.RequestException as e:
            return {'error': f'网络请求失败: {str(e)}'}
        except Exception as e:
            return {'error': f'XML 解析或其他失败: {str(e)}'}

    def fetch_sciencedb(self, doi: str):
        """抓取 Science Data Bank (ScienceDB) (使用官方 Open API)"""
        print(f'\n[ScienceDB] 正在解析 DOI: {doi}')
        clean_doi = doi.replace('https://doi.org/', '').replace('http://doi.org/', '')
        api_url = f'https://www.scidb.cn/api/sdb-openapi-service/json?doi={clean_doi}'
        print(f'[ScienceDB] 组装的官方 Open API URL: {api_url}')
        request_headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', 'Accept': 'application/json'}
        try:
            response = requests.get(api_url, headers=request_headers, timeout=15, verify=False)
            response.raise_for_status()
            return {'source': 'ScienceDB-OpenAPI', 'data': response.json()}
        except requests.exceptions.HTTPError as e:
            return {'error': f'HTTP错误: {str(e)}', 'details': e.response.text[:200]}
        except requests.exceptions.RequestException as e:
            return {'error': f'网络请求失败: {str(e)}'}

    def fetch_doe_gdr(self, doi: str):
        """抓取 DOE Geothermal Data Repository (OSTI API -> 语义网 JSON-LD 提取)"""
        print(f'\n[DOE GDR] 正在解析 DOI: {doi}')
        match = re.search('10\\.15121/(\\d+)', doi, re.IGNORECASE)
        if not match:
            return {'error': '不是标准的 DOE (OSTI) DOI'}
        osti_id = match.group(1)
        api_url = f'https://www.osti.gov/api/v1/records/{osti_id}'
        print(f'[DOE GDR] 🚀 第一级：请求 DOE 官方 OSTI API 查询真实 ID...')
        request_headers = {'Accept': 'application/json', 'User-Agent': 'curl/7.88.1'}
        try:
            response = requests.get(api_url, headers=request_headers, timeout=15)
            response.raise_for_status()
            response_json = response.json()
            osti_data = response_json[0] if isinstance(response_json, list) and len(response_json) > 0 else response_json
            gdr_id = osti_data.get('report_number')
            if gdr_id and gdr_id.isdigit():
                print(f'[DOE GDR] 🎯 成功拿到 GDR 内部 ID: {gdr_id}')
                print(f'[DOE GDR] 🚀 第二级：执行语义网收割 (提取网页端专为机器渲染的 JSON-LD 数据)...')
                gdr_url = f'https://gdr.openei.org/submissions/{gdr_id}'
                html_headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8', 'Accept-Language': 'en-US,en;q=0.5'}
                try:
                    gdr_res = requests.get(gdr_url, headers=html_headers, timeout=20)
                    gdr_res.raise_for_status()
                    ld_json_match = re.search('<script[^>]*type=["\\\']application/ld\\+json["\\\'][^>]*>(.*?)</script>', gdr_res.text, re.DOTALL | re.IGNORECASE)
                    if ld_json_match:
                        gdr_data = json.loads(ld_json_match.group(1).strip())
                        print('[DOE GDR] ✅ 完美！成功提取标准的 JSON-LD 语义网机器数据！')
                        return {'source': 'DOE-GDR-JSON-LD', 'data': gdr_data, 'osti_base': osti_data}
                    else:
                        print('[DOE GDR] ⚠️ 网页中未包含 JSON-LD 结构化数据。自动退回使用 OSTI 数据。')
                except Exception as fallback_e:
                    print(f'[DOE GDR] ❌ JSON-LD 提取失败 ({str(fallback_e)})。自动退回使用 OSTI 数据。')
                print('[DOE GDR] ⚠️ 仅能返回 OSTI 基础数据。')
                return {'source': 'OSTI-Fallback', 'data': osti_data, 'extracted_gdr_id': gdr_id}
            else:
                print('[DOE GDR] ⚠️ OSTI 数据中未包含有效 GDR ID。仅返回 OSTI 基础数据。')
                return {'source': 'OSTI-Fallback', 'data': osti_data}
        except Exception as e:
            return {'error': f'请求或解析失败: {str(e)}'}

    def fetch_figshare(self, doi: str):
        """从 Figshare 获取指定 DOI 的文章/数据集元数据"""
        print(f'\n[Figshare] 正在解析 DOI: {doi}')
        match = re.search('figshare\\.(\\d+)', doi, re.IGNORECASE)
        if not match:
            print('❌ 提取失败：这不是一个标准的 Figshare DOI')
            return None
        article_id = match.group(1)
        api_url = f'https://api.figshare.com/v2/articles/{article_id}'
        print(f'   👉 [主通道] 尝试请求原生 REST API: {api_url}')
        request_headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 'Accept': 'application/json'}
        access_token = FIGSHARE_TOKEN
        if access_token:
            request_headers['Authorization'] = f'token {access_token}'
            print('   🔑 已加载 Figshare Access Token 进行授权访问。')
        try:
            response = requests.get(api_url, headers=request_headers, timeout=15)
            response.raise_for_status()
            detail_res = response.json()
            print(f"✅ 成功通过 Figshare 官方 REST API 找到数据集! 标题: {detail_res.get('title')}")
            return {'source': 'Figshare-REST', 'data': detail_res}
        except Exception as e:
            print(f'   ⚠️ REST API 请求失败 ({str(e)})。')
            oai_url = f'https://api.figshare.com/v2/oai?verb=GetRecord&metadataPrefix=mets&identifier=oai:figshare.com:article/{article_id}'
            print(f'   🚀 自动降级并请求 OAI-PMH 官方机器接口 (METS格式): {oai_url}')
            try:
                oai_res = requests.get(oai_url, headers=request_headers, timeout=15)
                oai_res.raise_for_status()
                parsed_xml = xmltodict.parse(oai_res.text, process_namespaces=False)
                title_match = re.search('<[^>]*title[^>]*>(.*?)</[^>]*title>', oai_res.text, re.IGNORECASE)
                title = title_match.group(1) if title_match else '未知标题'
                core_data = parsed_xml.get('OAI-PMH', parsed_xml)
                print(f'✅ 成功通过兜底通道 OAI-PMH 获取到 METS 格式数据！')
                return {'source': 'Figshare-OAI-PMH-METS', 'title': title, 'data': core_data}
            except Exception as fallback_e:
                print(f'❌ OAI-PMH 提取或 XML 解析失败: {fallback_e}')
                return None

    def fetch_ess_dive(self, doi: str):
        """从 ESS-DIVE 获取指定 DOI 的公开数据记录"""
        print(f'\n[ESS-DIVE] 正在解析 DOI: {doi}')
        clean_doi = doi.replace('https://doi.org/', '').replace('http://doi.org/', '')
        solr_q = f'id:"doi:{clean_doi}" OR seriesId:"doi:{clean_doi}" OR identifier:"doi:{clean_doi}"'
        safe_query = urllib.parse.quote(solr_q)
        urls_to_try = [f'https://cn.dataone.org/cn/v2/query/solr/?q={safe_query}&wt=json']
        for url in urls_to_try:
            print(f'   👉 尝试请求 DataONE 全球总枢纽: {url}')
            try:
                headers = {'User-Agent': 'curl/7.88.1', 'Accept': 'application/json'}
                response = requests.get(url, headers=headers, timeout=15)
                response.raise_for_status()
                data = response.json()
                docs = data.get('response', {}).get('docs', [])
                if docs:
                    dataset = docs[0]
                    print(f"   ✅ 成功获取到数据集宏观元数据! 标题: {dataset.get('title')}")
                    return {'source': 'DataONE-CN', 'data': dataset}
            except Exception as e:
                print(f'   ⚠️ 节点请求异常或无数据 ({e})，尝试备用方案...')
        print(f'   ⚠️ DataONE 节点未找到匹配的数据集。')
        return None

    def fetch_gbif(self, identifier: str):
        """
            1. 抓取 GBIF (全球生物多样性信息网络)
            支持直接传入 UUID，或传入 DOI 进行自动映射。
            """
        print(f"\n[GBIF] 正在请求目标: '{identifier}'")
        is_doi_mode = self._is_doi(identifier)
        clean_id = self._clean_doi(identifier) if is_doi_mode else identifier
        if is_doi_mode:
            print('   👉 检测到输入为 DOI，正在通过全局映射接口寻找底层数据集...')
            api_url = f'https://api.gbif.org/v1/dataset?doi={clean_id}'
        else:
            api_url = f'https://api.gbif.org/v1/dataset/{clean_id}'
        try:
            response = requests.get(api_url, headers=self.headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            if is_doi_mode:
                results = data.get('results', [])
                if not results:
                    print(f'   ⚠️ GBIF 中未找到映射该 DOI ({clean_id}) 的数据集。')
                    return None
                dataset = results[0]
                print(f"   ✅ GBIF DOI 映射成功！底层 UUID 为: {dataset.get('key')}")
            else:
                dataset = data
            print(f"   ✅ GBIF 抓取成功！数据集标题: {dataset.get('title', '未知')}")
            return {'source': 'GBIF-REST-API', 'data': dataset}
        except Exception as e:
            print(f'   ❌ GBIF 抓取失败: {e}')
            return None

    def fetch_usgs_sciencebase(self, identifier: str):
        """
            2. 抓取 USGS ScienceBase (美国地质调查局)
            支持直接传入 Item ID，或传入 DOI 进行全局 DataCite 映射，绕过 USGS 自身的残缺搜索。
            """
        print(f"\n[USGS ScienceBase] 正在请求目标: '{identifier}'")
        is_doi_mode = self._is_doi(identifier)
        clean_id = self._clean_doi(identifier) if is_doi_mode else identifier
        if is_doi_mode:
            print('   👉 检测到输入为 DOI，正在通过 DataCite 权威注册局反向映射 USGS 真实 Item ID...')
            try:
                dc_res = requests.get(f'https://api.datacite.org/dois/{clean_id}', timeout=15)
                dc_res.raise_for_status()
                target_url = dc_res.json().get('data', {}).get('attributes', {}).get('url', '')
                item_match = re.search('/catalog/item/([a-zA-Z0-9]+)', target_url)
                if item_match:
                    clean_id = item_match.group(1)
                    print(f'   🎯 成功从 DataCite 提取到 USGS 底层 Item ID: {clean_id}')
                else:
                    print(f'   ⚠️ DataCite 映射失败，URL 中没有包含 Item ID: {target_url}')
                    return None
            except Exception as e:
                print(f'   ❌ DataCite DOI 解析失败: {e}')
                return None
        api_url = f'https://www.sciencebase.gov/catalog/item/{clean_id}?format=json'
        try:
            from curl_cffi import requests as cffi_requests
            response = cffi_requests.get(api_url, headers=self.headers, impersonate='chrome110', timeout=15)
        except ImportError:
            print('   ⚠️ 未安装 curl_cffi，尝试使用标准 requests 可能会被防火墙拦截...')
            response = requests.get(api_url, headers=self.headers, timeout=15)
        try:
            response.raise_for_status()
            dataset = response.json()
            print(f"   ✅ USGS 抓取成功！数据集标题: {dataset.get('title', '未知')}")
            return {'source': 'USGS-ScienceBase-API', 'data': dataset}
        except Exception as e:
            print(f'   ❌ USGS 抓取或解析失败: {e}')
            return None

    def fetch_mendeley(self, doi: str, api_key: str=None):
        """
            抓取 Mendeley Data 
            【核心修正】：使用 Mendeley 正式的 public-api，完美解决旧版获取和数据匹配错误的问题，不再需要网页爬虫。
            """
        print(f'\n[Mendeley Data] 正在解析 DOI: {doi}')
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
                return {'source': 'Mendeley-Public-API', 'data': data}
        except ImportError:
            print(f"   ⚠️ 未安装 curl_cffi 库，无法绕过 Cloudflare。请使用 'pip install curl_cffi' 安装。")
        except Exception as e:
            print(f'   ❌ Mendeley 数据抓取失败: {e}')

    def get_route_map(self):
        """返回动态生成的 API 路由映射"""
        return {
            "LAADS DAAC": self.auto_fetch_laads_daac,
            "Zenodo": self.fetch_zenodo,
            "OSTI": self.fetch_osti,
            "ICOS Carbon Portal": self.fetch_icos_carbon_portal,
            "Bureau of Transportation Statistics (BTS)": self.auto_fetch_bureau_of_transportation_statistics__bts_,
            "OpenTopography": self.fetch_opentopography,
        }

    @staticmethod
    def get_api_schema_desc():
        """返回给大模型用的 API Schema 动态提示词"""
        return """基于官网名称，智能匹配目标API。请按最可能的优先级提供一个匹配列表。**严禁强行凑数！**如果列表中没有任何平台明确、直接地匹配该数据集的官方来源，请务必返回空列表 []。宁可返回空，也不要错误归类：['LAADS DAAC', 'Zenodo', 'OSTI', 'ICOS Carbon Portal', 'Bureau of Transportation Statistics (BTS)']"""
    # --- AUTOGENERATED API FETCHERS END ---
    # ==========================================

# ==========================================
# 批量处理与断点续传逻辑
# ==========================================
def process_batch_data(input_file: str, output_file: str):
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    fetcher = IntegratedDataRepoFetcher()
    
    publisher_route_map = {
        "doe geothermal data repository": fetcher.fetch_doe_gdr,
        "pangaea": fetcher.fetch_pangaea,
        "zenodo": fetcher.fetch_zenodo,
        "science data bank": fetcher.fetch_sciencedb,
        "environmental system science data infrastructure for a virtual ecosystem": fetcher.fetch_ess_dive,
        "Watershed Function SFA": fetcher.fetch_ess_dive,
        "Watershed Functionality Scientific Focus Area": fetcher.fetch_ess_dive,
        "Next Generation Ecosystems Experiment - Arctic, Oak Ridge National Laboratory (ORNL), Oak Ridge, TN (US)": fetcher.fetch_ess_dive,
        "Carbon Dioxide Information Analysis Center (CDIAC), Oak Ridge National Laboratory (ORNL), Oak Ridge, TN (United States)": fetcher.fetch_ess_dive,
        "Groundwater Quality SFA": fetcher.fetch_ess_dive,
        "Incorporating the Hydrological Controls on Carbon Cycling in Floodplain Ecosystems into Earth System Models (ESMs)": fetcher.fetch_ess_dive,
        "lawrence livermore national laboratory": fetcher.fetch_osti,
        "lawrence berkeley national laboratory": fetcher.fetch_osti,
        "figshare": fetcher.fetch_figshare,
        "GBIF Secretariat": fetcher.fetch_gbif,
        "U.S. Geological Survey": fetcher.fetch_usgs_sciencebase,
        "sciencebase": fetcher.fetch_usgs_sciencebase,
        "OpenTopography": fetcher.fetch_opentopography,
        "Mendeley": fetcher.fetch_mendeley,
        "LBNL Materials Project": fetcher.fetch_osti,
        "emn-h2awsm": fetcher.fetch_osti,
        "osti": fetcher.fetch_osti,
        "Geological Society of America":fetcher.fetch_figshare,
    }


    if not os.path.exists(input_file):
        print(f"❌ 输入文件 {input_file} 不存在，请检查路径。")
        return

    with open(input_file, 'r', encoding='utf-8') as f:
        try:
            input_data = json.load(f)
        except json.JSONDecodeError:
            print(f"❌ 输入文件 {input_file} 不是合法的 JSON 格式。")
            return

    processed_records = []
    processed_ids = set()
    
    if os.path.exists(output_file):
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                processed_records = json.load(f)
                for record in processed_records:
                    unique_id = f"{record.get('datanet_id', '')}_{record.get('doi', '')}"
                    processed_ids.add(unique_id)
            print(f"🔄 检测到历史输出文件，已成功加载 {len(processed_ids)} 条历史记录，准备执行断点续传。")
        except json.JSONDecodeError:
            print(f"⚠️ 输出文件 {output_file} 格式破损，将以空缓存重新生成。")

    unmatched_file = output_file.replace(".json", "_unmatched.json")
    unmatched_records = {}
    if os.path.exists(unmatched_file):
        try:
            with open(unmatched_file, 'r', encoding='utf-8') as f:
                for err in json.load(f):
                    uid = f"{err.get('datanet_id', '')}_{err.get('doi', '')}"
                    unmatched_records[uid] = err
        except: pass

    api_errors_file = output_file.replace(".json", "_api_errors.json")
    api_error_records = {}
    if os.path.exists(api_errors_file):
        try:
            with open(api_errors_file, 'r', encoding='utf-8') as f:
                for err in json.load(f):
                    uid = f"{err.get('datanet_id', '')}_{err.get('doi', '')}"
                    api_error_records[uid] = err
        except: pass
    # 仅保留 data_repositories 类型的数据
    input_data = [entry for entry in input_data if entry.get("doi_type", "") == "data_repositories"]

    print(f"\n🚀 开始处理批量数据集，总计待处理数量: {len(input_data)}\n")
    new_success_count = 0
    for entry in input_data:
        datanet_id = str(entry.get("datanet_id", ""))
        doi = entry.get("doi", "")
        unique_id = f"{datanet_id}_{doi}"

        if unique_id in processed_ids:
            print(f"⏭️ [跳过] {unique_id} - 此记录在历史缓存中已处理成功。")
            continue

        metadata = entry.get("metadata", {})
        publisher_str = metadata.get("publisher", "")
        
        if not publisher_str:
            continue
            
        publishers = [p.strip().lower() for p in publisher_str.split(";") if p.strip()]
        
        methods_to_try = []
        seen_methods = set()
        
        for pub in publishers:
            for route_key, method in publisher_route_map.items():
                if route_key.lower() in pub:
                    if method not in seen_methods:
                        seen_methods.add(method)
                        methods_to_try.append((route_key, method))
                    break
                
        if not methods_to_try:
            print(f"⚠️ DOI: {doi} - 无法匹配到任何已知 API。")
            unmatched_records[unique_id] = {
                "datanet_id": datanet_id,
                "ddename": entry.get("ddename", ""),
                "doi": doi,
                "publisher_str": publisher_str
            }
            with open(unmatched_file, 'w', encoding='utf-8') as f:
                json.dump(list(unmatched_records.values()), f, ensure_ascii=False, indent=2)
            continue
            
        print(f"\n======================================")
        print(f"🔍 DOI: {doi} - 找到 {len(methods_to_try)} 个不同的候选 API")
        
        success = False
        api_error_msgs = []
        for matched_publisher_name, matched_method in methods_to_try:
            print(f"🎯 尝试命中目标：{matched_publisher_name.upper()} (DOI: {doi})")
            
            try:
                result = matched_method(doi)
                
                if result and isinstance(result, dict) and "error" not in result:
                    source_val = result.get("source", matched_publisher_name.upper())
                    
                    metadata_content = result.get("data", result)
                    
                    # 只要是字符串类型，就认为是未解析的原始文本（如 XML），直接存文件
                    if isinstance(metadata_content, str):
                        xml_filename = f"{datanet_id}.xml"
                        xml_filepath = os.path.join(os.path.dirname(output_file), xml_filename)
                        with open(xml_filepath, 'w', encoding='utf-8') as xf:
                            xf.write(metadata_content)
                        metadata_value = xml_filename
                    else:
                        metadata_value = metadata_content

                    final_entry = {
                        "datanet_id": datanet_id,
                        "ddename": entry.get("ddename", ""),
                        "doi_type": entry.get("doi_type", ""),
                        "doi": doi,
                        "source_api": source_val,
                        "metadata": metadata_value
                    }
                    
                    processed_records.append(final_entry)
                    processed_ids.add(unique_id)
                    new_success_count += 1
                    
                    if unique_id in unmatched_records:
                        del unmatched_records[unique_id]
                        with open(unmatched_file, 'w', encoding='utf-8') as ef:
                            json.dump(list(unmatched_records.values()), ef, ensure_ascii=False, indent=2)
                            
                    if unique_id in api_error_records:
                        del api_error_records[unique_id]
                        with open(api_errors_file, 'w', encoding='utf-8') as ef:
                            json.dump(list(api_error_records.values()), ef, ensure_ascii=False, indent=2)

                    with open(output_file, 'w', encoding='utf-8') as f:
                        json.dump(processed_records, f, ensure_ascii=False, indent=2)
                    
                    print(f"✅ 抓取并保存成功！(API: {source_val}, 共 {new_success_count} 条新增)")
                    success = True
                    # 取消了 break，允许程序继续尝试下一个不同的 API
                else:
                    msg = f"抓取或解析失败/无数据。错误信息: {result}"
                    print(f"❌ {msg}")
                    api_error_msgs.append(f"{matched_publisher_name}: {msg}")
                    
            except Exception as e:
                msg = f"调用过程中发生系统异常: {e}"
                print(f"❌ {msg}")
                api_error_msgs.append(f"{matched_publisher_name}: {msg}")
                
        if not success:
            print(f"⚠️ 所有匹配的API均未能成功获取数据，已记录到API失败文件。")
            api_error_records[unique_id] = {
                "datanet_id": datanet_id,
                "ddename": entry.get("ddename", ""),
                "doi": doi,
                "publisher_str": publisher_str,
                "errors": api_error_msgs
            }
            with open(api_errors_file, 'w', encoding='utf-8') as ef:
                json.dump(list(api_error_records.values()), ef, ensure_ascii=False, indent=2)

    print(f"\n🎉 批量处理流程结束！本次新增成功提取了 {new_success_count} 条记录。结果已保存至 {output_file}。")

if __name__ == "__main__":
    input_file_path = "meta_results/doi_org_full_metadata.json"
    output_file_path = "meta_results/output_merged_resultsnew.json"
    process_batch_data(input_file_path, output_file_path)
