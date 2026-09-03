# -*- coding: utf-8 -*-
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="NASA Goddard Space Flight Center (earth.gsfc.nasa.gov)",
    aliases=[],
    has_api=False,
    is_reviewed=True,
    auditor_notes="虽然GSFC、JPL 和 CSR 同属于NASA产品，但是JPL 和 CSR的 Mascons直接托管在 PO.DAAC 的数据库和网站上供全球下载，\
        而GSFC 的 Mascons：是由 GSFC 测地学实验室开发的一套独立算法产品。GSFC 选择将这套特殊的产品直接托管在他们自己的机构网站上，而没有统一放到 PO.DAAC 的目录中，故未找到元数据,testcase:https://earth.gsfc.nasa.gov/geo/data/grace-mascons",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_nasa_goddard_space_flight_center__earth_gsfc_nasa_gov_(**kwargs):
    return {"error": "KNOWN_NO_API_PLATFORM", "reason": "虽然GSFC、JPL 和 CSR 同属于NASA产品，但是JPL 和 CSR的 Mascons直接托管在 PO.DAAC 的数据库和网站上供全球下载，\
        而GSFC 的 Mascons：是由 GSFC 测地学实验室开发的一套独立算法产品。GSFC 选择将这套特殊的产品直接托管在他们自己的机构网站上，而没有统一放到 PO.DAAC 的目录中，故未找到元数据,testcase:https://earth.gsfc.nasa.gov/geo/data/grace-mascons"}
