# -*- coding: utf-8 -*-
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="DigitalOcean Spaces",
    aliases=[],
    has_api=False,
    is_reviewed=True,
    auditor_notes="S3 兼容对象存储服务，3Dflow背后的文件存储后端，未发现任何元数据导出接口",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_digitalocean_spaces(**kwargs):
    return {"error": "KNOWN_NO_API_PLATFORM", "reason": "S3 兼容对象存储服务，3Dflow背后的文件存储后端，未发现任何元数据导出接口"}
