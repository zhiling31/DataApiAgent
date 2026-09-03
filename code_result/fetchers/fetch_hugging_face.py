# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for Hugging Face
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="Hugging Face",
    aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="AI 初始判定",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_hugging_face(self, **kwargs):
    """自动生成的抓取方法: Hugging Face
    Fetch collection-level metadata from Hugging Face Datasets Hub API.
    Resolves dataset_id from available inputs using a polymorphic waterfall:
    1. Extract {owner}/{name} from dataset_url via regex
    2. Search by dataset_name via Hugging Face search API
    """
    import re
    import json
    
    dataset_url = kwargs.get('dataset_url', '')
    dataset_name = kwargs.get('dataset_name', '')
    
    dataset_id = None
    
    # --- Polymorphic ID Resolution ---
    # Path 1: Extract owner/dataset_name from dataset_url
    if dataset_url and 'huggingface.co' in dataset_url:
        match = re.search(r'/datasets/([^/]+/[^/?#]+)', dataset_url)
        if match:
            raw_id = match.group(1)
            dataset_id = raw_id.rstrip('/')
    
    # Path 2: Search by dataset_name using HF search API
    if not dataset_id and dataset_name:
        search_url = f'https://huggingface.co/api/datasets?search={dataset_name}&direction=-1&sort=downloads'
        try:
            search_resp = self._get_with_retry(search_url)
            search_data = search_resp.json()
            if search_data and isinstance(search_data, list) and len(search_data) > 0:
                candidate = search_data[0].get('id')
                if candidate:
                    dataset_id = candidate
        except (json.JSONDecodeError, Exception):
            pass
    
    # Guard: if no dataset_id could be resolved, fail gracefully
    if not dataset_id:
        return {"error": "缺少关键参数，无法解析出 Hugging Face dataset ID。请提供 dataset_url 或 dataset_name。"}
    
    # --- Single Optimal API: Hugging Face Datasets Info API ---
    api_url = f'https://huggingface.co/api/datasets/{dataset_id}'
    response = self._get_with_retry(api_url)
    
    # Transparent passthrough: return raw JSON as-is
    return {
        "source": "Hugging Face",
        "format": "json",
        "data": response.json()
    }
