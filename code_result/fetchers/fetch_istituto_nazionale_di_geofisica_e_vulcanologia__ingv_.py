# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for Istituto Nazionale di Geofisica e Vulcanologia (INGV)
from code_result.fetcher_decorator import register_api

import re
@register_api(
    publisher="Istituto Nazionale di Geofisica e Vulcanologia (INGV)",
    aliases=["INGV Open Data Registry"],
    has_api=True,
    is_reviewed=True,
    auditor_notes="AI 初始判定",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_istituto_nazionale_di_geofisica_e_vulcanologia__ingv_(self, **kwargs):
    meta_url = None
    doi = (kwargs.get('doi') or '').strip()
    dataset_url = (kwargs.get('dataset_url') or '').strip()
    doi_landing_page = (kwargs.get('doi_landing_page') or '').strip()
    dataset_name = (kwargs.get('dataset_name') or '').strip()

    if not any([doi, dataset_url, doi_landing_page, dataset_name]):
        return {'error': '缺少关键参数：doi / dataset_url / doi_landing_page / dataset_name 均为空', 'api_url': meta_url}

    package_id = None
    raw_url_candidates = [doi_landing_page, dataset_url]
    http_urls = []
    for raw in raw_url_candidates:
        if raw:
            http_urls.extend(re.findall(r'https?://[^\s;，,]+', raw))
    # 防止空字符串进入后续 find 逻辑
    for url in [u for u in http_urls if u]:
        m = re.search(r'data\.ingv\.it/(?:en/)?dataset/(\d+)', url)
        if m:
            package_id = m.group(1)
            break

    # 从 DISS 官方 Data 页面中，通过 DOI/版本锚点解析 INGV 注册表内部 ID
    if not package_id and doi:
        try:
            resp = self._get_with_retry(
                'https://diss.ingv.it/data/',
                headers={'User-Agent': 'Mozilla/5.0 metadata-client'}
            )
            html = resp.text or ''
            needle = doi.lower()
            lower_html = html.lower()
            pos = lower_html.find(needle)
            if pos == -1 and 'doi.org' in needle:
                pos = lower_html.find(needle.replace('doi.org/', ''))
            if pos != -1:
                window = html[pos:pos + 20000]
                m_meta = re.search(r'metadata/iso19115/(\d+)', window)
                m_ds = re.search(r'data\.ingv\.it/(?:en/)?dataset/(\d+)', window)
                if m_meta:
                    package_id = m_meta.group(1)
                elif m_ds:
                    package_id = m_ds.group(1)
        except Exception:
            package_id = None

    if not package_id:
        return {'error': '缺少关键参数，无法解析出 INGV 内部数据集 ID', 'api_url': meta_url}

    meta_url = 'https://data.ingv.it/metadata/iso19115/{}.xml'.format(package_id)
    try:
        resp = self._get_with_retry(
            meta_url,
            headers={'User-Agent': 'Mozilla/5.0 metadata-client'}
        )
    except Exception as e:
        return {'error': 'INGV ISO 19139 元数据请求失败: {}'.format(e), 'api_url': meta_url}

    if resp.status_code != 200:
        return {'error': 'INGV ISO 19139 元数据接口返回 HTTP {}'.format(resp.status_code), 'api_url': meta_url}

    text = resp.text or ''
    # 服务器当前会在 XML 声明前输出 PHP warning，这里仅移除前置噪声，不解析或改写 XML 元数据本身
    xml_pos = text.find('<?xml')
    if xml_pos != -1:
        text = text[xml_pos:]

    return {'source': 'INGV Open Data Registry (data.ingv.it)', 'format': 'xml', 'data': text, 'api_url': meta_url}
