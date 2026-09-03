# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for GitHub
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="GitHub",
    aliases=[],
    has_api=True,
    is_reviewed=False,
    auditor_notes="AI 初始判定",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_github(self, **kwargs):
    """自动生成的抓取方法: GitHub"""
    url = "https://api.github.com/repos/{owner}/{repo}"
    params = kwargs.get("extracted_api_params") or {}
    val_owner = params.get("owner") or kwargs.get("dataset_shortname") or kwargs.get("official_website_id") or kwargs.get("owner")
    if not val_owner:
        val_owner = kwargs.get("doi", "").split("/")[-1] if kwargs.get("doi") else ""
    if not val_owner:
        raise ValueError("Missing required parameter: owner")
    url = url.replace("{owner}", str(val_owner))
    val_repo = params.get("repo") or kwargs.get("dataset_shortname") or kwargs.get("official_website_id") or kwargs.get("repo")
    if not val_repo:
        val_repo = kwargs.get("doi", "").split("/")[-1] if kwargs.get("doi") else ""
    if not val_repo:
        raise ValueError("Missing required parameter: repo")
    url = url.replace("{repo}", str(val_repo))
    try:
        response = self._get_with_retry(url, self.headers)
        return {"source": "GitHub-AutoGen", "data": response.json()}
    except Exception as e:
        return {"error": str(e)}
