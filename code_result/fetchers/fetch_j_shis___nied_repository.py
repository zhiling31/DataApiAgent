# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for J-SHIS / NIED Repository
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="J-SHIS / NIED Repository",
    aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="目前获取的是J-SHIS整个数据平台的元数据，不是J-SHIS里某个数据集的元数据，是日本防灾科学技术研究所 (NIED) 给整个 J-SHIS（日本地震危害信息站）平台颁发的全局引用元数据",
    scope_limit="CATALOG_LEVEL_ONLY"
)
def fetch_j_shis___nied_repository(self, **kwargs):
    api_url = None
    import json
    import re
    import urllib.parse

    doi = kwargs.get("doi") or ""
    doi_landing_page = kwargs.get("doi_landing_page") or ""
    dataset_url = kwargs.get("dataset_url") or ""
    dataset_name = kwargs.get("dataset_name") or ""

    if not (doi or doi_landing_page or dataset_url or dataset_name):
        return {'error': '缺少关键参数，无法解析出内部记录 ID', 'api_url': api_url}

    def _parse_json(resp):
        if isinstance(resp, str):
            try:
                return json.loads(resp)
            except json.JSONDecodeError:
                return resp
        try:
            if hasattr(resp, "json"):
                return resp.json()
        except Exception:
            pass
        text = getattr(resp, "text", None)
        if text is not None:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
        return str(resp)

        

    record_id = None

    # 1) Prefer explicit record id embedded in supplied URLs.
    for candidate in (doi_landing_page, dataset_url):
        if not candidate:
            continue
        m = re.search(r"/records/(\d+)", candidate)
        if m:
            record_id = m.group(1)
            break

    # 2) No embedded record id: resolve it through NIED's own record search API.
    if not record_id:
        doi = (doi or "").strip()
        dataset_name = (dataset_name or "").strip()
        if doi:
            query = doi
        elif dataset_name:
            query = dataset_name
        else:
            return {'error': '缺少关键参数，无法解析出内部记录 ID', 'api_url': api_url}

        if not query:
            return {'error': '缺少关键参数，无法解析出内部记录 ID', 'api_url': api_url}

        search_url = (
            "https://nied-repo.bosai.go.jp/api/records?q="
            + urllib.parse.quote(query, safe="")
        )
        search_resp = self._get_with_retry(search_url)
        search_payload = _parse_json(search_resp)

        if isinstance(search_payload, dict):
            hits = search_payload.get("hits") or {}
            hit_list = hits.get("hits") or []
            if hit_list and isinstance(hit_list, list):
                first_hit = hit_list[0]
                if isinstance(first_hit, dict) and first_hit.get("id") is not None:
                    record_id = str(first_hit.get("id"))

        if not record_id:
            return {'error': '无法从 NIED 仓库检索接口解析出内部记录 ID', 'api_url': api_url}

    api_url = "https://nied-repo.bosai.go.jp/api/records/" + urllib.parse.quote(record_id, safe="")
    resp = self._get_with_retry(api_url)
    return {'source': 'NIED Repository (nied-repo.bosai.go.jp)', 'format': "json", 'data': resp.json(), 'api_url': api_url,"notes":"目前获取的是J-SHIS整个数据平台的元数据，不是J-SHIS里某个数据集的元数据，是日本防灾科学技术研究所 (NIED) 给整个 J-SHIS（日本地震危害信息站）平台颁发的全局引用元数据"}
