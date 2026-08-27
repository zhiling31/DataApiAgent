# -*- coding: utf-8 -*-
"""
用于自主搜索各数据存储平台的元数据获取 API，并进行轻量化可用性验证。
"""

import sys
sys.stdout.reconfigure(encoding='utf-8')
import os
import json
import uuid
import pandas as pd
import requests
from typing import TypedDict, Annotated, List, Optional
from pydantic import BaseModel, Field, model_validator
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_core.tools import tool
from langchain_tavily import TavilySearch
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
import logging
import sys

# 配置 Tavily API Key
# "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"（无0818）
# zhizhi333333@gmail.com           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（无8月）
# 2524258132@qq.com    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（无8月）
# 18868113539@163.com  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
os.environ["TAVILY_API_KEY"] = "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"

# ==========================================
# 0. 全局配置 (文件路径修改区)
# ==========================================
# 你可以在这里修改所有的输入输出文件路径
# INPUT_DATASET_FILE = "../45个数据集target_datasets.txt"       # 输入的原始数据集文件 (制表符分隔)
INPUT_DATASET_FILE =  r"D:\地学\doi\数据清单\20260820-第二批数据集\Gravity_master-27个_simple.txt"
OUTPUT_RESULTS_DIR = r"D:\地学\doi\数据清单\20260820-第二批数据集\Gravity_master-27个"
OUTPUT_RESULTS_FILE = os.path.join(OUTPUT_RESULTS_DIR, "publisher_api_results.xlsx")  # 增量保存的提取结果文件
OUTPUT_TRACE_FILE = os.path.join(OUTPUT_RESULTS_DIR, "publisher_api_trace.json")      # 大模型探索日志与思考过程文件
REGISTRY_FILE = "code_result/platform_api_registry.json"         # 大模型生成的 API 知识库 (存放 Python 代码)
TARGET_INJECT_FILE = "code_result/fetch_top_dataset_integrated_0728.py"   # 生成的 Python 代码最终注入的目标文件
USE_DATASET_INFO_CACHE = True  # 如果为 True，则启用并读取大模型对数据集基础信息（DOI/URL/平台名称）的提取缓存（dataset_extractor结果），避免重复调用提取大模型
IGNORE_API_CODE_CACHE = False  # 如果为 True，则强制重新生成平台 API 代码，忽略 platform_api_registry_0728.json 的缓存命中
IGNORE_PROGRESS_CACHE = True  # 如果为 True，则忽略断点续传的执行进度 (publisher_api_results)，强制重新运行所有数据集
IS_HEAL_MODE = True           # 内部状态标志，用来标记是否在进行 API 的自愈进化
dataset_info_cache_file = os.path.join(OUTPUT_RESULTS_DIR,"dataset_info_cache.json")
os.makedirs(OUTPUT_RESULTS_DIR,exist_ok=True)




logger = logging.getLogger('fetch_publisher')
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    
    file_handler = logging.FileHandler(os.path.join(OUTPUT_RESULTS_DIR,'fetch_publisher_api.log'), encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # 把 DatasetAgent 的日志也绑定到当前的终端和文件处理器上，确保 dataset_extractor 的日志也能输出到该文件
    dataset_logger = logging.getLogger('DatasetAgent')
    dataset_logger.setLevel(logging.INFO)
    dataset_logger.addHandler(handler)
    dataset_logger.addHandler(file_handler)


# ==========================================
# 1. 定义严格的 Pydantic 结构化输出模型 (防幻觉核心)
# ==========================================
class APIAttempt(BaseModel):
    api_template: Optional[str] = Field(description="测试的 API 模板", default=None)
    test_dataset_id: Optional[str] = Field(description="代入的参数 (dataset_id 或 doi 等)", default=None)
    tested_url: Optional[str] = Field(description="实际请求的完整 URL", default=None)
    is_successful: bool = Field(description="验证是否通过", default=False)
    error_message_or_response: Optional[str] = Field(description="如果失败，记录报错原因/状态码；如果成功，可简略记录返回或状态", default=None)

class HumanAudit(BaseModel):
    is_reviewed: bool = Field(description="是否经过人工复核 (初次生成默认为 false，人工审核后改为 true)", default=False)
    auditor_notes: Optional[str] = Field(description="人工复核备注说明", default="")
    scope_limit: Optional[str] = Field(description="API 粒度作用域：ITEM_LEVEL_ONLY | CATALOG_LEVEL_ONLY | BOTH | NONE", default="ITEM_LEVEL_ONLY")
    reviewed_at: Optional[str] = Field(description="人工审核完成时间 (格式: YYYY-MM-DD HH:MM:SS)", default=None)

class PublisherAPIResult(BaseModel):
    publisher_name: str = Field(description="目标数据存储平台/Publisher名称")
    python_code: Optional[str] = Field(description="为该平台定制的完整 Python 获取函数代码。签名必须以 fetch_ 开头：`def fetch_xxx(self, **kwargs):`。注意：因为函数将作为独立插件运行，你【必须】在函数体内部手动 import 需要用到的所有包（例如 import json, requests, re 等）。对于原生 API 返回的数据直接透传，勿二次解析，格式如 `{'source': '平台名', 'format': 'json', 'data': ...}`。若无可用API则返回 null。", default=None)
    test_dataset_id: Optional[str] = Field(description="用于验证的真实 Dataset ID 或 DOI", default=None)
    is_verified: bool = Field(description="是否找到了真实存在的 API。如果测试返回 200，必须填 True！否则天False", default=False)
    requires_auth: bool = Field(description="该 API 是否需要身份验证。如果测试返回 401/403，则填 True。", default=False)
    has_anti_crawler_risk: bool = Field(description="该API是否存在明显的反爬虫合规风险", default=False)
    risk_level: str = Field(description="风险等级", default="中风险")
    has_432_error: bool = Field(description="是否遭遇了 432 额度耗尽错误", default=False)
    has_reached_search_limit: bool = Field(description="是否触发了搜索次数上限", default=False)
    api_attempts: List[APIAttempt] = Field(description="所有测试过的 API记录", default_factory=list)
    reasoning_summary: str = Field(description="对整个搜索和验证过程的简短总结", default="")
    human_audit: HumanAudit = Field(default_factory=HumanAudit)

    @model_validator(mode='after')
    def set_default_scope(self) -> 'PublisherAPIResult':
        if not self.human_audit.is_reviewed:
            if self.is_verified:
                self.human_audit.scope_limit = "ITEM_LEVEL_ONLY"
            else:
                self.human_audit.scope_limit = "NONE"
        return self

# ==========================================
# 2. 定义 Agent 状态与工具
# ==========================================
class AgentState(TypedDict):
    messages: Annotated[List, lambda x, y: x + y]
    publisher: str
    dataset_name: str
    dataset_url: str
    dataset_doi: str
    doi_landing_page: str
    is_cached: bool
    final_metadata: dict # 最终提取的字典
    old_python_code: str
    old_api_attempts: list
    old_reasoning_summary: str
    old_baseline_context: dict
    error_reason: str


CURRENT_DATASET_CONTEXT = {
    "dataset_name": "",
    "dataset_url": "",
    "doi": "",
    "publisher": "",
    "dataset_description": "",
    "search_call_count": 0,
    "search_432_error": False,
    "search_limit_reached": False
}

OLD_BASELINE_CONTEXT = {}

def get_doi_metadata(doi: str) -> dict:
    """尝试通过 doi.org 内容协商获取 DOI 的官方元数据（标题、摘要、作者）"""
    meta = {"title": "", "abstract": "", "authors": []}
    if not doi: return meta
    doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "").strip()
    
    try:
        headers = {"Accept": "application/vnd.citationstyles.csl+json"}
        # doi.org 是顶级解析器，内容协商可统一跨机构 (DataCite/Crossref 等) 的返回格式
        r = requests.get(f"https://doi.org/{doi}", headers=headers, timeout=5)
        if r.status_code == 200:
            data = r.json()
            
            title = data.get("title", "")
            if isinstance(title, list) and len(title) > 0:
                meta["title"] = str(title[0])
            else:
                meta["title"] = str(title)
            
            abstract = data.get("abstract", "")
            if abstract:
                import re
                # 清洗部分返回结果中带有的 HTML 标签 (如 <jats:p>)
                meta["abstract"] = re.sub(r'<[^>]+>', '', str(abstract)).strip()
                
            authors = data.get("author", [])
            for a in authors:
                if isinstance(a, dict):
                    name = f"{a.get('given', '')} {a.get('family', '')}".strip()
                    if name:
                        meta["authors"].append(name)
            
            # 如果由于某种原因 name 的格式是 literal
            if not meta["authors"]:
                for a in authors:
                    if isinstance(a, dict) and a.get("literal"):
                        meta["authors"].append(a.get("literal"))
                        
            return meta
    except Exception as e:
        pass
        
    return meta

