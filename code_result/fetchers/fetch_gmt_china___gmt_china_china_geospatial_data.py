# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for GMT China / gmt-china/china-geospatial-data
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="GMT China / gmt-china/china-geospatial-data",
    aliases=[],
    has_api=False,
    is_reviewed=True,
    auditor_notes="目标页面 docs.gmt-china.org/6.6/dataset/CN-faults/ 是 Sphinx 静态文档页，不含 JSON-LD 或隐藏 API ID。\
        数据实际托管在 GitHub 仓库/Release 中，但 GitHub API 返回的是仓库、文件、目录树或 Release 碎片，均无法提供 CN-faults 数据集的集合级学术元数据。\
            GMT_docs 仓库仅保存文档源文件，无标准 ISO 19139/JSON/XML 元数据导出 API。该平台没有自建的、可返回 CN-faults 集合级元数据的原生 RESTful API，按“宁缺毋滥”原则判定失败。",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_gmt_china___gmt_china_china_geospatial_data(self, **kwargs):
    return {"error": "KNOWN_NO_API_PLATFORM", "reason": "目标页面 docs.gmt-china.org/6.6/dataset/CN-faults/ 是 Sphinx 静态文档页，不含 JSON-LD 或隐藏 API ID。数据实际托管在 GitHub 仓库/Release 中，但 GitHub API 返回的是仓库、文件、目录树或 Release 碎片，均无法提供 CN-faults 数据集的集合级学术元数据。"}
