# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for Center for Space Research (CSR), The University of Texas at Austin
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="Center for Space Research (CSR), The University of Texas at Austin", aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="人工初始审核",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_center_for_space_research__csr___the_university_of_texas_at_austin(self, **kwargs):
    import re

    doi = kwargs.get('doi') or ''
    dataset_url = kwargs.get('dataset_url') or ''
    doi_landing_page = kwargs.get('doi_landing_page') or ''
    dataset_name = kwargs.get('dataset_name') or ''

    escidoc_id = None

    # 路径 A：从 dataset_url / doi_landing_page / doi 直接提取 escidoc ID
    for text in (dataset_url, doi_landing_page, doi):
        if text:
            m = re.search(r'escidoc[%3A:]\s*(\d+)', text, re.I)
            if m:
                escidoc_id = m.group(1)
                break

    # 路径 B：仅有数据集名称时，从 ICGEM 列表页匹配模型名 -> DOI
    if not escidoc_id and dataset_name:
        list_url = 'https://icgem.gfz-potsdam.de/tom_longtime'
        try:
            r = self._get_with_retry(list_url)
            html = r.text if hasattr(r, 'text') else str(r)
            name_core = re.sub(r'[\s\-_]+', '', dataset_name).upper()
            doi_pattern = re.compile(r'10\.5880/[iI][cC][gG][eE][mM][\d\.]+')
            best_doi = None
            best_dist = 999999
            # 用名称核心词匹配，并在其后窗口内找 DOI
            for m in re.finditer(re.escape(name_core[:20]), html, re.I):
                window = html[m.start():m.start() + 3000]
                dm = doi_pattern.search(window)
                if dm:
                    dist = dm.start()
                    if dist < best_dist:
                        best_dist = dist
                        best_doi = dm.group(0)
            if best_doi:
                try:
                    rr = self._get_with_retry('https://doi.org/' + best_doi)
                    landing_text = rr.text if hasattr(rr, 'text') else str(rr)
                    mm = re.search(r'escidoc[%3A:]\s*(\d+)', landing_text, re.I)
                    if mm:
                        escidoc_id = mm.group(1)
                except Exception:
                    pass
        except Exception:
            pass

    # 路径 C：DOI 或 DOI 落地页 -> 解析 escidoc ID
    if not escidoc_id and (doi or doi_landing_page):
        target = doi_landing_page if doi_landing_page else ('https://doi.org/' + doi)
        try:
            r = self._get_with_retry(target)
            html = r.text if hasattr(r, 'text') else str(r)
            m = re.search(r'escidoc[%3A:]\s*(\d+)', html, re.I)
            if m:
                escidoc_id = m.group(1)
        except Exception:
            pass

    if not escidoc_id:
        return {"error": "缺少关键参数，无法解析出内部 escidoc ID"}

    # 唯一最优原生 API：ISO 19115 XML 元数据
    api_url = ('https://dataservices.gfz-potsdam.de/icgem/download.php'
               '?item=/ir/item/escidoc:' + escidoc_id + '&mdrecord=iso19115')
    r = self._get_with_retry(api_url, headers={'Accept': 'application/xml'})
    raw = r.text if hasattr(r, 'text') else str(r)

    return {"source": "GFZ Data Services (ICGEM)", "format": "xml", "data": raw}