def check_semantic_metadata(data, status_code=200, api_url=""):
    import json
    try:
        data_str = json.dumps(data, ensure_ascii=False)
    except Exception:
        data_str = str(data)
        
    data_str_lower = data_str.lower()
        
    # --- 1. 基于 DOI 官方元数据的极速匹配通道 ---
    current_doi = CURRENT_DATASET_CONTEXT.get("doi", "")
    current_name = CURRENT_DATASET_CONTEXT.get("dataset_name", "")
    doi_meta = {"title": "", "abstract": "", "authors": []}
    
    if current_doi:
        doi_meta = get_doi_metadata(current_doi)
        doi_title = doi_meta["title"]
        # if doi_title:
        #     import re
        #     clean_title = doi_title.lower()
        #     words = [w for w in re.split(r'\W+', clean_title) if len(w) >= 4]
            
        #     # 条件1：标题匹配度（100%匹配，或者核心单词命中率 >= 80%）
        #     title_exact_match = (clean_title in data_str_lower)
        #     title_words_match = False
        #     if words:
        #         match_count = sum(1 for w in words if w in data_str_lower)
        #         if match_count >= max(1, int(len(words) * 0.8)):
        #             title_words_match = True
                    
        #     # 条件2：作者或摘要命中
        #     author_match = any(a.lower() in data_str_lower for a in doi_meta["authors"] if len(a) > 4)
        #     clean_abstract = re.sub(r'<[^>]+>', '', doi_meta["abstract"]).strip()
        #     abstract_snippet = clean_abstract[:100].lower() if clean_abstract else ""
        #     abstract_match = (len(abstract_snippet) > 20 and abstract_snippet in data_str_lower)
            
        #     # 严格加速通道：必须标题高度吻合，且（精准匹配 或者 发生了作者/摘要的交叉验证）
        #     if title_exact_match or (title_words_match and (author_match or abstract_match)):
        #         url_log = f" URL: {api_url} |" if api_url else ""
        #         logger.info(f"   ⚡ [语义加速] API 结果不仅命中了 DOI 标题，还符合作者/摘要交叉验证！直接判定通过！({url_log} Title: {doi_title})")
        #         return True, "AUTO", "语义加速: 官方DOI元数据强吻合"

    # --- 2. 兜底回退：大模型语义判别 ---
    data_str = data_str[:2500]  # 截断以控制 token 开销并防止过长
    
    current_desc = CURRENT_DATASET_CONTEXT.get("dataset_description", "")
    
    # 将 DOI 和输入信息注入 Prompt 中作为参考
    doi_reference_info = ""
    if doi_meta.get("title"):
        doi_reference_info += f"【官方 DOI 注册指纹】\n     - 目标标题: {doi_meta['title']}\n        - 目标作者: {', '.join(doi_meta['authors'])[:200]}\n        - 目标摘要片段: {doi_meta['abstract'][:300]}...\n"
    
    if current_name or current_desc:
        doi_reference_info += f"【原始输入指纹】\n"
        if current_name:
            doi_reference_info += f"      - 目标标题: {current_name}\n"
        if current_desc:
            doi_reference_info += f"      - 目标描述: {current_desc}\n"
        
    prompt = f"""你是一个严格的数据格式和语义校验专家。请判断以下数据片段是否属于“宏观的学术数据集资源（Collection-level / Dataset-level）”元数据。
        我们当前正在寻找特定数据集的 API。该数据集的语义指纹如下：
        {doi_reference_info}

        请你执行严格的【两步鉴定】：

        第一步（模态鉴定）：判断这段文本的真实数据格式是什么（JSON / XML / YAML / NDJSON / HTML / 纯文本 / 乱码）。（HTTP状态码：{status_code}）
        【致命红线】：如果它是普通的 HTML 网页（如带有 <!DOCTYPE html>、<body 等前端标签），即使状态码是 200 或命中了标题，也绝对不是合法的 API 报文！如果是 HTML 且返回了 401/403，那是防火墙拦截页！

        第二步（实体对齐与颗粒度鉴定）：如果格式合法，请仔细阅读报文内容，它是否【精确描述】了我们正在寻找的目标数据集？
        【一票否决标准 (只要触犯即判定为 NO)】：
        1. 【实体错位 / 张冠李戴】：
            实体错位：如果“目标语义指纹”请求的是一个【限定了某个具体国家/州/地方名或者其他限定条件的数据集】，而待校验报文的全局标题/描述中是不限定地名/宏观/全局的，这是实体错位，绝对不是目标数据集本身！必须坚决判定 VALID: NO！
            张冠李戴：返回的数据标题、摘要与我们的“目标语义指纹”完全不符！
        2. 【子实体/地名越界错位】：
           如果“目标语义指纹”请求的是一个【全局/宏观/不限定地名的数据集】，而待校验报文的全局标题/描述中强行限定了某个【具体国家/州/地方名】，这属于典型的“搜索首项子实体错位”！即使报文中包含了目标关键词，也绝对不是目标数据集本身！必须坚决判定 VALID: NO！
        3. 【全站大倾印 (Scope Too Large)】：返回的是整个平台的全站目录 (Catalog)、全局检索 Feed 或包含了成百上千个无关数据集的数组。API 没有精确定位到特定实体！
        4. 【底层微观碎片 (Scope Too Small)】：返回的仅仅是文件下载列表、某个具体观测点坐标、技术波段说明，缺乏整体学术描述。]
        5. 【系统内部配置】：如单纯的数据库表名列表、前端渲染组件。

        【通过标准 (必须同时满足)】：
        1. 包含宏观学术特征：如全局标题(title)、发布机构/作者(publisher/creator)、全局描述(abstract/description)、全局标识符(doi)。
        2. 描述的对象是一个完整的“数据集”、“数据库”或“项目集合”。

        请你严格按照以下 3 行格式输出（不要输出任何多余字符）：
        FORMAT: [识别出的格式，如 JSON/XML/YAML/HTML]
        VALID: [YES 或 NO]
        REASON: [一句话说明放行或拦截的理由]

        数据片段：
        {data_str}
        """
    try:
        response = custom_request_llm_invoke([
            SystemMessage(content="你是一个严格的数据格式和语义校验专家。"),
            HumanMessage(content=prompt)
        ], use_tools=False)
        
        result_text = response.content.strip().upper()
        detected_format = "UNKNOWN"
        is_valid = False
        reason = ""
        
        for line in result_text.split('\n'):
            line = line.strip()
            if line.startswith("FORMAT:"): detected_format = line.split(":", 1)[1].strip()
            elif line.startswith("VALID:"): is_valid = "YES" in line.upper()
            elif line.startswith("REASON:"): reason = line.split(":", 1)[1].strip()
                
        # 系统级硬拦截：大模型如果识别出 HTML，系统坚决不放行！
        if "HTML" in detected_format.upper():
            is_valid = False
            reason = f"{api_url}系统硬拦截：严禁将 HTML 网页作为 API 使用！这通常是防火墙或前端页面。"
            
        return is_valid, detected_format, reason
        

    except Exception as e:
        url_log = f" (URL: {api_url})" if api_url else ""
        logger.info(f"   ⚠️ [Warning] 大模型语义匹配校验异常，默认不放行{url_log}: {e}")
        return False, "UNKNOWN", "校验异常，默认拦截"

web_search_tool = TavilySearch(max_results=5, include_answer=True, search_depth="advanced")

MAX_SEARCH_LIMIT = 25

@tool
def tavily_search(query: str) -> str:
    """
    【搜索引擎工具】多功能搜索工具。
    1. 在寻找 DOI 阶段，用于全网搜索目标数据集的官方网页以提取精准本体 DOI。
    2. 在 API 挖掘阶段，用于寻找目标数据平台(Data Repository)的官方 API 文档或可用的真实 Dataset ID。
    """
    global CURRENT_DATASET_CONTEXT
    if CURRENT_DATASET_CONTEXT.get("search_432_error"):
        return "【系统硬性提示】: 搜索API额度已耗尽 (Error 432)！"
        
    if CURRENT_DATASET_CONTEXT.get("search_call_count", 0) >= MAX_SEARCH_LIMIT:
        CURRENT_DATASET_CONTEXT["search_limit_reached"] = True
        return f"【系统硬性提示】: 调用 tavily_search 的次数已达到上限 ({MAX_SEARCH_LIMIT}次)！"
        
    try:
        CURRENT_DATASET_CONTEXT["search_call_count"] = CURRENT_DATASET_CONTEXT.get("search_call_count", 0) + 1
        result = web_search_tool.invoke({"query": query})
        return result
    except Exception as e:
        err_str = str(e).lower()
        if "error 432" in err_str:
            CURRENT_DATASET_CONTEXT["search_432_error"] = True
            return "【系统硬性提示】: 搜索额度已耗尽 (Error 432)。"
        return f"搜索失败: {str(e)}"

@tool
def extract_html_meta(url: str) -> str:
    """
    【HTML元数据提取工具】多功能网页抓取工具。
    1. 在寻找 DOI 阶段，用于抓取文献页面或发布平台链接，提取内文以寻找官方 DOI（如 Data Availability 段落）。
    2. 在 API 挖掘阶段，如果通过 DOI 或当前链接无法直接找到 API 所需的内部 UUID，使用此工具抓取网页，提取其中的 JSON-LD 和 Meta 标签，寻找隐藏 UUID。
    """
    import re
    try:
        headers = {"User-Agent": "DataLibrarianAgent/1.0"}
        res = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        html = res.text
        
        json_lds = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL | re.IGNORECASE)
        metas = re.findall(r'<meta[^>]+>', html, re.IGNORECASE)
        
        res_str = ""
        if json_lds:
            res_str += "【发现 JSON-LD】:\n" + "\n".join([j[:1000] + ("..." if len(j)>1000 else "") for j in json_lds]) + "\n"
        if metas:
            filtered_metas = [m for m in metas if 'name=' in m.lower() or 'property=' in m.lower()]
            res_str += "【发现 Meta 标签】:\n" + "\n".join(filtered_metas[:35]) + "\n"
            
        if not res_str:
            return "【提取失败】: 未在网页中找到 JSON-LD 或包含 name/property 的 meta 标签。"
        return res_str
    except Exception as e:
        return f"【提取请求错误】错误信息: {str(e)}"

@tool
def verify_api_endpoint(api_url: str) -> str:
    """
    【API验证工具】尝试使用 HTTP GET 请求访问目标 API。
    请确保传入的 api_url 包含了具体的真实的 Dataset ID，例如 "https://zenodo.org/api/records/1234567"。
    该工具会返回 HTTP 状态码及返回的 JSON 结构的前 500 个字符。
    """
    from curl_cffi import requests as cffi_requests
    import requests as std_requests
    import urllib3
    urllib3.disable_warnings()
    
    try:
        try:
            # 直接告诉 curl_cffi 完美伪装成 Chrome 120
            response = cffi_requests.get(
                api_url, 
                timeout=30, 
                allow_redirects=True, 
                verify=False,
                impersonate="chrome120"  # 🌟 终极杀招：底层 TLS 指纹 100% 伪装
            )
        except cffi_requests.exceptions.RequestException as e:
            # 针对类似 osti.gov HTTP/2 握手拒绝的情况，降级使用原生 requests
            logger.info(f"⚠️ chrome120 伪装请求异常 ({str(e)}), 降级尝试原生 requests...")
            response = std_requests.get(
                api_url,
                timeout=30,
                allow_redirects=True,
                verify=False
            )
            
        status_code = response.status_code
        raw_text = response.text
        # 调用大模型鉴定器，一次性解决格式识别与语义校验
        is_valid, detected_format, reason = check_semantic_metadata(raw_text, status_code, api_url)
        
        # 截取一小段方便调试输出
        snippet = raw_text[:800].replace('\n', ' ')
        
        if is_valid:
            if status_code in [401, 403]:
                return f"【验证成功但需鉴权】Status: {status_code}\n格式: {detected_format}\n结论: {reason}\n【重要战略提示】：API可用但需鉴权。请不要立刻停止探索！你必须继续寻找是否有免鉴权的公开 API！只有穷尽手段找不到公开 API 时，才使用此接口。\n片段: {snippet}"
            return f"【验证成功】Status: {status_code}\n格式: {detected_format}\n结论: {reason}\n片段: {snippet}"
        else:
            return f"【验证失败】Status: {status_code}\n判定格式: {detected_format}\n拦截原因: {reason}\n片段: {snippet}\n请根据失败原因和返回片段重新判断，是填入参数有问题还是API有问题，找到正确参数格式或者API"
            
    except Exception as e:
        return f"【验证请求错误】错误信息: {str(e)}"

class DummyFetcher:
    def __init__(self):
        # 🌟 监控探头：记录这段代码实际发出的所有网络请求
        self.called_urls = []

    def _get_with_retry(self, url, headers=None, max_retries=3):
        # import urllib3
        # # 屏蔽烦人的 SSL 警告信息
        # urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        # self.called_urls.append(url)
        # headers = headers or {}
        # headers.setdefault("User-Agent", "DataLibrarianAgent/1.0")
        # response = requests.get(url, headers=headers, timeout=10, allow_redirects=True, verify=False)
        # response.raise_for_status()
        # return response
        import requests as std_requests
        from curl_cffi import requests # 🌟 使用指纹伪装库
        self.called_urls.append(url)
        
        headers = headers or {}
        try:
            response = requests.get(
                url, 
                headers=headers, 
                timeout=120, 
                allow_redirects=True, 
                verify=False,
                impersonate="chrome120" # 🌟 底层伪装
            )
            # HTTP/403 依然会 raise_for_status，保留你的防伪逻辑
            if response.status_code >= 400:
                response.raise_for_status()
            return response
        except Exception as e:
            if "HTTP/2" in str(e) or "curl:" in str(e):
                try:
                    fallback_resp = std_requests.get(url, headers=headers, timeout=120, allow_redirects=True, verify=False)
                    if fallback_resp.status_code < 400:
                        return fallback_resp
                    fallback_resp.raise_for_status()
                except Exception as fallback_e:
                    raise Exception(f"{e} (且降级requests失败: {fallback_e})")
            raise e
