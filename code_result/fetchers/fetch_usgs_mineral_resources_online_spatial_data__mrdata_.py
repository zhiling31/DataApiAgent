# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for U.S. Geological Survey (USGS) - Mineral Resources Online Spatial Data (MRData)
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="U.S. Geological Survey (USGS) - Mineral Resources Online Spatial Data (MRData)",
    aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="人工精修恢复",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_usgs_mineral_resources_online_spatial_data__mrdata_(self, **kwargs):
    import json
    import requests
    import re

    dataset_url = kwargs.get('dataset_url', '')
    doi_landing_page = kwargs.get('doi_landing_page', '')
    cite_id = None
    candidates = []

    if dataset_url:
        candidates.extend([u.strip() for u in dataset_url.split(';') if u and u.strip()])
    if doi_landing_page:
        candidates.extend([u.strip() for u in doi_landing_page.split(';') if u and u.strip()])

    # ---- Step 1: 尝试从 URL 中直接提取 cite ID ----
    for u in candidates:
        m = re.search(r'(?:cite[=-])(\d+)', u, re.IGNORECASE)
        if m:
            cite_id = int(m.group(1))
            break

    # ---- Step 2: 如果 URL 没有 cite，通过爬取落地页和 OGC API 反查 cite ID ----
    if cite_id is None and candidates:
        landing = None
        for u in candidates:
            if 'mrdata.usgs.gov' in u:
                landing = u.rstrip('/')
                break
        if landing:
            try:
                html = self._get_with_retry(landing).text
            except Exception:
                html = ''
            
            # 寻找分类特征码
            cats = re.findall(r'science\.php\?thcode=(\d+)(?:&amp;|&)term=(\d+)', html)
            seen = set()
            for thcode, code in cats:
                key = (thcode, code)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    search_url = f'https://mrdata.usgs.gov/catalog/records-matching.php?thcode={thcode}&code={code}'
                    raw = self._get_with_retry(search_url).text
                    data = json.loads(raw)
                except Exception:
                    continue
                
                recs = data.get('record') or []
                for r in recs:
                    link = (r.get('onlink') or '').rstrip('/')
                    if r.get('cite') and link == landing:
                        cite_id = int(r['cite'])
                        break
                if cite_id is not None:
                    break

    if cite_id is None:
        return {'error': '无法从 dataset_url 或 doi_landing_page 解析出 MRData 内部 cite ID'}

    # ---- Step 3: 获取动态生成的 ISO 19139 XML ----
    iso_url = f'https://mrdata.usgs.gov/catalog/iso.php?cite={cite_id}'
    try:
        iso_resp = self._get_with_retry(iso_url)
        iso_text = iso_resp.text
    except Exception as e:
        return {'error': f'获取 ISO 接口失败: {str(e)}'}

    # ---- Step 4 (新增): 顺藤摸瓜，从 ISO 中提取原版静态 FGDC XML 链接 ----
    true_xml_url = None
    fgdc_text = None
    
    # 兼容性正则：匹配类似 <gmd:linkage>https://mrdata.usgs.gov/metadata/usgravboug.xml</gmd:linkage>
    xml_link_match = re.search(r'<[^>]+linkage>\s*(https?://mrdata\.usgs\.gov/metadata/[^<]+\.xml)\s*</[^>]+linkage>', iso_text, re.IGNORECASE)
    
    if xml_link_match:
        true_xml_url = xml_link_match.group(1).strip()
        # 发起二次请求，获取最原始的硬核元数据
        try:
            fgdc_resp = self._get_with_retry(true_xml_url)
            fgdc_text = fgdc_resp.text
        except Exception:
            pass

    # ---- Step 5: 结果组装与返回 ----
    if fgdc_text:
        # 方案 A：成功获取到原版数据
        return {
            'source': 'USGS MRDATA (Original FGDC Metadata)',
            'format': 'xml',
            'cite_id': cite_id,
            'metadata_url': true_xml_url, 
            'data': fgdc_text
        }
    else:
        # 方案 B：降级返回 ISO 生成版数据
        stripped = iso_text.lstrip()
        fmt = 'json' if (stripped.startswith('{') or stripped.startswith('[')) else 'xml'
        return {
            'source': 'USGS MRDATA (ISO Generated Metadata)',
            'format': fmt,
            'cite_id': cite_id,
            'metadata_url': iso_url,
            'data': iso_text
        }
