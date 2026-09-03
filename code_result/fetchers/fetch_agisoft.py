# -*- coding: utf-8 -*-
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="Agisoft",
    aliases=[],
    has_api=False,
    is_reviewed=True,
    auditor_notes="Agisoft 仅为商业摄影测量软件厂商，其 Geoids 页面为静态下载页，提供 GeoTIFF 二进制文件直链，未发现任何元数据导出接口",
    scope_limit="BOTH"
)
def fetch_agisoft(**kwargs):
    return {"error": "KNOWN_NO_API_PLATFORM", "reason": "Agisoft 仅为商业摄影测量软件厂商，其 Geoids 页面为静态下载页，提供 GeoTIFF 二进制文件直链，未发现任何元数据导出接口"}
