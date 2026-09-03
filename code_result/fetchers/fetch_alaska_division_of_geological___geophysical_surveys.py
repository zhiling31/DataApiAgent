# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for Alaska Division of Geological & Geophysical Surveys
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="Alaska Division of Geological & Geophysical Surveys",
    aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="AI 初始判定",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_alaska_division_of_geological___geophysical_surveys(self, **kwargs):
    metadata_url = None
    import re

    dataset_name = (kwargs.get("dataset_name") or "").strip()
    dataset_url = (kwargs.get("dataset_url") or "").strip()
    doi_landing_page = (kwargs.get("doi_landing_page") or "").strip()
    download_url = (kwargs.get("download_url") or "").strip()

    publication_no = None

    def extract_publication_no_from_text(text):
        if not text:
            return None
        # Prefer explicit short citations such as RDF 2026-13, PIR 2026-1
        m = re.search(r'\b(RDF|PIR|MP|RI|DDS|GB|IC|SR|GR|BMP|MR)\s*(\d{4})\s*[-–—]\s*(\d+)\b', text, re.IGNORECASE)
        if m:
            return f"{m.group(1).upper()}{m.group(2)}-{int(m.group(3))}"
        # Long-form publication series names
        m = re.search(r'\bRaw Data File\s*(\d{4})\s*[-–—]\s*(\d+)\b', text, re.IGNORECASE)
        if m:
            return f"RDF{m.group(1)}-{int(m.group(2))}"
        m = re.search(r'\bPreliminary Interpretive Report\s*(\d{4})\s*[-–—]\s*(\d+)\b', text, re.IGNORECASE)
        if m:
            return f"PIR{m.group(1)}-{int(m.group(2))}"
        m = re.search(r'\bDigital Data Series\s*(\d+)\b', text, re.IGNORECASE)
        if m:
            return f"DDS{int(m.group(1))}"
        return None

    def clean_urls(raw):
        if not raw:
            return []
        return re.findall(r'https?://[^\s;；，,]+', raw)

    # Path 1: dataset_name usually contains the official DGGS series citation (e.g. "DGGS RDF 2026-13").
    if dataset_name:
        publication_no = extract_publication_no_from_text(dataset_name)

    # Path 2: the download URL often contains a filename like rdf2026_013_...
    candidate_download_url = download_url
    if not candidate_download_url and dataset_url:
        urls = clean_urls(dataset_url)
        candidate_download_url = next((u for u in urls if 'webpubs/data/' in u), None)
    if not publication_no and candidate_download_url:
        m = re.search(r'/([a-z]{2,5})(\d{4})_(\d{3})_', candidate_download_url, re.IGNORECASE)
        if m:
            publication_no = f"{m.group(1).upper()}{m.group(2)}-{int(m.group(3))}"

    # Path 3: fetch the publication landing page (/pubs/id/{citation_id}) and extract the series number.
    if not publication_no:
        candidate_landing_url = doi_landing_page
        if not candidate_landing_url and dataset_url:
            urls = clean_urls(dataset_url)
            candidate_landing_url = urls[0] if urls else dataset_url
        if candidate_landing_url and candidate_landing_url.startswith('http'):
            try:
                landing_resp = self._get_with_retry(candidate_landing_url, headers={"Accept": "text/html,application/xhtml+xml"})
            except Exception:
                landing_resp = None
            landing_text = None
            if landing_resp is not None:
                if hasattr(landing_resp, "text"):
                    landing_text = landing_resp.text
                elif isinstance(landing_resp, str):
                    landing_text = landing_resp
            if landing_text:
                publication_no = extract_publication_no_from_text(landing_text)

    if not publication_no:
        return {'error': '无法从 dataset_name、dataset_url、doi_landing_page 或 download_url 解析出 DGGS 出版物编号（如 RDF2026-13）', 'api_url': metadata_url}

    metadata_url = f"https://dggs.alaska.gov/webpubs/metadata/{publication_no}.xml"

    try:
        catalog_resp = self._get_with_retry(metadata_url, headers={"Accept": "application/xml,text/xml,*/*;q=0.8"})
    except Exception as exc:
        return {'error': f'DGGS metadata request failed: {exc}', 'api_url': metadata_url}

    if catalog_resp is None:
        return {'error': 'DGGS metadata API 返回空响应', 'api_url': metadata_url}

    status_code = getattr(catalog_resp, "status_code", None)
    if status_code is not None and int(status_code) >= 400:
        return {'error': f'DGGS metadata API HTTP {status_code}', 'api_url': metadata_url}

    if hasattr(catalog_resp, "text"):
        raw_text = catalog_resp.text
    elif isinstance(catalog_resp, str):
        raw_text = catalog_resp
    else:
        raw_text = str(catalog_resp)

    if not raw_text or "<metadata" not in raw_text:
        return {'error': 'DGGS metadata 返回的内容不是预期的 XML 元数据', 'api_url': metadata_url}

    return {'source': 'Alaska Division of Geological & Geophysical Surveys', 'format': 'xml', 'data': raw_text, 'api_url': metadata_url}
