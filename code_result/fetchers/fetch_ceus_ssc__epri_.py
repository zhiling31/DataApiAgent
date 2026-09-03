# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for CEUS-SSC (EPRI)
from code_result.fetcher_decorator import register_api

@register_api(
    publisher="CEUS-SSC (EPRI)",
    aliases=["CEUS-SSC"],
    has_api=True,
    is_reviewed=True,
    auditor_notes="返回的是MediaWiki页面数据（不是严格的结构化后数据）",
    scope_limit="ITEM_LEVEL_ONLY"
)
def fetch_ceus_ssc__epri_(self, **kwargs):
    import json
    import re
    from urllib.parse import urlparse, parse_qs, unquote, urlencode

    dataset_url = kwargs.get("dataset_url")
    doi_landing_page = kwargs.get("doi_landing_page")

    raw_url = None
    if isinstance(dataset_url, str) and dataset_url.strip():
        raw_url = dataset_url.strip()
    elif isinstance(doi_landing_page, str) and doi_landing_page.strip():
        raw_url = doi_landing_page.strip()

    if not raw_url:
        return {"error": "缺少关键参数 dataset_url 或 doi_landing_page，无法解析出 MediaWiki 页面标题"}

    # 兼容“落地页url:...;下载页url:...”这类复合入参：优先取非 ZIP 的落地页 URL
    urls = re.findall(r'https?://[^\s;，；]+', raw_url)
    if urls:
        landing = None
        for u in urls:
            if not u.lower().endswith(".zip") and "/images/" not in u.lower():
                landing = u
                break
        if landing:
            raw_url = landing
        else:
            raw_url = urls[0]

    def extract_title(url):
        if not isinstance(url, str) or not url.strip():
            return None
        try:
            parsed = urlparse(url)
        except Exception:
            return None
        query_title = None
        try:
            qs = parse_qs(parsed.query)
            if qs.get("title") and qs["title"][0]:
                query_title = qs["title"][0]
        except Exception:
            pass
        if query_title:
            return unquote(query_title)
        path = parsed.path.rstrip("/")
        if not path:
            return None
        title = path.rsplit("/", 1)[-1]
        title = unquote(title)
        if title in ("index.php", "wiki", "api.php", ""):
            return None
        return title

    title = extract_title(raw_url)
    if not title:
        return {"error": "无法从 URL 中解析出 MediaWiki 页面标题"}

    # 若传入的是 ZIP 静态文件下载链接，则通过 MediaWiki fileusage 定位引用该文件的数据集页面
    if title.lower().startswith("file:") or title.lower().endswith(".zip") or "/images/" in raw_url.lower():
        file_title = title if title.lower().startswith("file:") else "File:" + title
        fileusage_url = "https://ceus-ssc.epri.com/api.php?" + urlencode({
            "action": "query",
            "format": "json",
            "titles": file_title,
            "prop": "fileusage",
            "fulimit": "10"
        })
        try:
            fu_resp = self._get_with_retry(fileusage_url)
            fu_data = fu_resp.json()
            fu_pages = fu_data.get("query", {}).get("pages", {})
            resolved = None
            for _pid, page in fu_pages.items():
                if not isinstance(page, dict):
                    continue
                for used_page in page.get("fileusage", []) or []:
                    if used_page.get("ns") == 0 and used_page.get("title"):
                        resolved = used_page["title"]
                        break
                if resolved:
                    break
            if resolved:
                title = resolved
        except Exception:
            pass

    api_url = "https://ceus-ssc.epri.com/api.php?" + urlencode({
        'action': 'query',
        'titles': title,
        'prop': 'info|categories|revisions',
        'rvprop': 'content|timestamp|user|ids',
        'rvslots': 'main',
        'format': 'json',
        'formatversion': '2',
        'rvlimit':'1'
    })

    resp = self._get_with_retry(api_url)
    try:
        data = resp.json()
        return {"source": "CEUS-SSC (EPRI)", "format": "json", "data": data,"api_url":api_url,"notes":"需要review，之前的case返回的是采集的是CEUS-SSC项目的GIS数据库的元数据，非Faults主题的元数据"}
    except Exception:
        return {"error": "结果无法解析为json，"+str(resp.text),"api_url":api_url}
