# -*- coding: utf-8 -*-
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="International Service for the Geoid (ISG)",
    aliases=[],
    has_api=False,
    is_reviewed=True,
    auditor_notes="（新数据集需要重新探索）ISG 平台本身没有面向数据集级元数据的开放 RESTful API；ISG与GFZ Data Services合作，ISG负责数据的“业务审核与标准化”，而 GFZ Data Services负责数据的“学术身份认证（分配 DOI）与永久归档” ，\
        但是该条数据在GFZ Data Services中央目录中找到对应记录。原因：对于xGEOID20这类美国国家测地局（NGS/NOAA）、加拿大自然资源部（NRCan）和墨西哥国家统计局（INEGI）三大国家机构联合官方发布的权威数据，ISG 仅仅作为一个全球镜像存储库将其收录，并没有为其重新向 GFZ Data Services 申请注册新的数字对象标识符（DOI）。",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_international_service_for_the_geoid__isg_(**kwargs):
    return {"error": "KNOWN_NO_API_PLATFORM", "reason": "（新数据集需要重新探索）ISG 平台本身没有面向数据集级元数据的开放 RESTful API；ISG与GFZ Data Services合作，ISG负责数据的“业务审核与标准化”，而 GFZ Data Services负责数据的“学术身份认证（分配 DOI）与永久归档” ，但是该条数据在GFZ Data Services中央目录中找到对应记录。原因：对于xGEOID20这类美国国家测地局（NGS/NOAA）、加拿大自然资源部（NRCan）和墨西哥国家统计局（INEGI）三大国家机构联合官方发布的权威数据，ISG 仅仅作为一个全球镜像存储库将其收录，并没有为其重新向 GFZ Data Services 申请注册新的数字对象标识符（DOI）。"}
