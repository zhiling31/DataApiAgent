# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for AWS Open Data Registry
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="Registry of Open Data on AWS",
    aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="AI 初始判定",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_aws_open_data_registry(self, **kwargs):
    """自动生成的抓取方法: Registry of Open Data on AWS
    Fetch collection-level dataset metadata from Registry of Open Data on AWS (RODA).
    The RODA hosts dataset metadata as YAML files at:
    https://registry.opendata.aws/datasets/awslabs-open-data-registry/datasets/{slug}.yaml
    This function extracts the dataset slug from the provided URL/landing page
    and fetches the corresponding YAML metadata.
    """
    import re
    
    dataset_url = kwargs.get('dataset_url', '')
    doi_landing_page = kwargs.get('doi_landing_page', '')
    dataset_name = kwargs.get('dataset_name', '')
    
    # Step 1: Extract the dataset slug
    slug = None
    
    # Priority 1: Extract from dataset_url (e.g., https://registry.opendata.aws/overture/)
    if dataset_url:
        match = re.search(r'registry\.opendata\.aws/([^/]+)', dataset_url)
        if match:
            slug = match.group(1)
    
    # Priority 2: Extract from doi_landing_page
    if not slug and doi_landing_page:
        match = re.search(r'registry\.opendata\.aws/([^/]+)', doi_landing_page)
        if match:
            slug = match.group(1)
    
    # Priority 3: Derive from dataset_name (lowercase, replace spaces with hyphens)
    if not slug and dataset_name:
        slug = dataset_name.lower().strip()
        slug = re.sub(r'[^a-z0-9]+', '-', slug)
        slug = slug.strip('-')
    
    if not slug:
        return {"error": "无法从提供的参数中解析出 dataset slug，需要 registry.opendata.aws 格式的 URL 或 landing page。"}
    
    # Step 2: Construct the YAML API URL
    api_url = f"https://registry.opendata.aws/datasets/awslabs-open-data-registry/datasets/{slug}.yaml"
    
    # Step 3: Fetch the YAML metadata
    try:
        response = self._get_with_retry(api_url)
        response.raise_for_status()
        yaml_text = response.text
    
        # Validate that we got meaningful YAML (not an HTML error page)
        if not yaml_text or yaml_text.strip().startswith('<!DOCTYPE') or yaml_text.strip().startswith('<html'):
            return {"error": f"API 返回了 HTML 而非 YAML，slug '{slug}' 可能不匹配任何数据集。"}
        
        return {
            "source": "Registry of Open Data on AWS",
            "format": "yaml",
            "data": yaml_text
        }
        
    except Exception as e:
        return {"error": f"请求 YAML API 失败: {str(e)}"}