@tool
def execute_python_sandbox(python_code_str: str, test_kwargs_json: str, declared_api_url: str) -> str:
    """
    【真实代码沙箱验证工具】
    你必须将你写好的完整的抓取函数（例如 def fetch_xxx(self, **kwargs):）的源码传给此工具。
    【警告/绝对禁止】：
    同时，你必须提供你在挖掘阶段找到的测试参数的 JSON 字符串 (test_kwargs_json)，沙箱将解析该 JSON 并注入给代码。
    生产环境中通常可用的参数键值包括:
    - "doi": 官方 DOI
    - "dataset_url": 数据集链接
    - "doi_landing_page": 数据集落地页
    - "dataset_name": 数据集名称
    请将你目前找出的真实参数填入 test_kwargs_json (如 '{"doi": "10.xxx", "uuid": "1234"}') 供沙箱验证。
    你必须在 declared_api_url 参数中，如实申报你最终选定请求的那个最优 API 路径（用于底层防张冠李戴的轨迹核对）。
    """
@tool
def execute_python_sandbox(python_code_str: str, declared_api_url: str) -> str:
    """
    【真实代码沙箱验证工具】
    系统将【强制注入】当前用户输入的真实参数。你编写的 python_code_str 必须能自己从参数中解析出所需的内部 ID。
    - python_code_str: 你的 Python 函数源码。【警告】只能包含函数定义代码！由于函数将被保存为独立的插件文件，你【必须】在函数内部手动 import 所有用到的包（如 import json, requests, re）。沙箱已经移除了全局包注入，不写 import 将直接报错！绝对不允许包含测试脚手架（如实例化、print 测试等），否则会导致代码污染！
        沙箱在运行时，会自动向 kwargs 注入以下真实参数（你不必自己传，代码里直接用 kwargs.get() 接收即可）：
        - "doi": 官方 DOI
        - "dataset_url": 数据集原始链接
        - "doi_landing_page": DOI 解析落地页
        - "dataset_name": 数据集名称
    - declared_api_url: 你在探路阶段最终【选定】的那个最优原生 API 的 URL 模板（例如 "https://api.domain.com/v1/items/{id}"）。你必须如实申报，系统将进行轨迹核对！
    """
    import json
    import traceback
    global CURRENT_DATASET_CONTEXT
    
    # 强制物理代入全局真实参数（防伪造）
    kwargs_to_pass = {
        "dataset_name": CURRENT_DATASET_CONTEXT.get("dataset_name", ""),
        "dataset_url": CURRENT_DATASET_CONTEXT.get("dataset_url", ""),
        "doi": CURRENT_DATASET_CONTEXT.get("doi", ""),
        "doi_landing_page": CURRENT_DATASET_CONTEXT.get("doi_landing_page", "")
    }
        
    try:
        local_vars = {} # 强制移除了全局包注入，逼迫大模型必须在源码中自己写 import
        exec(python_code_str, globals(), local_vars)
        
        target_func = None
        target_func_name = ""
        for name, obj in local_vars.items():
            if callable(obj) and name.startswith("fetch_"):
                target_func = obj
                target_func_name = name
                break
                
        if not target_func:
            return "【执行失败】：传入的代码中没有找到任何以 'fetch_' 开头的方法！"
            
        fetcher = DummyFetcher()
        import types
        fetcher_method = types.MethodType(target_func, fetcher)
        setattr(fetcher, target_func_name, fetcher_method)

        # ==========================================
        # ⚔️ 杀招一：空参微盲测 (Micro-Fuzzing)
        # 目的：不传入任何有效参数，强制触发代码内部的异常/兜底分支，防范 NoneType 崩溃
        # ==========================================
        try:
            empty_test = fetcher_method(dataset_name="", dataset_url="", doi="", doi_landing_page="")
            if not isinstance(empty_test, dict) or "error" not in empty_test:
                return f"【代码极度脆弱 (空参盲测失败)】：当外部系统未传入任何有效参数时，你的代码未能返回标准 error 字典！请务必在提取 ID 失败时返回 {{\"error\": \"...\"}}！"
        except Exception as e:
            return f"【致命漏洞 (空参盲测崩溃)】：当外部未传入任何有效参数时，你的代码发生了 {type(e).__name__} 崩溃！\n【警告】：请严格遵守防御性编程纪律！必须在使用 kwargs 前进行判空（如 `if not doi: ...`），绝对禁止对可能为 None 的变量直接调用方法！\n报错堆栈: {traceback.format_exc()}"

        # ==========================================
        # ⚔️ 杀招三：基线兼容测试预留 (Baseline Test Mock)
        # 目的：使用老数据进行空转测试，确保对老指纹的兼容性没有被打破
        # ==========================================
        global OLD_BASELINE_CONTEXT
        if OLD_BASELINE_CONTEXT:
            # 🌟 修复 1：只有当旧基线上下文包含有效 URL 或 DOI 时才执行回归测试，避免用全空参数测试新代码引发死锁
            has_valid_baseline_param = bool(OLD_BASELINE_CONTEXT.get("dataset_url") or OLD_BASELINE_CONTEXT.get("doi"))
            if has_valid_baseline_param:
                try:
                    baseline_test = fetcher_method(
                        dataset_name=OLD_BASELINE_CONTEXT.get("dataset_name", ""),
                        dataset_url=OLD_BASELINE_CONTEXT.get("dataset_url", ""),
                        doi=OLD_BASELINE_CONTEXT.get("doi", ""),
                        doi_landing_page=OLD_BASELINE_CONTEXT.get("doi_landing_page", "")
                    )
                    if not isinstance(baseline_test, dict):
                        return "【基线回归测试失败】：你的代码在处理老版本数据集参数时返回类型错误。"
                    
                    # 🌟 修复 2：如果老基线测试报错是因为缺少关键参数，优雅忽略，不打断大模型的新代码验证
                    if "error" in baseline_test:
                        err_str = str(baseline_test["error"])
                        if "缺少关键参数" in err_str or "无法解析" in err_str:
                            pass # ⚠️ 旧基线测试缺少必要参数，跳过强拦截
                        else:
                            return f"【基线回归测试失败 (逻辑被覆盖)】：新代码处理老数据集时报错：{err_str}！请务必保留老版本解析分支！"
                except Exception as e:
                    return f"【致命漏洞 (基线回归测试崩溃)】：新代码处理老数据集参数时抛出了 {type(e).__name__} 异常！\n报错堆栈: {traceback.format_exc()}"

        # ==========================================
        # 正常执行带真实参数的测试
        # ==========================================
        result = fetcher_method(**kwargs_to_pass)
        
        if not isinstance(result, dict) or ("source" not in result and "error" not in result):
            return f"【执行失败】：{target_func_name} 必须返回包含 'source' 和 'data' 的字典，或者包含 'error' 的字典。"
            
        if "error" in result:
            return f"【执行失败 (代码逻辑主动返回错误)】：{result['error']}"

        # ==========================================
        # ⚔️ 杀招二：防张冠李戴 URL 轨迹比对
        # 目的：校验大模型代码实际请求的 URL，是否与其“申报”的 API URL 属于同一个路径体系
        # ==========================================
        from urllib.parse import urlparse
        if declared_api_url and fetcher.called_urls:
            declared_path = urlparse(declared_api_url).path
            
            # 放宽比对标准：只要申报 API 的核心 path 在代码实际请求的 url 列表中出现即可
            import re
            static_prefix = re.split(r'[{<:]', declared_path)[0]
            if static_prefix and static_prefix != "/":
                path_matched = any(static_prefix in urlparse(u).path for u in fetcher.called_urls)
                if not path_matched:
                    return f"【执行成功，但发生严重错位 (张冠李戴)】：\n你申报的最优 API 路径是：{declared_path} (匹配前缀: {static_prefix})\n但你代码实际请求的路径是：{[urlparse(u).path for u in fetcher.called_urls]}\n【致命警告】：两者完全不匹配！这说明你的参数提取逻辑（如 if-else 分支或 \"\" in string）出现严重 Bug，导致抓取了毫无关联的默认数据集！请立刻修改你的提取算法！"
        
        kwargs_str = json.dumps(kwargs_to_pass, ensure_ascii=False)
        return f"【执行成功】\n测试入参: {kwargs_str}\n返回值: {json.dumps(result, ensure_ascii=False)[:1000]}..."
        
    except Exception as e:
        tb_str = traceback.format_exc()
        return f"【代码抛出运行时异常】:\n{tb_str}"

tools = [tavily_search, extract_html_meta, verify_api_endpoint, execute_python_sandbox]

