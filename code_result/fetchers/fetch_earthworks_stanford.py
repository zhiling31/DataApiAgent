# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for EarthWorks Stanford
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="EarthWorks Stanford",
    aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="AI 初始判定",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_earthworks_stanford(self, **kwargs):
    import re
    import json

    # 1. 从可靠的入参中解析 EarthWorks catalog ID（GeoBlacklight ID）。
    #    生产环境通常只注入 dataset_url / doi_landing_page / dataset_name / doi，
    #    因此这里必须做多态解析，并做严格的判空与防御。
    catalog_id = None
    candidate_texts = []
    for key in ('dataset_url', 'doi_landing_page'):
        raw_value = kwargs.get(key)
        if raw_value:
            candidate_texts.append(str(raw_value))

    for text in candidate_texts:
        if text:
            # EarthWorks catalog URL 形态：
            # https://earthworks.stanford.edu/catalog/stanford-yh802fk1065
            match = re.search(r'/catalog/([A-Za-z0-9._-]+)', text)
            if match:
                catalog_id = match.group(1)
                break

    if not catalog_id:
        return {
            "error": (
                "缺少关键参数，无法解析出 EarthWorks catalog ID。"
                "请提供 earthworks.stanford.edu/catalog/<id> 形式的 URL。"
            )
        }

    api_url = "https://earthworks.stanford.edu/catalog/{catalog_id}.json".format(
        catalog_id=catalog_id
    )

    # 2. 使用平台原生的 GeoBlacklight JSON 元数据端点。
    #    该端点返回结构化 JSON，严格按“原汁原味”原则透传。
    response = self._get_with_retry(
        api_url,
        headers={"Accept": "application/json"}
    )

    if getattr(response, "status_code", None) != 200:
        return {
            "error": "EarthWorks API 请求失败，HTTP 状态码: {status}".format(
                status=getattr(response, "status_code", "unknown")
            ),
            "url": api_url,
            "body": getattr(response, "text", ""),
        }

    try:
        data = response.json()
    except (json.JSONDecodeError, ValueError):
        # 正常情况下该 URL 始终返回 JSON；若异常则原样透传文本，绝不让函数崩溃。
        return {
            "error": "结果解析失败"+getattr(response, "text", ""),
            "api_url":api_url
        }

    return {
        "source": "EarthWorks Stanford",
        "format": "json",
        "data": data,
        "api_url":api_url
    }
