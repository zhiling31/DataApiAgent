# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for NOAA National Centers for Environmental Information (NCEI)
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="NOAA National Centers for Environmental Information (NCEI)", aliases=["NOAA NCEI"],
    has_api=True,
    is_reviewed=True,
    auditor_notes="人工初始审核",
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

    # ========== OLD STRATEGIES (legacy, keep untouched) ==========

    # Strategy 1: Extract from doi_landing_page URL pattern
    # Pattern: ...?xml=.../iso/xml/{name}.xml&...
    if not metadata_id and doi_landing_page:
        m = re.search(r'/iso/xml/([^/.&]+)\.xml', doi_landing_page)
        if m:
            name = m.group(1)
            metadata_id = f"gov.noaa.ngdc.mgg.dem:{name}"

    # Strategy 2: Scrape doi_landing_page for NCEI Metadata ID
    if not metadata_id and doi_landing_page:
        try:
            resp = self._get_with_retry(doi_landing_page)
            if resp and resp.text:
                m = re.search(r'NCEI\s+Metadata\s+ID:\s*(gov\.noaa\.[^\s<]+)', resp.text)
                if m:
                    metadata_id = m.group(1)
        except Exception:
            pass

    # Strategy 3: Scrape dataset_url for NCEI Metadata ID
    if not metadata_id and dataset_url:
        try:
            resp = self._get_with_retry(dataset_url)
            if resp and resp.text:
                m = re.search(r'NCEI\s+Metadata\s+ID:\s*(gov\.noaa\.[^\s<]+)', resp.text)
                if m:
                    metadata_id = m.group(1)
        except Exception:
            pass

    # ========== NEW STRATEGIES (for WOD / product-page type datasets) ==========

    # Strategy 4: Scrape pages for NCEI metadata landing page URLs
    # Pattern: ncei.noaa.gov/access/metadata/landing-page/bin/iso?id=xxx
    if not metadata_id:
        pages_to_scrape = []
        if doi_landing_page:
            pages_to_scrape.append(doi_landing_page)
        if dataset_url:
            pages_to_scrape.append(dataset_url)
        for page_url in pages_to_scrape:
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

    # Strategy 5: Scrape pages for any gov.noaa.nodc: or gov.noaa.ngdc: identifier
    if not metadata_id:
        pages_to_scrape = []
        if doi_landing_page:
            pages_to_scrape.append(doi_landing_page)
        if dataset_url:
            pages_to_scrape.append(dataset_url)
        for page_url in pages_to_scrape:
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

    # Strategy 6: If dataset_url is an NCEI products page, try to construct 
    # metadata landing page URL and scrape it for the metadata ID
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
        return {"error": "无法从已知参数中解析出 NCEI Metadata ID"}

    # Use NCEI Geoportal REST API
    api_url = f"https://www.ncei.noaa.gov/metadata/geoportal/rest/metadata/item/{metadata_id}/xml"

    resp = self._get_with_retry(api_url)
    print("NOAA",api_url)

    return {
        "source": "NOAA NCEI",
        "format": "xml",
        "data": resp.text,
        "api_url":api_url
    }