# ==========================================
# 3. 大模型调用逻辑
# ==========================================
def custom_request_llm_invoke(messages, use_tools=False, json_mode=False, custom_tools=None):
    url = "https://ai.zj-computility.com/maas/v1/chat/completions"
    headers = {
        "Authorization": "Bearer sk-5ve6fyd4fyd2ne33",
        "Content-Type": "application/json"
    }
    
    api_messages = []
    for m in messages:
        if isinstance(m, SystemMessage):
            api_messages.append({"role": "system", "content": m.content})
        elif isinstance(m, HumanMessage):
            api_messages.append({"role": "user", "content": m.content})
        elif isinstance(m, AIMessage):
            msg_dict = {"role": "assistant", "content": m.content or ""}
            if "reasoning_content" in m.additional_kwargs:
                msg_dict["reasoning_content"] = m.additional_kwargs["reasoning_content"]
            if hasattr(m, "tool_calls") and m.tool_calls:
                msg_dict["tool_calls"] = [
                    {
                        "id": tc.get("id") or str(uuid.uuid4()),
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["args"]) if isinstance(tc["args"], dict) else tc["args"]
                        }
                    } for tc in m.tool_calls
                ]
            api_messages.append(msg_dict)
        elif type(m).__name__ == "ToolMessage":
            tool_msg_dict = {
                "role": "tool",
                "tool_call_id": getattr(m, "tool_call_id", ""),
                "content": str(m.content)
            }
            if hasattr(m, "name") and m.name:
                tool_msg_dict["name"] = m.name
            api_messages.append(tool_msg_dict)

    payload = {
        "model": "deepseek-v4-pro",
        "messages": api_messages,
        "temperature": 0.0,
        "reasoning_effort": "high",
        "extra_body": {"thinking": {"type": "enabled"}}
    }
    
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
        
    if use_tools:
        active_tools = custom_tools if custom_tools is not None else tools
        payload["tools"] = [convert_to_openai_tool(t) for t in active_tools]
        
    import time
    max_retries = 6
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=120)
            response.raise_for_status()
            break
        except requests.exceptions.RequestException as e:
            logger.info(f"请求大模型接口失败 (尝试 {attempt+1}/{max_retries}): {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.info(f"响应内容: {e.response.text}")
                if e.response.status_code == 429:
                    logger.info("🚦 触发接口限流 (429 Too Many Requests)，等待 30 秒后重试...")
                    time.sleep(30)
                    if attempt == max_retries - 1:
                        raise e
                    continue
            if attempt == max_retries - 1:
                raise e
            time.sleep(5)
        
    data = response.json()
    choice = data["choices"][0]
    msg_data = choice["message"]
    
    content = msg_data.get("content", "")
    reasoning = msg_data.get("reasoning_content", "")
    if not reasoning and msg_data.get("model_extra"):
        reasoning = msg_data.get("model_extra").get("reasoning_content", "")
        
    tool_calls = []
    if "tool_calls" in msg_data and msg_data["tool_calls"]:
        for tc in msg_data["tool_calls"]:
            if tc.get("type") == "function":
                try:
                    args_dict = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    args_dict = {}
                tool_calls.append({
                    "name": tc["function"]["name"],
                    "args": args_dict,
                    "id": tc["id"]
                })
                
    ai_message = AIMessage(
        content=content or "",
        tool_calls=tool_calls,
        additional_kwargs={"reasoning_content": reasoning} if reasoning else {}
    )
    return ai_message

# ==========================================
# 4. LangGraph 节点定义
# ==========================================
SYSTEM_PROMPT = """你是一个资深的地学与计算科学数据馆员和元数据抽取专家。任务：为学术数据平台寻找获取“集合级(Collection-level)”元数据的RESTful API 并编写 Python 抓取代码。

【核心推理链条】
1. 【定位 RESTful API】：使用 `tavily_search` 查找该平台的官方数据集 API 文档（如 "dataset metadata RestFull API"）。
2. 【分析参数】：明确该 API 需要什么参数（如纯数字 ID、内部 UUID 等）。
3. 【挖掘参数】：检查传入的 `dataset_url`、`doi` 、`doi_landing_page`、`dataset_name`。
   - 如果目标 API 需要特殊的内部 ID（如 UUID或者shortname），而你当前只有 `dataset_url`、`doi` 、`doi_landing_page`、`dataset_name`，必须按照以下瀑布流顺序尝试：
     优先从 DOI 解析：如果有 DOI，尝试使用正则提取，或者调用平台的 DOI 转 ID 接口。
     其次从 URL / doi_landing_page正则提取：如果 URL 形如 .../dataset/12345，你必须在代码中写 re.search(r'/dataset/(\d+)', url) 来提取 12345。
     其次从 调用特定的 Search API 把 `URL`/`DOI` 转换为 UUID 等
     最后从网页源码嗅探：调用'extract_html_meta'，并用正则从 HTML 的 <meta> 或 JSON-LD 中提取隐藏 ID！（注意：仅限提取 ID，严禁把网页里的 JSON-LD 直接当成元数据返回！）
    说明该平台对我们是封闭的。请立即停止尝试！ 直接在最终输出中判定 is_verified=False 且 python_code=null，严禁强行编写无法运行的废代码！"
4. 【宁缺毋滥】：如果我传入的 dataset_name 或 dataset_url 指向的是一个【宏观的大型数据库/数据集合】（如 Neotoma Database），而你发现该平台只提供了获取【微观单条数据】（如 某个具体化石采样点）的 API，且没有全库级别的 Catalog API，请果断承认失败并放弃（返回 null）！绝对禁止在网上随便搜一个该库内的微观子数据集 ID 代入测试并糊弄过关！"
5. 【沙箱验证】：使用 `verify_api_endpoint` 探路。确认有效后，编写完整的 `def fetch_{name}(self, **kwargs):` 函数。
6. 【执行沙箱】：通过 `execute_python_sandbox` 运行你写的代码。
    注意：沙箱会自动包装和调用你写的函数，你只需要在参数里提供函数定义，【绝对禁止】在 python_code_str 里写任何用于测试实例化的逻辑（如 MockSelf / print 等），否则会导致生产环境代码污染。


使用 `verify_api_endpoint` 探路测试候选 API 时，必须遵守以下警示法则：
   - 警惕搜索首项陷阱（First-Item Trap）：如果目标是一个宏观/全局数据集，当测试平台的搜索接口时，**严禁测试硬套 `rows=1` 或 `limit=1` 的盲目请求**！如果返回的报文中标题限定了具体的【国家/地方名】，说明发生了子实体错位！
   - 优先探路集合级接口：对于带有组织/集合的平台，优先尝试机构或集合级 API。
   - 见有效 API 即止熔断：一旦 `verify_api_endpoint` 返回了与目标实体颗粒度以及语义完全对齐的 200 OK 结构化元数据，**立刻停止任何二次无意义搜索**（严禁去搜子图层接口），直接进入代码编写阶段！

【代码生成要求（极其重要）】
函数签名必须以 fetch_ 开头：`def fetch_xxx(self, **kwargs):`
- 生产环境唯一可靠入参：
  代码执行时，外部系统只会可靠地提供 `kwargs.get('doi')`、`kwargs.get('dataset_url')`、`kwargs.get('doi_landing_page')` 和 `kwargs.get('dataset_name')`。你绝不能假设外部系统会帮你传入其他的内部 ID (如 uuid, shortname, official_website_id)。

- 【数据入口：参数解析必须多态 (Polymorphic Parsing)】：
  为了保证生产环境的鲁棒性，你【强烈被鼓励】在代码内部编写多条解析路径（if-else 瀑布流）来获取目标 API 所需的内部 ID。
  例如：优先尝试从 `dataset_url` 提取 ID；如果没有，再尝试从 `doi_landing_page` 正则提取；如果还没有，再尝试调用平台原生的 DOI 转 ID 接口。只要这些路径能让【当前测试样例】拿到真实内部 ID 即可。同时，为了防范下游系统未来传入的残缺数据，你的代码必须包含防御性逻辑：if not 最终解析到的ID: return {"error": "缺少关键参数，无法解析出内部 ID"}。
  
- 【数据出口：绝对单一优先 & 严格原汁原味】：
  1. 最终【必须且只能】选择并请求一条最优 API 路径！绝对禁止在代码中编写备用降级逻辑！在选择目标 API 时，你必须严格遵循以下 API 优先级（从高到低）：
     第一优先级（强制首选）：官方标准的最原生、数据最丰富的 RESTful API（特征：URL 路径中通常包含 `/api/`, `/rest/`, `/v1/`, `/v2/` 等微服务路由，例如 `.../rest/metadata/item/{id}/xml`）。
        【生态穿透原则（打破域名执念）】：不要被狭隘的子平台域名死死绑定！许多科研子平台（如具体的观测站、子数据中心）并不自己维护元数据 API，而是将元数据统一托管在上级机构或联盟的中央目录系统（Central Catalog / Registry）中。只要该 API 是数据生产方官方所属生态内的系统，即使域名不同，也【完全合法】，应优先采信其中央目录的 API！发
     第二优先级：底层静态文件直链（特征：直接请求物理服务器上的静态文件，URL 通常以 `.xml` 或 `.json` 结尾，如 `.../published/iso/xml/xxx.xml`）。
     第三优先级（仅作兜底）：Web 网关导出接口（特征：通过在普通的 HTML 网页 URL 后追加 `?format=json` 或 `&view=xml` 等参数，强行让前端页面吐出数据的接口）。

  2. 【绝对原汁原味透传】：
     只要原生 API 返回的是【结构化纯文本数据】（包括但不限于 JSON, XML, YAML, JSONL/NDJSON, RDF/Turtle 等机器可解析格式）：
     - 必须绝对透传！返回 `{"source": "平台名", "format": "[识别到的真实格式(如 json/xml/yaml/turtle)]", "data": response.text 或 response.json()}`。
     - **【严禁】**在代码中对原生数据进行遍历、重命名、清洗或挑选字段！绝不允许手动构建新字典（如 data['title'] = ...）！
     - **【严禁】**使用 ElementTree, BeautifulSoup, 正则表达式等工具对原生结构进行任何二次拆解！把所有的字段解析、清洗工作全部留给下游的数据中台！
  3.如果返回的数据是xml格式，优先尝试iso19139格式，其次iso19115格式，然后再尝试其他

- 【代码内动态映射要求】：
  如果目标 API 需要隐藏的内部 ID，【这种映射逻辑必须完整写进你生成的代码中】！
  (1) 你的代码只能使用 `doi`、`dataset_url`、`doi_landing_page` 或 `dataset_name` 作为起点。
  (2) 在代码内部动态发起前置请求或解析：比如请求 DOI 落地页并用正则提取隐藏 ID，或是调用特定的 Search API 把 `dataset_name` 转换为 UUID 等，手段不限。
  (3) 动态拿到所需的真实内部 ID 后，再用它去拼接并请求最终的数据集元数据 API。

- 发起请求：使用 `self._get_with_retry(url, headers=custom_headers)`

- 【代码生成防御性编程强制宪法】：
  你的代码将在无人值守的高并发环境中运行，必须具备极强的容错性。严禁出现以下新手级别的低级 Bug：
  1. 判空前置：在提取参数（如 url, doi）后，必须立即进行判空处理！严禁对可能为空的变量直接调用 `.split()` 或 `re.search()`。
  2. 严禁空字符串陷阱：绝对禁止使用 `if a in b:` 这种极易产生假阳性的危险写法（当 a 为空字符串 `""` 时条件永远为 True，会导致严重的数据污染）！必须加上真值前置校验，严格写为 `if a and a in b:` 或 `if a == b:`。
  3. JSON 容错：遇到响应报文的 JSON 解析，必须包裹在 `try...except json.JSONDecodeError:` 中，绝不能假定服务器永远返回 JSON。
  4. 列表边界防守：对任何数组/列表进行索引访问（如 `data[0]`）之前，必须确保其非空（如 `if data and len(data) > 0:`）。

【严格约束】
1. **【禁止使用DOI注册机构API获取元数据】**：严禁在代码中使用 `api.datacite.org`、`api.crossref.org`、`doi.org` 等DOI注册机构的API获取元数据。你必须寻找并使用目标数据平台【自己开发和托管】的原生 API！
2. **【禁止直接解析网页充当 API获取元数据】**：严禁从 HTML 源码中提取 `<script type="application/ld+json">` 或 `<meta>` 标签的内容作为最终的元数据结果。我们要的是标准的 RESTful API 接口。
3. **【宁缺毋滥的底线】**：如果你穷尽了全网搜索，发现该原生平台根本没有开放的 JSON/XML 元数据 API，或者无法完成参数的动态映射，**请立即放弃！** 直接返回 `is_verified=False` 和 `python_code=null`。我们宁可该条目为空，也绝对不要爬虫数据或非原生数据！
4. - 【完整代码要求】：绝不允许在生成的代码中使用 `...`、`pass` 或类似 `# 此处省略解析逻辑` 的注释来偷懒省略核心逻辑！你的 `python_code` 必须包含完完整整、可直接执行的代码。你的代码必须是【通用】的！绝不能在代码里写死当前测试用例的特定 ID！
5. **【反作弊纪律】**：沙盒验证和生成的代码，必须且只能针对我传入给你的测试用例进行。绝不允许在网络上随便找一个该平台的其他随机 ID 来糊弄测试！

- 【特例兜底：慎用主从互补多 API 模式 (Master-Slave Composite)】：
  - 触发底线：【仅当】主 API 严重缺失核心学术维度（如只有基本信息，缺失空间坐标），且该平台存在另一个原生 API 提供此数据时，才允许使用此模式。95% 的情况你不需要用到它！
  - 数量红线：绝对不超过 2 个 API（1主 1辅）！严禁拿通用搜索接口或网页源码 HTML 凑数！
  - 强制容错：辅助 API 的请求【必须】被 `try-except` 包裹！若辅助 API 报错，必须只带上主 API 数据正常返回，【绝对禁止】因为辅助 API 获取失败而导致整个 `fetch_xxx` 函数崩溃！
  - 返回格式必须严格写为：
    main_data = self._get_with_retry(main_url).json() # 或 .text
    try:
        aux_data = self._get_with_retry(aux_url, timeout=5).json() # 或 .text
    except Exception as e:
        aux_data = {"error": f"辅助 API 获取失败: {e}"}
    return {
        "source": "平台名",
        "format": "composite",
        "data": {"primary": main_data, "auxiliary": aux_data}
    }
"""

SYSTEM_PROMPT_HEAL = """你是一个资深的地学与计算科学数据馆员和元数据抽取专家。

【本次任务的核心目的】
系统知识库中【已经有一版】针对当前数据平台的老代码，它在处理过去的历史数据集时运作良好。
但是现在发生了一些问题：我们在处理【新的测试样例】时，发现老代码不兼容或抛出了异常。这往往是因为同一个平台针对不同颗粒度（宏观/微观）、不同版本的数据提供了截然不同的 API 路径，或者是平台存在多套 API 路径。
因此，你现在的核心目标是：
1. 探索新知：基于本次传入的【新测试样例】（新的 dataset_url、doi 等），重新调用工具进行网络探索，挖掘出适用于当前新 case 的目标 API。
2. 增量融合 ：在系统提供给你的【旧版代码】基础上进行重构。你必须将针对新 case 探索出的逻辑，通过 if-else 参数解析分支或 try-except 异常捕获，完美整合进老代码中。
3. 记忆留存：绝对不能直接丢弃老逻辑！！非常重要！！你的新代码必须向下兼容老用例，同时支持本次的新用例。强制先尝试老逻辑，except 捕获异常后再走你本次探索出的新逻辑。

【核心推理链条】
1. 【定位 RESTful API】：使用 `tavily_search` 查找适用于新 case 的官方数据集 API 文档。
2. 【分析参数】：明确该 API 需要什么参数（如纯数字 ID、内部 UUID 等）。
3. 【挖掘参数】：检查传入的新 `dataset_url`、`doi` 、`doi_landing_page`、`dataset_name`。
   - 如果目标 API 需要特殊的内部 ID（如 UUID或者shortname），必须按照以下瀑布流顺序尝试：
     优先从 DOI 解析：如果有 DOI，尝试使用正则提取，或者调用平台的 DOI 转 ID 接口。
     其次从 URL / doi_landing_page正则提取：如果 URL 形如 .../dataset/12345，你必须在代码中写 re.search(r'/dataset/(\d+)', url) 来提取 12345。
     其次从 调用特定的 Search API 把 `URL`/`DOI` 转换为 UUID 等
     最后从网页源码嗅探：调用'extract_html_meta'，并用正则从 HTML 的 <meta> 或 JSON-LD 中提取隐藏 ID！（注意：仅限提取 ID，严禁把网页里的 JSON-LD 直接当成元数据返回！）
    说明该平台对我们是封闭的。请立即停止尝试！ 直接在最终输出中判定 is_verified=False 且 python_code=null，严禁强行编写无法运行的废代码！"
4. 【宁缺毋滥】：如果我传入的 dataset_name 或 dataset_url 指向的是一个【宏观的大型数据库/数据集合】（如 Neotoma Database），而你发现该平台只提供了获取【微观单条数据】（如 某个具体化石采样点）的 API，且没有全库级别的 Catalog API，请果断承认失败并放弃（返回 null）！绝对禁止在网上随便搜一个该库内的微观子数据集 ID 代入测试并糊弄过关！"
5. 【沙箱验证】：使用 `verify_api_endpoint` 探路。确认有效后，开始在旧版代码上进行重构。
6. 【执行沙箱】：通过 `execute_python_sandbox` 运行你写的整合版代码。
    注意：沙箱会自动包装和调用你写的函数，你只需要在参数里提供函数定义，【绝对禁止】在 python_code_str 里写任何用于测试实例化的逻辑（如 MockSelf / print 等），否则会导致生产环境代码污染。


使用 `verify_api_endpoint` 探路测试候选 API 时，必须遵守以下警示法则：
   - 警惕搜索首项陷阱（First-Item Trap）：如果目标是一个宏观/全局数据集，当测试平台的搜索接口时，**严禁测试硬套 `rows=1` 或 `limit=1` 的盲目请求**！如果返回的报文中标题限定了具体的【国家/地方名】，说明发生了子实体错位！
   - 优先探路集合级接口：对于带有组织/集合的平台，优先尝试机构或集合级 API。
   - 见有效 API 即止熔断：一旦 `verify_api_endpoint` 返回了与目标实体颗粒度以及语义完全对齐的 200 OK 结构化元数据，**立刻停止任何二次无意义搜索**（严禁去搜子图层接口），直接进入代码编写阶段！


【代码生成要求（极其重要）】
函数签名必须以 fetch_ 开头：`def fetch_xxx(self, **kwargs):`
- 生产环境唯一可靠入参：
  代码执行时，外部系统只会可靠地提供 `kwargs.get('doi')`、`kwargs.get('dataset_url')`、`kwargs.get('doi_landing_page')` 和 `kwargs.get('dataset_name')`。你绝不能假设外部系统会帮你传入其他的内部 ID (如 uuid, shortname, official_website_id)。

- 【数据入口：参数解析必须多态 (Polymorphic Parsing)】：
  代码内部必须编写多条解析路径（if-else 瀑布流）来获取目标 API 所需的内部 ID。
  你的代码必须包含防御性逻辑：if not 最终解析到的ID: return {"error": "缺少关键参数，无法解析出内部 ID"}。
  
- 【数据出口：严格原汁原味透传】：
  1. 你必须严格遵循以下 API 优先级（从高到低）：第一优先级是 RESTful API；第二优先级是底层静态文件直链；第三优先级是 Web 网关导出接口。
  2. 只要原生 API 返回的是【结构化纯文本数据】（JSON, XML, YAML 等）：
     - 必须绝对透传！返回 `{"source": "平台名", "format": "[识别到的真实格式(如 json/xml/yaml/turtle)]", "data": response.text 或 response.json()}`。
     - **【严禁】**在代码中对原生数据进行遍历、重命名、清洗或挑选字段！
     - **【严禁】**使用 ElementTree, BeautifulSoup, 正则表达式等工具对原生结构进行任何二次拆解！把所有的清洗工作全部留给下游！
  3.如果返回的数据是xml格式，优先尝试iso19139格式，其次iso19115格式，然后再尝试其他
  
- 发起请求：使用 `self._get_with_retry(url, headers=custom_headers)`

- 【代码生成防御性编程强制宪法】：
  1. 判空前置：在提取参数（如 url, doi）后，必须立即进行判空处理！严禁对可能为空的变量直接调用 `.split()` 或 `re.search()`。
  2. 严禁空字符串陷阱：绝对禁止使用 `if a in b:`，必须加上真值前置校验，严格写为 `if a and a in b:` 或 `if a == b:`。
  3. JSON 容错：遇到响应报文的 JSON 解析，必须包裹在 `try...except json.JSONDecodeError:` 中。
  4. 列表边界防守：对任何数组/列表进行索引访问之前，必须确保其非空。

【严格约束】
1. **【禁止使用DOI注册机构API获取元数据】**：严禁使用 `api.datacite.org`、`api.crossref.org` 等获取元数据。你必须寻找平台【自己开发和托管】的原生 API！
2. **【禁止直接解析网页充当 API获取元数据】**：严禁从 HTML 源码中提取 JSON-LD 或 meta 标签作为最终结果。我们要的是 RESTful API。
3. **【完整代码要求】**：你的 `python_code` 必须包含完完整整、可直接执行的代码。绝不允许使用 `...` 或 `pass` 省略逻辑！你的代码必须向下兼容，绝不能写死当前测试用例的特定 ID！
4. **【反作弊纪律】**：沙盒验证和生成的代码，必须且只能针对我传入给你的测试用例进行。绝不允许随便找其他 ID 来糊弄测试！
"""

def load_registry():
    if os.path.exists(REGISTRY_FILE):
        try:
            with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_registry(data):
    with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)



