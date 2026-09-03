# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for NOAA National Centers for Environmental Information (NCEI)
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="NOAA National Centers for Environmental Information (NCEI)",
    aliases=["NOAA NCEI"],
    has_api=True,
    is_reviewed=True,
    auditor_notes="AI 初始判定",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_noaa_national_centers_for_environmental_information__ncei_(self, **kwargs):
    import re
    import urllib.parse

    doi = kwargs.get('doi')
    dataset_url = kwargs.get('dataset_url')
    doi_landing_page = kwargs.get('doi_landing_page')
    dataset_name = kwargs.get('dataset_name')

    metadata_id = None

    if not metadata_id:
        urls_to_check = []
        if doi_landing_page:
            urls_to_check.extend(doi_landing_page.split(';'))
        if dataset_url:
            urls_to_check.extend(dataset_url.split(';'))
        for url in urls_to_check:
            url = url.strip()
            # Look for id=gov.noaa... in the URL
            m = re.search(r'id=(gov\.noaa\.[^"\'&\s<>;]+)', url)
            if m:
                metadata_id = urllib.parse.unquote(m.group(1))
                break

    if not metadata_id and doi_landing_page:
        m = re.search(r'/iso/xml/([^/.&]+)\.xml', doi_landing_page)
        if m:
            name = m.group(1)
            metadata_id = f"gov.noaa.ngdc.mgg.dem:{name}"

    if not metadata_id and doi_landing_page:
        try:
            resp = self._get_with_retry(doi_landing_page)
            if resp and resp.text:
                m = re.search(r'NCEI\s+Metadata\s+ID:\s*(gov\.noaa\.[^"\'\s<>;]+)', resp.text)
                if m:
                    metadata_id = m.group(1)
        except Exception:
            pass

    if not metadata_id and dataset_url:
        try:
            resp = self._get_with_retry(dataset_url)
            if resp and resp.text:
                m = re.search(r'NCEI\s+Metadata\s+ID:\s*(gov\.noaa\.[^"\'\s<>;]+)', resp.text)
                if m:
                    metadata_id = m.group(1)
        except Exception:
            pass

    if not metadata_id:
        pages_to_scrape = []
        if doi_landing_page:
            pages_to_scrape.extend(doi_landing_page.split(';'))
        if dataset_url:
            pages_to_scrape.extend(dataset_url.split(';'))
        for page_url in pages_to_scrape:
            page_url = page_url.strip()
            if not page_url:
                continue
            try:
                resp = self._get_with_retry(page_url)
                if resp and resp.text:
                    m = re.search(
                        r'ncei\.noaa\.gov/access/metadata/landing-page/bin/iso\?id=([^"\'&\s<>;]+)',
                        resp.text
                    )
                    if m:
                        metadata_id = urllib.parse.unquote(m.group(1))
                        break
            except Exception:
                continue

    if not metadata_id:
        pages_to_scrape = []
        if doi_landing_page:
            pages_to_scrape.extend(doi_landing_page.split(';'))
        if dataset_url:
            pages_to_scrape.extend(dataset_url.split(';'))
        for page_url in pages_to_scrape:
            page_url = page_url.strip()
            if not page_url:
                continue
            try:
                resp = self._get_with_retry(page_url)
                if resp and resp.text:
                    m = re.search(r'(gov\.noaa\.(?:nodc|ngdc)[^\s"\'<>&;]+)', resp.text)
                    if m:
                        candidate = m.group(1)
                        candidate = candidate.rstrip('.,;:')
                        metadata_id = candidate
                        break
            except Exception:
                continue

    if not metadata_id and dataset_url and 'ncei.noaa.gov/products/' in dataset_url:
        try:
            resp = self._get_with_retry(dataset_url)
            if resp and resp.text:
                for pattern in [
                    r'/(?:access/metadata|metadata/geoportal)[^"\'<\s]+',
                ]:
                    m = re.search(pattern, resp.text)
                    if m:
                        sub_url = m.group(0)
                        id_m = re.search(r'id=([^&"\'<\s;]+)', sub_url)
                        if id_m:
                            metadata_id = urllib.parse.unquote(id_m.group(1))
                            break
                        id_m = re.search(r'/item/([^/"\'<\s;]+)', sub_url)
                        if id_m:
                            metadata_id = urllib.parse.unquote(id_m.group(1))
                            break
        except Exception:
            pass

    if not metadata_id:
        pages_to_scrape = []
        if dataset_url:
            pages_to_scrape.extend(dataset_url.split(';'))
        if doi_landing_page:
            pages_to_scrape.extend(doi_landing_page.split(';'))
        for page_url in pages_to_scrape:
            page_url = page_url.strip()
            if not page_url:
                continue
            try:
                resp = self._get_with_retry(page_url)
                if not resp or not getattr(resp, 'text', None):
                    continue
                text = resp.text
                product_id = None

                m = re.search(r'prodnum=([A-Za-z]+\d+)-POS-[A-Za-z0-9]+', text, flags=re.I)
                if m:
                    product_id = m.group(1)

                if not product_id:
                    m = re.search(r'/([A-Za-z]+\d+)-pos-[a-z0-9]+\.pdf', text, flags=re.I)
                    if m:
                        product_id = m.group(1)

                if product_id:
                    metadata_id = "gov.noaa.ngdc.mgg.geophysics:" + product_id.upper()
                    break
            except Exception:
                continue

    if not metadata_id:
        return {"error": "无法从已知参数中解析出 NCEI Metadata ID"}

    api_url = f"https://www.ncei.noaa.gov/metadata/geoportal/rest/metadata/item/{metadata_id}/xml"

    try:
        print("NOAA", api_url)
        resp = self._get_with_retry(api_url)
        if not resp or not getattr(resp, 'text', None):
            return {"error": "NCEI Geoportal API 请求失败", "api_url": api_url}
        return {
            "source": "NOAA NCEI",
            "format": "xml",
            "data": resp.text,
            "api_url": api_url
        }
    except Exception as exc:
        return {"error": f"NCEI Geoportal API 请求异常: {exc}", "api_url": api_url}
