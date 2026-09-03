# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for GNS Science Dataset Catalogue
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="GNS Science",
    aliases=["GNS Science Dataset Catalogue"],
    has_api=True,
    is_reviewed=True,
    auditor_notes="AI 初始判定",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_gns_science_dataset_catalogue(self, **kwargs):
    import json
    import re
    import urllib.parse

    dataset_url = (kwargs.get("dataset_url") or "").strip()
    doi = (kwargs.get("doi") or "").strip()
    doi_landing_page = (kwargs.get("doi_landing_page") or "").strip()
    dataset_name = (kwargs.get("dataset_name") or "").strip()

    if not (dataset_url or doi or doi_landing_page or dataset_name):
        return {'error': '缺少必要的入参：dataset_url/doi/doi_landing_page/dataset_name'}

    raw_urls = []
    if dataset_url:
        raw_urls.extend([p.strip() for p in dataset_url.split(';') if p.strip()])
    if doi_landing_page:
        raw_urls.append(doi_landing_page)

    gn_uuid_re = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')
    gn_uuid = None
    for candidate in raw_urls + [doi]:
        if candidate:
            m = gn_uuid_re.search(candidate)
            if m:
                gn_uuid = m.group(0)
                break

    has_gn_metadata = bool(gn_uuid) or any(
        ('data.gns.cri.nz/metadata' in u) or ('metadata/srv' in u) or ('catalog.search#/metadata/' in u)
        for u in raw_urls
    )

    headers = {"Accept": "application/json"}
    ckan_base = "https://catalogue.data.govt.nz"

    def _get_json(url, req_headers=None):
        if req_headers is None:
            req_headers = headers
        try:
            resp = self._get_with_retry(url, headers=req_headers)
        except Exception:
            return None
        text = None
        if isinstance(resp, str):
            text = resp
        elif hasattr(resp, "text"):
            text = resp.text
        if not text:
            return None
        try:
            return json.loads(text)
        except Exception:
            if hasattr(resp, "json"):
                try:
                    return resp.json()
                except Exception:
                    pass
            return None

    def _resolve_ckan_slug(q, fq=None):
        params = {"q": q, "rows": 5}
        if fq:
            params["fq"] = fq
        url = ckan_base + "/api/3/action/package_search?" + urllib.parse.urlencode(params)
        payload = _get_json(url)
        if not payload:
            return None
        search_result = payload.get("result") or {}
        results = search_result.get("results") or []
        if not isinstance(results, list) or len(results) == 0:
            return None
        first = results[0]
        return first.get("name") or first.get("id")

    def _try_old_ckan():
        slug = None
        for candidate in raw_urls:
            match = re.search(r"catalogue\.data\.govt\.nz/dataset/([^/?#]+)", candidate)
            if match:
                slug = match.group(1)
                break

        if not slug and doi:
            doi_clean = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
            doi_clean = re.sub(r"^doi:\s*", "", doi_clean, flags=re.IGNORECASE)
            doi_clean = doi_clean.strip().replace('"', "")
            if doi_clean:
                slug = _resolve_ckan_slug('"{}"'.format(doi_clean), fq="organization:gns-science")

        if not slug and dataset_name:
            title_clean = dataset_name.replace('"', " ").strip()
            if title_clean:
                slug = _resolve_ckan_slug('title:"{}"'.format(title_clean))

        if not slug:
            return {'error': '无法从 doi/dataset_url/dataset_name 解析出 CKAN package_id', 'api_url': None}

        ckan_show_url = ckan_base + "/api/3/action/package_show?" + urllib.parse.urlencode({"id": slug})
        try:
            package_resp = self._get_with_retry(ckan_show_url, headers=headers)
        except Exception as exc:
            return {'error': 'package_show 请求失败: {}'.format(exc), 'api_url': ckan_show_url}

        if isinstance(package_resp, str):
            package_text = package_resp
        elif hasattr(package_resp, "text"):
            package_text = package_resp.text
        else:
            package_text = ""

        if not package_text:
            return {'error': 'package_show 返回空响应', 'api_url': ckan_show_url}

        try:
            package_payload = json.loads(package_text)
        except Exception:
            try:
                package_payload = package_resp.json()
            except Exception as exc:
                return {'error': 'package_show 返回非 JSON 数据: {}'.format(exc), 'format': 'text', 'data': package_text, 'api_url': ckan_show_url}

        if not package_payload or not package_payload.get("success") or not package_payload.get("result"):
            return {'error': 'package_show 调用失败', 'data': package_payload, 'api_url': ckan_show_url}

        return {'source': 'GNS Science / data.govt.nz CKAN', 'format': 'json', 'data': package_payload, 'api_url': ckan_show_url}

    old_result = _try_old_ckan()

    if old_result and old_result.get('format') and not has_gn_metadata:
        return old_result

    if not gn_uuid:
        if old_result:
            return old_result
        return {'error': '旧 CKAN 逻辑未成功；且无法从入参中解析出 GNS GeoNetwork UUID', 'old_error': old_result}

    gn_base = "https://data.gns.cri.nz/metadata/srv"
    xml_url = gn_base + "/api/records/{uuid}/formatters/xml".format(uuid=gn_uuid)
    xml_headers = {"Accept": "application/xml, text/xml, */*"}
    try:
        xml_resp = self._get_with_retry(xml_url, headers=xml_headers)
    except Exception as exc:
        new_error = {'error': 'GNS GeoNetwork formatters/xml 请求失败: {}'.format(exc), 'api_url': xml_url}
        if old_result and old_result.get('format'):
            return old_result
        new_error['old_error'] = old_result
        return new_error

    if isinstance(xml_resp, str):
        xml_text = xml_resp
    elif hasattr(xml_resp, "text"):
        xml_text = xml_resp.text
    else:
        xml_text = ""

    if not xml_text:
        if old_result and old_result.get('format'):
            return old_result
        return {'error': 'GNS GeoNetwork formatters/xml 返回空响应', 'api_url': xml_url, 'old_error': old_result}

    if "<html" in xml_text[:500].lower():
        if old_result and old_result.get('format'):
            return old_result
        return {'error': 'GNS GeoNetwork formatters/xml 返回了 HTML 页面', 'format': 'text', 'data': xml_text, 'api_url': xml_url, 'old_error': old_result}

    return {'source': 'GNS Science GeoNetwork', 'format': 'xml', 'data': xml_text, 'api_url': xml_url}