def get_actual_python_code(publisher_name, default_code):
    try:
        import os, ast, re
        if not os.path.exists(TARGET_INJECT_FILE):
            return default_code
        with open(TARGET_INJECT_FILE, 'r', encoding='utf-8') as f:
            file_content = f.read()
            
        pattern = rf'["\']{re.escape(publisher_name)}["\']\s*:\s*self\.([a-zA-Z0-9_]+)'
        match = re.search(pattern, file_content)
        if match:
            method_name = match.group(1)
            tree = ast.parse(file_content)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == method_name:
                    return ast.get_source_segment(file_content, node)
        return default_code
    except Exception as e:
        logger.warning(f"无法从注入文件中动态提取旧代码，回退到 registry: {e}")
        return default_code

def check_cache_node(state: AgentState):
    """检查识别出的平台是否已在沉淀知识库中"""
    true_pub = state.get("publisher", "")
    
    registry = load_registry() if not IGNORE_API_CODE_CACHE else {}
    
    import difflib
    import re
    
    def normalize_name(name):
        name = re.sub(r'[^\w\s]', '', name).lower()
        return re.sub(r'\s+', ' ', name).strip()
        
    matched_key = None
    true_pub_norm = normalize_name(true_pub)
    
    for k in registry.keys():
        # 1. 严格不区分大小写匹配
        if k.lower() == true_pub.lower():
            matched_key = k
            break


    # 3. 如果字符串匹配失败，再使用大模型进行语义匹配兜底
    if not matched_key:
        registry_keys = list(registry.keys())
        if registry_keys:
            import json
            prompt = f"""你是一个数据平台名称匹配专家。
当前正在处理的数据存储平台名称是: "{true_pub}"

以下是系统已知的平台名称列表:
{json.dumps(registry_keys, ensure_ascii=False, indent=2)}

请判断当前平台名称是否指代上述列表中的某一个平台。
【匹配规则】：
1. 它们可能名称略有不同（例如 "Zenodo" 与 "CERN Zenodo"，或 "Dryad" 与 "Dryad Digital Repository"）。
2. 如果它们在语义上明显是同一个数据仓库实体，请严格返回已知平台列表中的那一个精确名称。
3. 如果当前平台确实不在列表中，请输出 "NULL"。
【输出要求】：
请只输出匹配到的精确平台名称，或者是 "NULL"。绝对不要输出任何其他多余的文字或解释！
"""
            response = custom_request_llm_invoke([HumanMessage(content=prompt)], use_tools=False)
            matched_str = response.content.strip()
            
            if matched_str in registry:
                logger.info(f"🤖 [大模型语义匹配兜底] 成功将 '{true_pub}' 匹配到已沉淀的 '{matched_str}'")
                matched_key = matched_str
            else:
                logger.info(f"🤖 [大模型语义匹配兜底] '{true_pub}' 未命中已知平台 (LLM判断结果: {matched_str})")
            
    force_test = IGNORE_API_CODE_CACHE
    is_heal_mode = IS_HEAL_MODE
    
    if matched_key and not force_test:
        cached_data = registry[matched_key]
        if is_heal_mode and cached_data.get("is_verified") == True:
            logger.info(f"🎯 命中沉淀知识库，触发【增量自愈模式】！加载平台: {matched_key} 的历史数据。")
            old_python_code = cached_data.get("python_code", "")
            old_python_code = get_actual_python_code(matched_key, old_python_code)
            old_api_attempts = cached_data.get("api_attempts", [])
            old_reasoning_summary = cached_data.get("reasoning_summary", "")
            old_baseline_context = {
                "dataset_name": cached_data.get("dataset_name", ""),
                "dataset_url": cached_data.get("original_domain", ""),
                "doi": cached_data.get("dataset_doi", ""),
                "doi_landing_page": ""
            }
            
            global OLD_BASELINE_CONTEXT
            OLD_BASELINE_CONTEXT = old_baseline_context
            
            new_sys = SystemMessage(content=SYSTEM_PROMPT_HEAL)
            ds_name = state.get('dataset_name', '')
            ds_url = state.get('dataset_url', '')
            ds_doi = state.get('dataset_doi', '')
            doi_landing_page = state.get('doi_landing_page', '')
            error_reason = state.get('error_reason', '')
            
            task_content = f"请寻找目标数据存储平台的元数据获取 API：\n【候选平台名称】：{true_pub}\n"
            task_content += f"【测试样例数据集名称】：{ds_name}\n【测试样例原始链接】：{ds_url}\n"
            if ds_doi:
                task_content += f"【官方明确 DOI】：{ds_doi}\n"
            if doi_landing_page:
                task_content += f"【DOI 解析落地页】：{doi_landing_page}\n"
            if error_reason:
                task_content += f"\n【历史 Badcase 修复任务】之前尝试提取该数据集信息时发生了如下错误/失败原因：{error_reason}。请特别留意并修改你的提取策略，以避免重蹈覆辙。\n"
            task_content += f"\n请从上述新样例中提取目标 API 所需的 ID/参数。同时，以下是该平台的旧版抓取代码，请严格按照 SYSTEM_PROMPT_HEAL 的要求将新旧逻辑融合！\n\n【旧版代码】：\n```python\n{old_python_code}\n```"
            
            new_human = HumanMessage(content=task_content)
            return {
                "is_cached": False, 
                "messages": [new_sys, new_human],
                "old_python_code": old_python_code,
                "old_api_attempts": old_api_attempts,
                "old_reasoning_summary": old_reasoning_summary,
                "old_baseline_context": old_baseline_context
            }

        if cached_data.get("is_verified") == True:
            logger.info(f"🎯 命中沉淀知识库！直接提取平台: {matched_key} 的 API。")
        else:
            logger.info(f"🎯 命中沉淀知识库的【失败记录】！跳过对平台: {matched_key} 的重复探索。")
        return {"is_cached": True, "final_metadata": cached_data}
    else:
        logger.info(f"❌ 未命中沉淀知识库，开始探索: {true_pub} 的 API。")
        new_sys = SystemMessage(content=SYSTEM_PROMPT)
        ds_name = state.get('dataset_name', '')
        ds_url = state.get('dataset_url', '')
        ds_doi = state.get('dataset_doi', '')
        doi_landing_page = state.get('doi_landing_page', '')
        error_reason = state.get('error_reason', '')
        
        task_content = f"请寻找目标数据存储平台的元数据获取 API：\n【候选平台名称】：{true_pub}\n"
        task_content += f"【测试样例数据集名称】：{ds_name}\n【测试样例原始链接】：{ds_url}\n"
        if ds_doi:
            task_content += f"【官方明确 DOI】：{ds_doi}\n"
        if doi_landing_page:
            task_content += f"【DOI 解析落地页】：{doi_landing_page}\n"
        if error_reason:
            task_content += f"\n【历史 Badcase 修复任务】之前尝试提取该数据集信息时发生了如下错误/失败原因：{error_reason}。请特别留意并修改你的提取策略，以避免重蹈覆辙。\n"
        task_content += "请从样例链接、名称或 DOI 中提取目标 API 所需的 ID/参数，编写 Python 抓取代码并验证！"
        
        new_human = HumanMessage(content=task_content)
        return {"is_cached": False, "messages": [new_sys, new_human]}

