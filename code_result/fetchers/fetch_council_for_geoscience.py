# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for Council for Geoscience
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="Council for Geoscience", aliases=[],
    has_api=True,
    is_reviewed=True,
    auditor_notes="人工初始审核",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_council_for_geoscience(self, **kwargs):

    import urllib
    import re
    from urllib.parse import quote

    api_base = "https://www.geoscience.org.za/wp-json/wp/v2/pages"
    dataset_url = kwargs.get("dataset_url") or ""
    doi_landing_page = kwargs.get("doi_landing_page") or ""
    dataset_name = kwargs.get("dataset_name") or ""

    ignored_slugs = {"cgs", "systems", "publications", "category", "author", "tag"}

    def normalize_slug(name):
        if not name or not str(name).strip():
            return None
        slug = re.sub(r"[^a-z0-9]+", "-", str(name).strip().lower()).strip("-")
        if slug and slug not in ignored_slugs:
            return slug
        return None

    slug = None

    raw_urls = []
    for raw in (dataset_url, doi_landing_page):
        if raw and str(raw).strip():
            raw_urls.extend(re.findall(r"https?://[^\s;，,、\"'）)]+", str(raw)))

    for url in raw_urls:
        if not url:
            continue
        clean = url.split("#", 1)[0].split("?", 1)[0].rstrip("/")
        if not clean:
            continue
        lower = clean.lower()
        if "/download/" in lower:
            continue
        if lower.endswith((".zip", ".pdf", ".xml", ".json", ".csv", ".asc", ".tif", ".png")):
            continue
        m = re.search(r"/([a-z0-9-]+)/?$", clean)
        if m:
            slug = normalize_slug(m.group(1))
            if slug:
                break

    if not slug:
        slug = normalize_slug(dataset_name)

    if not slug:
        return {"error": "缺少关键参数，无法从链接/名称解析出目标集合的 slug"}

    api_url = "{}?slug={}".format(api_base, quote(slug, safe=""))

    try:
        resp = self._get_with_retry(api_url)
    except Exception as exc:
        return {"error": "请求 WordPress REST API 失败: {}".format(exc)}

    try:
        payload = resp if isinstance(resp, dict) else resp.json()
    except Exception as exc:
        return {"error": "响应 JSON 解析失败: {}".format(exc)}

    if isinstance(payload, list) and len(payload) == 0:
        return {"error": "slug 未能匹配到任何页面记录: {}".format(slug)}

    return {
        "source": "Council for Geoscience (geoscience.org.za WordPress REST API)",
        "format": "json",
        "data": payload,
    }
