# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for GNS Science
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="GNS Science",
    aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="GNS 自有 GeoNetwork 元数据端点 data.gns.cri.nz/metadata 在验证时返回 Microsoft 登录 HTML 或 OGC 异常，不可用；\
        但该数据集同时收录于新西兰政府中央开放数据目录 data.govt.nz 的 CKAN 中。通过 CKAN package_search 使用 DOI 短语检索并限定 organization:gns-science，精确定位到 CKAN name=new-zealand-community-fault-model-v1-0；随后 package_show 返回完整数据集级 JSON 元数据\
        备注：不是所有GNS数据都收录在新西兰政府中央开放数据目录 data.govt.nz 的 CKAN 中",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_gns_science(self, **kwargs):
    final_url = None
    import json
    import re
    import urllib.parse

    base_url = "https://catalogue.data.govt.nz"
    headers = {"Accept": "application/json"}

    dataset_url = (kwargs.get("dataset_url") or "").strip()
    doi = (kwargs.get("doi") or "").strip()
    doi_landing_page = (kwargs.get("doi_landing_page") or "").strip()
    dataset_name = (kwargs.get("dataset_name") or "").strip()

    if not (dataset_url or doi or doi_landing_page or dataset_name):
        return {'error': '缺少必要的入参：dataset_url/doi/doi_landing_page/dataset_name', 'api_url': final_url}

    slug = None

    def _get_json(url):
        try:
            resp = self._get_with_retry(url, headers=headers)
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

    def resolve_slug(q, fq=None):
        params = {"q": q, "rows": 5}
        if fq:
            params["fq"] = fq
        url = base_url + "/api/3/action/package_search?" + urllib.parse.urlencode(params)
        payload = _get_json(url)
        print(3333333,url)
        if not payload:
            return None
        search_result = payload.get("result") or {}
        results = search_result.get("results") or []
        if not isinstance(results, list) or len(results) == 0:
            return None
        first = results[0]
        print(2222222222222222,first)
        return first.get("name") or first.get("id")

    # 1) 如果传入的是 data.govt.nz 的 dataset 页面，则直接提取 CKAN slug。
    for candidate_url in (dataset_url, doi_landing_page):
        if candidate_url:
            match = re.search(r"catalogue\.data\.govt\.nz/dataset/([^/?#]+)", candidate_url)
            if match:
                slug = match.group(1)
                break

    # 2) 否则，优先用 DOI 在 GNS Science 的 CKAN 组织下精确检索。
    if not slug and doi:
        doi_clean = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
        doi_clean = re.sub(r"^doi:\s*", "", doi_clean, flags=re.IGNORECASE)
        doi_clean = doi_clean.strip().replace('"', "")
        if doi_clean:
            print(11111111111111111,doi_clean)
            slug = resolve_slug('"{}"'.format(doi_clean), fq="organization:gns-science")

    # 3) 最后使用数据集名称做 CKAN title 短语检索。
    if not slug and dataset_name:
        title_clean = dataset_name.replace('"', " ").strip()
        if title_clean:
            slug = resolve_slug('title:"{}"'.format(title_clean))

    if not slug:
        return {'error': '无法从 doi/dataset_url/dataset_name 解析出 CKAN package_id'}

    final_url = base_url + "/api/3/action/package_show?" + urllib.parse.urlencode({"id": slug})
    try:
        package_resp = self._get_with_retry(final_url, headers=headers)
    except Exception as exc:
        return {'error': 'package_show 请求失败: {}'.format(exc), 'api_url': final_url}

    if isinstance(package_resp, str):
        package_text = package_resp
    elif hasattr(package_resp, "text"):
        package_text = package_resp.text
    else:
        package_text = ""

    if not package_text:
        return {'error': 'package_show 返回空响应', 'api_url': final_url}

    try:
        package_payload = json.loads(package_text)
    except Exception:
        try:
            package_payload = package_resp.json()
        except Exception as exc:
            return {'error': 'package_show 返回非 JSON 数据: {}'.format(exc), 'format': 'text', 'data': package_text, 'api_url': final_url}

    if not package_payload or not package_payload.get("success") or not package_payload.get("result"):
        return {'error': 'package_show 调用失败', 'data': package_payload, 'api_url': final_url}

    return {'source': 'GNS Science / data.govt.nz CKAN', 'format': 'json', 'data': package_payload, 'api_url': final_url}