def route_after_cache(state: AgentState):
    if state.get("is_cached", False):
        return "END"
    else:
        return "researcher"

def save_to_cache_node(state: AgentState):
    final_json = state.get("final_metadata") or {}
    if not final_json.get("has_432_error"):
        registry = load_registry()
        pub_name = state.get("publisher")
        if pub_name:
            # 🌟 增量自愈审核退回：不管以前是否审核过，发生探索后一律重置审核状态
            if "human_audit" in final_json:
                final_json["human_audit"]["is_reviewed"] = False
            else:
                final_json["human_audit"] = {"is_reviewed": False, "auditor_notes": "", "scope_limit": "ITEM_LEVEL_ONLY" if final_json.get("is_verified") else "NONE", "reviewed_at": None}

            # 🌟 草稿与合流逻辑：拦截大模型生成的 python_code，将其转入 draft
            generated_code = final_json.get("python_code")
            old_code = state.get("old_python_code")
            
            if generated_code and generated_code != old_code:
                # 确实产生了新的有效代码
                final_json["draft_python_code"] = generated_code
                final_json["has_pending_draft"] = True
            else:
                final_json["has_pending_draft"] = False
                final_json["draft_python_code"] = None
                
            # 将主 python_code 恢复为原来的生产代码（如果是完全新增的站点，则为 None/空）
            final_json["python_code"] = old_code

            if state.get("old_python_code"):
                # 增量合并历史探索记录
                old_attempts_list = state.get("old_api_attempts", [])
                if isinstance(old_attempts_list, str):
                    try:
                        old_attempts_list = json.loads(old_attempts_list)
                    except:
                        old_attempts_list = []
                new_attempts = final_json.get("api_attempts", [])
                if isinstance(new_attempts, str):
                    try:
                        new_attempts = json.loads(new_attempts)
                    except:
                        new_attempts = []
                merged_attempts = old_attempts_list + new_attempts
                final_json["api_attempts"] = merged_attempts
                
                old_summary = state.get("old_reasoning_summary", "")
                new_summary = final_json.get("reasoning_summary", "")
                final_json["reasoning_summary"] = f"[历史探索]: {old_summary}\n[本次增量自愈探索]: {new_summary}"
                
            registry[pub_name] = final_json
            save_registry(registry)
            if final_json.get("is_verified") == True:
                if state.get("old_python_code"):
                    logger.info(f"💾 已将融合后的 API 代码与追加的尝试记录保存至知识库: {pub_name}")
                else:
                    logger.info(f"💾 已将新验证的 API (带有 Python Code) 强制覆盖/沉淀至知识库: {pub_name}")
            else:
                logger.info(f"💾 已将此平台的探索失败记录写入知识库，避免重复探索: {pub_name}")
    return {}

def research_and_verify_node(state: AgentState):
    messages = state["messages"]
    response = custom_request_llm_invoke(messages, use_tools=True)
    return {"messages": [response]}

def should_continue(state: AgentState):
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return "extract"

def structured_extraction_node(state: AgentState):
    import re
    context = "\n".join([m.content for m in state["messages"] if hasattr(m, "content") and m.content])
    
    # 提取真正的代码：优先从最近一次 execute_python_sandbox 的参数中获取完整代码
    extracted_python_code = None
    # 倒序遍历消息，找到最近的沙盒调用
    for i in range(len(state["messages"]) - 1, -1, -1):
        m = state["messages"][i]
        if hasattr(m, "tool_calls") and m.tool_calls:
            for tc in m.tool_calls:
                if tc.get("name") == "execute_python_sandbox":
                    args = tc.get("args", {})
                    if "python_code_str" in args:
                        extracted_python_code = args["python_code_str"]
                        break
            if extracted_python_code:
                break
    # 若未找到沙盒调用，则回退到正则匹配
    if not extracted_python_code:
        code_matches = re.findall(r'```(?:python)?\s*(.*?)\s*```', context, re.DOTALL)
        if code_matches:
            extracted_python_code = code_matches[-1].strip()

    # --- 拦截并系统级硬抓取 API 尝试记录，防止大模型遗漏 ---
    sys_api_attempts = []
    call_id_to_url = {}
    for m in state["messages"]:
        # 提取发出的工具调用
        if hasattr(m, "tool_calls") and m.tool_calls:
            for tc in m.tool_calls:
                if tc.get("name") == "verify_api_endpoint":
                    call_id_to_url[tc.get("id")] = tc.get("args", {}).get("api_url", "")
        # 匹配工具调用的结果
        if getattr(m, "type", "") == "tool" and getattr(m, "tool_call_id", "") in call_id_to_url:
            url = call_id_to_url[m.tool_call_id]
            res_content = str(getattr(m, "content", ""))
            is_success = "【验证成功" in res_content
            sys_api_attempts.append({
                "api_template": "auto-extracted",
                "test_dataset_id": "auto-extracted",
                "tested_url": url,
                "is_successful": is_success,
                "error_message_or_response": res_content[:200]
            })

    schema_dict = PublisherAPIResult.model_json_schema()
    if "python_code" in schema_dict.get("properties", {}):
        del schema_dict["properties"]["python_code"]
    schema_str = json.dumps(schema_dict, ensure_ascii=False, indent=2)
    
    extraction_prompt = f"""
    基于之前的搜索和验证结果，提取最终的 API 信息。
    注意：无需提取 python_code，它将在代码中由正则独立处理。
    注意：无需关心 api_attempts 的遗漏问题，系统会在底层自动补充完整的 API 测试记录。
    【格式要求】
    你必须输出一段合法的 JSON 字符串，严格符合以下 JSON Schema 结构：
    {schema_str}
    
    收集到的信息：
    {context}
    """
    
    response = custom_request_llm_invoke(
        [
            SystemMessage(content="你是一个数据提取专家，请严格按照 JSON Schema 提取输出。"),
            HumanMessage(content=extraction_prompt)
        ],
        json_mode=True
    )
    
    try:
        raw_json_str = response.content.strip()
        if raw_json_str.startswith("```json"): raw_json_str = raw_json_str[7:]
        if raw_json_str.startswith("```"): raw_json_str = raw_json_str[3:]
        if raw_json_str.endswith("```"): raw_json_str = raw_json_str[:-3]
        
        json_data = json.loads(raw_json_str.strip())
        metadata_obj = PublisherAPIResult(**json_data)
        if extracted_python_code:
            metadata_obj.python_code = extracted_python_code
            
        # 强制覆盖 api_attempts 为系统级无损记录
        if sys_api_attempts:
            metadata_obj.api_attempts = [APIAttempt(**attempt) for attempt in sys_api_attempts]
            
    except Exception as e:
        logger.info(f"[Warning] JSON解析失败: {e}")
        metadata_obj = PublisherAPIResult(publisher_name=state.get("publisher", "Unknown"))
        if extracted_python_code:
            metadata_obj.python_code = extracted_python_code
        if sys_api_attempts:
            metadata_obj.api_attempts = [APIAttempt(**attempt) for attempt in sys_api_attempts]
        
    return {"messages": [response], "final_metadata": metadata_obj.model_dump()}

workflow = StateGraph(AgentState)
workflow.add_node("check_cache", check_cache_node)
workflow.add_node("researcher", research_and_verify_node)
workflow.add_node("tools", ToolNode(tools))
workflow.add_node("extractor", structured_extraction_node)
workflow.add_node("save_cache", save_to_cache_node)

workflow.set_entry_point("check_cache")
workflow.add_conditional_edges("check_cache", route_after_cache, {"END": END, "researcher": "researcher"})
workflow.add_conditional_edges("researcher", should_continue, {"tools": "tools", "extract": "extractor"})
workflow.add_edge("tools", "researcher")
workflow.add_edge("extractor", "save_cache")
workflow.add_edge("save_cache", END)
app = workflow.compile()

# ==========================================
# 5. 主执行逻辑
# ==========================================



def resolve_doi_to_url(doi: str) -> str:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"}
        res = requests.get(f"https://doi.org/{doi}", allow_redirects=True, timeout=15, headers=headers)
        return res.url
    except Exception as e:
        logger.info(f"   ⚠️ [DOI重定向] 解析失败: {e}")
        return ""

def main():
    import sys
    # 🌟 架构升级：在程序刚启动时，强制将本地人工修改的 .py 插件同步回 JSON 注册表！
    # 这确保了老 JSON 不会掩盖人工刚刚修改的心血。
    sync_registry_from_plugins()
    
    if "--generate-only" in sys.argv:
        logger.info("\n🚀 [快速模式] 直接基于 platform_api_registry.json 重新生成插件...")
        generate_plugins_from_registry()
        return

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", type=int, default=0, help="如果 > 0，则仅测试前几个 publisher。否则测试全部。")
    parser.add_argument("--dataset-id", type=str, default="", help="指定测试 45个数据集target_datasets.txt 中的特定 数据集ID")
    parser.add_argument("--heal-file", type=str, default="", help="增量自愈进化模式：输入缺失数据集列表，重构旧API代码。")
    parser.add_argument("--heal-dir", type=str, default="", help="增量自愈进化模式：输入包含 badcase JSON 的文件夹")
    parser.add_argument("--force", action="store_true", help="强制重新生成平台 API 代码，忽略缓存")
    args = parser.parse_args()

    global IGNORE_API_CODE_CACHE, IS_HEAL_MODE
    if args.force:
        IGNORE_API_CODE_CACHE = True
    if args.heal_file or args.heal_dir:
        IS_HEAL_MODE = True

    publisher_samples = []

    if args.heal_dir:
        heal_dir = args.heal_dir
        if not os.path.exists(heal_dir):
            logger.info(f"找不到文件夹 {heal_dir}")
            return
        
        for filename in os.listdir(heal_dir):
            if filename.endswith(".json"):
                file_path = os.path.join(heal_dir, filename)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        # We expect either a list of objects or a single object with an 'input_summary' key
                        items = data if isinstance(data, list) else [data]
                        for item in items:
                            if isinstance(item, dict):
                                summary = item.get("input_summary")
                                original_input = item.get("original_input", {})
                                if summary:
                                    ds_id = filename[:-5] # remove .json
                                    ds_name = summary.get("dataset_name", "未知数据集")
                                    ds_url = summary.get("dataset_url", "未知链接")
                                    ds_desc = original_input.get("dataset_description", "")
                                    publisher_samples.append({
                                        "id": ds_id,
                                        "dataset_name": ds_name,
                                        "dataset_description": ds_desc,
                                        "url": ds_url,
                                        "target_api_name": summary.get("target_api_name", []),
                                        "error_reason": summary.get("error_reason", ""),
                                        "doi_landing_page": summary.get("doi_landing_page", ""),
                                        "doi": summary.get("doi", ""),
                                        "official_website": summary.get("official_websites", "")[0],
                                        "is_incremental_mode": True
                                    })
                except Exception as e:
                    logger.info(f"读取文件 {filename} 失败: {e}")
                    
        if args.dataset_id:
            publisher_samples = [s for s in publisher_samples if str(s["id"].split('-')[0]) == str(args.dataset_id)]
            if not publisher_samples:
                logger.info(f"⚠️ 在文件夹中找不到 数据集ID 为 {args.dataset_id} 的记录。")
                return

    else:
        if args.heal_file:
            input_file = args.heal_file
        else:
            input_file = INPUT_DATASET_FILE
            
        if not os.path.exists(input_file):
            logger.info(f"找不到 {input_file}")
            return

        if input_file.endswith(".json"):
            try:
                with open(input_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        if isinstance(item, dict):
                            summary = item.get("input_summary")
                            if summary:
                                filename = os.path.basename(input_file)
                                ds_id = filename[:-5] # remove .json
                                ds_name = summary.get("dataset_name", "未知数据集")
                                ds_url = summary.get("dataset_url", "未知链接")
                                official_website = summary.get("official_website") or (summary.get("official_websites")[0] if summary.get("official_websites") else "")
                                publisher_samples.append({
                                    "id": ds_id,
                                    "dataset_name": ds_name,
                                    "url": ds_url,
                                    "target_api_name": summary.get("target_api_name", []),
                                    "error_reason": item.get("error_reason", ""),
                                    "doi_landing_page": summary.get("doi_landing_page", ""),
                                    "doi": summary.get("doi", ""),
                                    "official_website": official_website,
                                    "is_incremental_mode": True
                                })
                                print("11111111111",official_website)
            except Exception as e:
                logger.info(f"读取文件失败: {e}")
                return

            if args.dataset_id:
                publisher_samples = [s for s in publisher_samples if str(s["id"].split('-')[0]) == str(args.dataset_id)]
                if not publisher_samples:
                    logger.info(f"⚠️ 在文件中找不到 数据集ID 为 {args.dataset_id} 的记录。")
                    return
        else:
            try:
                df = pd.read_csv(input_file, sep='\t', dtype=str)
            except Exception as e:
                logger.info(f"读取文件失败: {e}")
                return
    
            if args.dataset_id:
                df = df[df.iloc[:, 0].astype(str) == str(args.dataset_id)]
                if df.empty:
                    logger.info(f"⚠️ 在文件中找不到 数据集ID 为 {args.dataset_id} 的记录。")
                    return
                    
            for _, row in df.iterrows():
                if args.heal_file:
                    ds_id = str(row.iloc[0]) if len(row) > 0 else ""
                    ds_name = str(row.iloc[1]) if len(row) > 1 else "未知数据集"
                    ds_desc = str(row.iloc[2]) if len(row) > 2 else ""
                    ds_url = str(row.iloc[3]) if len(row) > 3 else "未知链接"
                else:
                    ds_url = str(row.iloc[3]) if len(row) > 3 else "未知链接"
                    ds_name = str(row.iloc[1]) if len(row) > 1 else "未知数据集"
                    ds_desc = str(row.iloc[2]) if len(row) > 2 else ""
                    ds_id = str(row.iloc[0]) if len(row) > 0 else ""
                    
                ds_id = "" if ds_id == "nan" else ds_id
                ds_name = "" if ds_name == "nan" else ds_name
                ds_desc = "" if ds_desc == "nan" else ds_desc
                ds_url = "" if ds_url == "nan" else ds_url
                
                publisher_samples.append({
                    "id": ds_id,
                    "dataset_name": ds_name,
                    "dataset_description": ds_desc,
                    "url": ds_url
                })
    
    if args.test > 0 and not args.dataset_id:
        publisher_samples = publisher_samples[:args.test]

    results_file = OUTPUT_RESULTS_FILE
    trace_file = OUTPUT_TRACE_FILE

    # 断点续传初始化
    existing_dataset_ids = set()
    all_results = []
    
    if not IGNORE_PROGRESS_CACHE and os.path.exists(results_file):
        try:
            existing_df = pd.read_excel(results_file)
            if 'dataset_id' in existing_df.columns:
                existing_dataset_ids = set(existing_df['dataset_id'].dropna().astype(str).tolist())
                logger.info(f"检测到历史进度，已跳过 {len(existing_dataset_ids)} 个已处理的数据集。")
            all_results = existing_df.to_dict('records')
        except Exception as e:
            logger.info(f"无法读取历史结果文件: {e}")

    all_traces = []
    if os.path.exists(trace_file):
        try:
            with open(trace_file, "r", encoding="utf-8") as f:
                all_traces = json.load(f)
        except Exception as e:
            logger.info(f"无法读取历史日志文件: {e}")

    
    dataset_info_cache = {}
    if USE_DATASET_INFO_CACHE and os.path.exists(dataset_info_cache_file):
        try:
            with open(dataset_info_cache_file, "r", encoding="utf-8") as f:
                dataset_info_cache = json.load(f)
        except Exception as e:
            logger.info(f"无法读取数据集信息缓存文件: {e}")

    for sample in publisher_samples:
        ds_id = sample["id"]
        if ds_id in existing_dataset_ids and not args.dataset_id:
            logger.info(f"⏩ 数据集 {ds_id} 已经处理过，跳过。")
            continue
            
        ds_name = sample["dataset_name"]
        ds_url = sample["url"]
        
        logger.info(f"\n===========================================")
        logger.info(f"正在处理数据集: {ds_name} (ID: {ds_id})")
        logger.info(f"===========================================")
        
        original_url = ds_url
        
        doi_landing_page = sample.get("doi_landing_page", "")
        str_ds_id = str(ds_id)
        print(sample)
        if sample.get("is_incremental_mode"):
            logger.info("🚀 检测到增量自优化模式，跳过 DOI 查找和平台分析流程。")
            extracted_doi = sample.get("doi", "")
            doi_landing_page = sample.get("doi_landing_page", "")
            candidates = [{"name": sample.get("official_website") or "Unknown", "reason": "来自增量自优化的 official_website"}]
        elif USE_DATASET_INFO_CACHE and str_ds_id in dataset_info_cache:
            logger.info("🎯 命中数据集信息缓存，跳过大模型提取流程。")
            extracted_list = dataset_info_cache[str_ds_id]
            extracted_doi = ""
            candidates = []
            
            if extracted_list and len(extracted_list) > 0:
                first_ds = extracted_list[0]
                
                if sample.get("doi"):
                    extracted_doi = sample.get("doi")
                else:
                    extracted_doi = first_ds.get("doi", "")

                if sample.get("doi_landing_page"):
                    doi_landing_page = sample.get("doi_landing_page")
                elif extracted_doi:
                    real_url = resolve_doi_to_url(extracted_doi)
                    if real_url and "doi.org" not in real_url:
                        doi_landing_page = real_url
                
                for ds_info in extracted_list:
                    pub = ds_info.get("official_website")
                    if pub and not any(c["name"] == pub for c in candidates):
                        candidates.append({
                            "name": pub,
                            "reason": f"Unified extraction (version: {ds_info.get('version_name', 'default')})"
                        })
            
            if not candidates:
                 candidates = [{"name": sample.get("official_website") or original_url, "reason": "Unified extraction fallback"}]
                 
        else:
            logger.info("🧠 正在使用统一提取逻辑分析数据集...")
            dataset_info_dict = {
                "dataset_id": ds_id,
                "dataset_name": ds_name,
                "dataset_description": sample.get("dataset_description", ""),
                "url": original_url
            }
            from dataset_extractor import extract_dataset_info
            
            # 使用与 integrated 相同的入口进行提取
            extracted_list = extract_dataset_info(dataset_info_dict, custom_request_llm_invoke)
            
            extracted_doi = ""
            candidates = []
            
            if extracted_list and len(extracted_list) > 0:
                first_ds = extracted_list[0]
                
                # 优先使用 badcase 中的 doi
                if sample.get("doi"):
                    extracted_doi = sample.get("doi")
                    logger.info("🎯 命中 badcase 提供的 DOI。")
                else:
                    extracted_doi = first_ds.get("doi", "")
                    
                # 存入缓存并落盘
                if USE_DATASET_INFO_CACHE:
                    dataset_info_cache[str_ds_id] = extracted_list
                    with open(dataset_info_cache_file, "w", encoding="utf-8") as f:
                        json.dump(dataset_info_cache, f, ensure_ascii=False, indent=2)

                # 重定向
                if sample.get("doi_landing_page"):
                    doi_landing_page = sample.get("doi_landing_page")
                    logger.info(f"🎯 命中 badcase 提供的 doi_landing_page: {doi_landing_page}")
                elif extracted_doi:
                    logger.info(f"💡 发现 DOI: {extracted_doi}，尝试重定向底层 URL...")
                    real_url = resolve_doi_to_url(extracted_doi)
                    if real_url and "doi.org" not in real_url:
                        logger.info(f"✅ DOI 重定向成功，真实链接: {real_url}")
                        doi_landing_page = real_url
                
                # 构建 candidates (过滤重名)
                for ds_info in extracted_list:
                    pubs = ds_info.get("official_websites", [])
                    if isinstance(pubs, str):
                        pubs = [pubs]
                    if "official_website" in ds_info and ds_info["official_website"]:
                        pubs.insert(0, ds_info["official_website"])
                    for pub in pubs:
                        if pub and not any(c["name"] == pub for c in candidates):
                            candidates.append({
                                "name": pub,
                                "reason": f"Unified extraction (version: {ds_info.get('version_name', 'default')})"
                            })
            
            if not candidates:
                 candidates = [{"name": sample.get("official_website") or original_url, "reason": "Unified extraction fallback"}]
            
            target_api_name = sample.get("target_api_name", [])
            if target_api_name:
                filtered_candidates = []
                for c in candidates:
                    c_name = c.get("name", "").lower()
                    if any(t.lower() in c_name or c_name in t.lower() for t in target_api_name):
                        filtered_candidates.append(c)
                candidates = filtered_candidates
                logger.info(f"🎯 使用 badcase 限定平台过滤后，保留 {len(candidates)} 个候选平台。")
            
        logger.info(f"📋 候选平台列表:")
        for idx, c in enumerate(candidates):
            logger.info(f"  {idx+1}. {c.get('name', 'Unknown')} (理由: {c.get('reason', '')})")
            
        dataset_success = False
        dataset_final_result = None
        
        for cand in candidates:
            pub = cand.get("name", "Unknown")
            logger.info(f"\n▶️ 开始探索候选平台: {pub}")
            
            global CURRENT_DATASET_CONTEXT
            CURRENT_DATASET_CONTEXT = {
                "dataset_name": ds_name,
                "dataset_url": ds_url,
                "doi": extracted_doi,
                "publisher": pub,
                "dataset_description": sample.get("dataset_description", ""),
                "search_call_count": 0,
                "search_432_error": False,
                "search_limit_reached": False,
                "error_reason": sample.get("error_reason", "")
            }
            
            initial_state = {
                "messages": [],
                "publisher": pub,
                "dataset_name": ds_name,
                "dataset_url": original_url,
                "dataset_doi": extracted_doi,
                "doi_landing_page": doi_landing_page,
                "is_cached": False,
                "final_metadata": {},
                "error_reason": sample.get("error_reason", "")
            }
            
            trace_log = {"dataset_id": ds_id, "publisher": pub, "steps": []}
            
            try:
                current_state = initial_state.copy()
                for step in app.stream(initial_state):
                    for node_name, state_update in step.items():
                        logger.info(f"\n--- ⚡ 节点执行完毕: {node_name} ---")
                        if state_update is None:
                            continue
                            
                        if "messages" in state_update:
                            current_state["messages"].extend(state_update["messages"])
                        if "final_metadata" in state_update:
                            current_state["final_metadata"] = state_update["final_metadata"]
                            
                        messages = state_update.get("messages", [])
                        latest_msg = messages[-1] if messages else None
                        
                        if node_name == "researcher" and latest_msg:
                            reasoning = latest_msg.additional_kwargs.get("reasoning_content", "")
                            if reasoning:
                                logger.info(f"\n[思考过程]: {reasoning[:300]}...\n")
                                
                            if hasattr(latest_msg, "tool_calls") and latest_msg.tool_calls:
                                logger.info("🧠 [大模型调用工具]:")
                                for tc in latest_msg.tool_calls:
                                    logger.info(f"   🔧 工具: {tc['name']}, 参数: {tc['args']}")
                            else:
                                logger.info("🧠 [大模型决策] 思考完毕，准备抽取。")
                                
                            trace_log["steps"].append({
                                "node": "researcher",
                                "reasoning": reasoning,
                                "content": latest_msg.content,
                                "tool_calls": latest_msg.tool_calls if hasattr(latest_msg, "tool_calls") else []
                            })
                                
                        elif node_name == "tools" and latest_msg:
                            content_preview = str(latest_msg.content)[:300] + "..." if len(str(latest_msg.content)) > 300 else str(latest_msg.content)
                            logger.info(f"🛠️ [工具返回]:\n   📤 {content_preview}")
                            trace_log["steps"].append({
                                "node": "tools",
                                "tool_name": getattr(latest_msg, "name", "unknown_tool"),
                                "tool_call_id": getattr(latest_msg, "tool_call_id", ""),
                                "result": latest_msg.content
                            })
                        
                if current_state.get("final_metadata"):
                    final_json = current_state["final_metadata"].copy()
                    final_json["original_domain"] = ds_url
                    final_json["true_publisher"] = pub
                    final_json["publisher_name"] = pub 
                    final_json["dataset_id"] = ds_id
                    final_json["has_432_error"] = CURRENT_DATASET_CONTEXT.get("search_432_error")
                    final_json["has_reached_search_limit"] = CURRENT_DATASET_CONTEXT.get("search_limit_reached")
                    
                    if "api_attempts" in final_json and isinstance(final_json["api_attempts"], list):
                        final_json["api_attempts"] = json.dumps(final_json["api_attempts"], ensure_ascii=False, indent=2)
                        
                    trace_log["steps"].append({"node": "final_output", "extracted": final_json})
                    all_traces.append(trace_log)
                    
                    if final_json.get("is_verified"):
                        dataset_success = True
                        dataset_final_result = final_json
                        break
            except Exception as e:
                import traceback
                logger.info(f"探索 {pub} 时发生错误: {e}")
                traceback.print_exc()

        if dataset_success and dataset_final_result:
            all_results.append(dataset_final_result)
            logger.info(f"🎉 数据集 {ds_id} 在平台 {dataset_final_result.get('publisher_name')} 上成功找到可用 API！停止探索更低优先级的平台。")
        else:
            logger.info(f"❌ 数据集 {ds_id} 的所有候选平台均未找到可用的宏观元数据 API。")
            all_results.append({
                "dataset_id": ds_id,
                "publisher_name": "无符合要求平台",
                "is_verified": False,
                "reasoning_summary": "遍历了所有候选平台，均未找到支持获取宏观集合元数据的 API。"
            })

        existing_dataset_ids.add(ds_id)
        
        results_df = pd.DataFrame(all_results)
        try:
            results_df.to_excel(results_file, index=False)
        except PermissionError:
            alt_name = results_file.replace(".xlsx", "_temp.xlsx")
            results_df.to_excel(alt_name, index=False)
            
        with open(trace_file, "w", encoding="utf-8") as f:
            json.dump(all_traces, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 数据集 {ds_id} 处理完成，已增量保存。")

    logger.info(f"\n✅ 所有数据集处理完成！")
    
    # 最后，基于已沉淀的注册表自动生成请求代码
    try:
        logger.info("\n🚀 正在自动生成/更新 API 抓取代码至独立的插件文件 ...")
        generate_plugins_from_registry()
    except Exception as e:
        logger.info(f"⚠️ 自动生成代码失败: {e}")

def generate_plugins_from_registry(force_override=False):
    """
    治本落盘逻辑：将 platform_api_registry.json 导出为独立插件。
    双轨制设计：
    1. 生成生产代码 fetchers/fetch_xxx.py
    2. 如果存在待审核草稿，生成 drafts/fetch_xxx.py 和 diffs/fetch_xxx.diff
    """
    import os, re, json, urllib.parse, glob, difflib
    registry = load_registry()
    fetchers_dir = os.path.join("code_result", "fetchers")
    drafts_dir = os.path.join(fetchers_dir, "drafts")
    diffs_dir = os.path.join(fetchers_dir, "diffs")
    
    os.makedirs(fetchers_dir, exist_ok=True)
    os.makedirs(drafts_dir, exist_ok=True)
    os.makedirs(diffs_dir, exist_ok=True)

    for pub_name, data in registry.items():
        if not data.get('is_verified') and not data.get('has_pending_draft'):
            continue

        clean_name = re.sub(r'[^a-zA-Z0-9]', '_', pub_name).lower()
        method_name = f"fetch_{clean_name}"
        domain = data.get("original_domain", "")
        netloc = urllib.parse.urlparse(domain).netloc.lower().replace("www.", "")
        aliases = []
        if netloc: aliases.append(netloc)
        
        prod_file = os.path.join(fetchers_dir, f"fetch_{clean_name}.py")
        
        # 1. 生产代码 (如果存在)
        if data.get('python_code'):
            raw_code = data['python_code'].strip()
            match_code = re.search(r'```(?:python)?\s*(.*?)\s*```', raw_code, re.DOTALL)
            if match_code:
                raw_code = match_code.group(1).strip()
            raw_code = re.sub(r'^\s*def\s+[^\(]+\(', f'def {method_name}(', raw_code, count=1, flags=re.MULTILINE)
            
            prod_content = f"""# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for {pub_name}
from code_result.fetcher_decorator import register_api

@register_api(publisher="{pub_name}", aliases={json.dumps(aliases, ensure_ascii=False)})
{raw_code}
"""
            
            existing_prod = ""
            if os.path.exists(prod_file):
                with open(prod_file, 'r', encoding='utf-8') as f:
                    existing_prod = f.read()
            if existing_prod != prod_content:
                with open(prod_file, 'w', encoding='utf-8') as f:
                    f.write(prod_content)
                logger.info(f"✅ 成功生成/同步生产插件: {prod_file}")

        # 2. 生成草稿代码与差异对比 (如果有草稿)
        if data.get('has_pending_draft') and data.get('draft_python_code'):
            draft_file = os.path.join(drafts_dir, f"fetch_{clean_name}.py")
            diff_file = os.path.join(diffs_dir, f"fetch_{clean_name}.diff")
            
            raw_code = data['draft_python_code'].strip()
            match_code = re.search(r'```(?:python)?\s*(.*?)\s*```', raw_code, re.DOTALL)
            if match_code:
                raw_code = match_code.group(1).strip()
            raw_code = re.sub(r'^\s*def\s+[^\(]+\(', f'def {method_name}(', raw_code, count=1, flags=re.MULTILINE)
            
            draft_content = f"""# -*- coding: utf-8 -*-
# AI-Generated/Audited Plugin for {pub_name}
from code_result.fetcher_decorator import register_api

@register_api(publisher="{pub_name}", aliases={json.dumps(aliases, ensure_ascii=False)})
{raw_code}
"""
            
            with open(draft_file, 'w', encoding='utf-8') as f:
                f.write(draft_content)
                
            current_prod = ""
            if os.path.exists(prod_file):
                with open(prod_file, 'r', encoding='utf-8') as f:
                    current_prod = f.read()
            
            if current_prod != draft_content:
                prod_lines = current_prod.splitlines(keepends=True) if current_prod else []
                draft_lines = draft_content.splitlines(keepends=True)
                diff = list(difflib.unified_diff(
                    prod_lines, draft_lines,
                    fromfile=f"a/{os.path.basename(prod_file)}",
                    tofile=f"b/{os.path.basename(draft_file)}",
                    n=3
                ))
                
                if diff:
                    with open(diff_file, 'w', encoding='utf-8') as f:
                        f.writelines(diff)
                    logger.info(f"\n🚨 [AI 自愈成功 - 待人工审核] 发现平台 [{pub_name}] 的代码变更！")
                    logger.info(f"   - 生产当前文件: {prod_file}")
                    logger.info(f"   - AI 建议补丁: {draft_file}")
                    logger.info(f"   - 变更差异对比: {diff_file}")
                    logger.info(f"   👉 审核完毕后，请运行: python sync_drafts.py --approve fetch_{clean_name}\n")

    sync_registry_from_plugins()

def sync_registry_from_plugins():
    """
    反向同步工具：扫描 code_result/fetchers/*.py 文件，
    自动更新 platform_api_registry.json，确保人工手写/精修的代码 100% 被知识库识别为 is_verified=True。
    """
    import os, glob, re
    registry = load_registry()
    fetchers_dir = os.path.join("code_result", "fetchers")
    if not os.path.exists(fetchers_dir):
        return

    plugin_files = glob.glob(os.path.join(fetchers_dir, "fetch_*.py"))
    for p_file in plugin_files:
        try:
            with open(p_file, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # 提取 publisher 名称
            match_pub = re.search(r'@register_api\(\s*publisher=["\']([^"\']+)["\']', content)
            if match_pub:
                pub_name = match_pub.group(1)
                # 提取函数源码
                match_code = re.search(r'(def fetch_[a-zA-Z0-9_]+\s*\(.*)', content, re.DOTALL)
                if match_code:
                    code_str = match_code.group(1).strip()
                    if pub_name not in registry:
                        registry[pub_name] = {}
                    
                    registry[pub_name]["publisher_name"] = pub_name
                    registry[pub_name]["python_code"] = f"```python\n{code_str}\n```"
                    registry[pub_name]["is_verified"] = True  # 🌟 强制将人工修改/新增的代码标记为 Verified!
                    registry[pub_name]["reasoning_summary"] = "由人工精修/插件反向同步成功"
        except Exception as e:
            logger.warning(f"反向同步文件 {p_file} 失败: {e}")

    save_registry(registry)
    logger.info("🔄 已成功将 code_result/fetchers/ 下的所有插件状态反向同步至 platform_api_registry.json")

if __name__ == "__main__":
    main()
