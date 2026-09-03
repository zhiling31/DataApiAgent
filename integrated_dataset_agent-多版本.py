# -*- coding: utf-8 -*-
from fetch_publisher_api import workflow
import os
import json
from typing import TypedDict, Annotated, List, Optional
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
import requests
from bs4 import BeautifulSoup

# ==========================================
# 0. 全局配置 (文件路径修改区)
# ==========================================
# 你可以在这里修改所有的输入输出文件路径
INPUT_DATASET_FILE = "../45个数据集target_datasets.txt"       # 输入的原始数据集文件 (制表符分隔)
OUTPUT_RESULTS_DIR = "agent_results0804"                     # 运行结果(成功或报错的 JSON)的保存目录
MISSING_REGISTRY_FILE = "agent_results0804/missing_registry_datasets.txt"  # 未命中知识库的数据集保存文件
API_FALLBACK_LOG_FILE = "agent_results0804/api_fallback_errors.log"            # 多API尝试时，中间失败的日志
REGISTRY_API_LOG_FILE = "agent_results0804/registry_api_errors.log"            # 注册机构(doi.org, DataCite, Crossref)的报错日志
MAX_RECORDS_TO_PROCESS = 10                               # 每次批量测试的最大数量
STRICT_RESUME_MODE = False                               # 续传模式: False=只要有1个成功版就跳过; True=只要有报错版(或全错)就必须重跑
MAX_SEARCH_ITERATIONS = 35                               # 大模型检索的最大循环思考次数 (默认25，值过大会增加死循环和Token爆炸的风险)
INTEGRATED_FETCHER_MODULE = "output0728.fetch_top_dataset_integrated"  # 动态导入抓取脚本的模块路径，方便后续更新

import logging
import sys

# ==========================================
# Logger Configuration
# ==========================================
os.makedirs(OUTPUT_RESULTS_DIR, exist_ok=True)
logger = logging.getLogger('DatasetAgent')
logger.setLevel(logging.INFO)
# Avoid adding handlers multiple times if module is reloaded
if not logger.handlers:
    fh = logging.FileHandler(os.path.join(OUTPUT_RESULTS_DIR, 'batch_process.log'), encoding='utf-8')
    fh.setLevel(logging.INFO)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    logger.addHandler(fh)
    logger.addHandler(ch)


# ==========================================
# 1. 导入已有工具模块
# ==========================================
import importlib
IntegratedDataRepoFetcher = importlib.import_module(INTEGRATED_FETCHER_MODULE).IntegratedDataRepoFetcher
from fetch_datacite_metadata import fetch_from_datacite, fetch_from_crossref, fetch_with_retry

# 从 agent_doi 直接复用大模型调用、Tavily工具及网页抓取工具
from langchain_core.tools import tool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_tavily import TavilySearch
import uuid
import os
# 配置 Tavily API Key
# "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"
# zhizhi333333@gmail.com           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
# 2524258132@qq.com    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

os.environ["TAVILY_API_KEY"] = "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"

web_search_tool = TavilySearch(
    max_results=5,
    include_answer=True,
    search_depth="advanced"
)


@tool
def academic_web_search(query: str) -> str:
    """
    【发现工具】用于全网关键词检索，寻找未知的标杆论文或数据托管平台。
    使用场景：当不知道具体的链接或 DOI 时使用。
    使用技巧：
    - 找论文可附加关键词示例: "Data Descriptor" OR "Methodology" OR "article"
    - 找数据本体可附加关键词示例: "Data Repository" OR "DOI" OR "Zenodo" OR "PANGAEA"
    """
    try:
        result = web_search_tool.invoke({"query": query})
        result_str = str(result)
        logger.info(f"Tavily search result (first 100 chars): {result_str[:100]}")
        if "Error 432: This request exceeds your plan's set usage limit" in result_str:
            logger.error(f"Encountered 432 error: {result_str}. Exiting program.")
            import sys
            sys.exit(1)
        return result
    except Exception as e:
        return f"搜索失败: {str(e)}"

@tool
def read_and_verify_url(url_or_doi: str) -> str:
    """
    【精准阅读与验证工具】用于解析具体的 URL 网页内容，或验证 DOI 是否真实存在并指向数据。
    使用场景：
    1. 用户在初始描述中提供了具体的链接（如 ESSD/Nature 文章页），使用此工具提取网页内文（特别是类似于 Data Availability 的段落）。
    2. 需要验证某个 10.xxxx/xxxx 格式的 DOI 是否是合法的数据本体链接时，传入 https://doi.org/10.xxxx/xxxx 进行验证。
    """
    # ----------------- Content Negotiation 补丁 开始 -----------------
    # 修改时间: 2026-06-01
    # 修改原因: 原始逻辑使用简单的 requests 抓取落地页，遇到 Zenodo 等强 WAF 站点会直接返回 403 Forbidden。
    # 现改为：识别为 DOI 时，优先使用 DOI Content Negotiation (Accept: application/vnd.citationstyles.csl+json) 
    # 直接向 doi.org 获取干净的结构化 JSON 元数据，避免网页抓取；普通 URL 则回退到原逻辑。
    
    # 提取纯粹的 DOI 字符串
    import re
    doi = ""
    # 尝试正则提取标准 DOI 格式
    doi_match = re.search(r'(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)', url_or_doi)
    if doi_match:
        doi = doi_match.group(1)
    # # 专门处理 Zenodo 链接 (支持普通网页和 API 链接)
    # elif "zenodo.org" in url_or_doi:
    #     record_id = re.search(r'records?/(\d+)', url_or_doi)
    #     if record_id:
    #         doi = f"10.5281/zenodo.{record_id.group(1)}"
        
    if doi:
        # 使用 DOI Content Negotiation 优雅地获取元数据，不触发目标网站(如Zenodo)的反爬虫
        try:
            headers = {
                "Accept": "application/vnd.citationstyles.csl+json",
                "User-Agent": "DataLibrarianAgent/1.0"
            }
            response = requests.get(f"https://doi.org/{doi}", headers=headers, timeout=10, allow_redirects=True)
            response.raise_for_status()
            
            data = response.json()
            summary = [
                f"【DOI 验证成功 (Content Negotiation)】: {doi}",
                f"标题 (Title): {data.get('title', 'N/A')}",
                f"类型 (Type): {data.get('type', 'N/A')}",
                f"发布者 (Publisher): {data.get('publisher', 'N/A')}",
                f"落地页 URL: {data.get('URL', 'N/A')}",
                f"摘要 (Abstract): {str(data.get('abstract', 'N/A'))[:1500]}" 
            ]
            return "\n".join(summary)
            
        except requests.exceptions.RequestException as e:
            # 如果 DOI 解析失败，继续尝试当做普通 URL 抓取
            pass

    
    # 自动补全普通 URL 协议 (用于兜底的普通网页抓取)
    if not url_or_doi.startswith("http"):
        if url_or_doi.startswith("10."):
            url_or_doi = f"https://doi.org/{url_or_doi}"
        else:
            url_or_doi = f"https://{url_or_doi}"
            
    # ----------------- 本地 CDP 浏览器复用 补丁 开始 -----------------
    # 修改时间: 2026-06-01 17:15
    # 修改原因: 传统的 requests 库无法渲染现代 SPA/CSR 网页 (如 HuggingFace)，导致抓取到的都是无用骨架代码。
    # 现改为使用 Playwright 通过 CDP 协议 (Chrome DevTools Protocol) 寄生并复用本地正在运行的 Chrome 浏览器 (需开启 9222 端口)。
    # 这样不仅能完美渲染 JavaScript，还能利用本地浏览器真实的指纹和 Cookie 彻底绕过验证码和 WAF 拦截。
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            # 尝试连接本地开着 debug 端口的 Chrome
            browser = p.chromium.connect_over_cdp("http://127.0.0.1:9223")
            default_context = browser.contexts[0]
            page = default_context.new_page()
            # 设置较长的超时以应对复杂的页面加载
            page.goto(url_or_doi, timeout=60000, wait_until="domcontentloaded")
            # 拿到渲染后的纯文本
            text = page.locator("body").inner_text()
            page.close()
            browser.close()
            
            # 清理多余的空白符
            import re
            text = re.sub(r'\s+', ' ', text).strip()
            
            return f"【CDP 网页抓取成功】(截取了前10000字符):\n{text[:10000]}"
            # if "data availability" in text.lower():
            #     idx = text.lower().find("data availability")
            #     # start = max(0, idx - 1000)
            #     # end = min(len(text), idx + 3000)
            #     start = max(0, idx - 2000)
            #     end = min(len(text), idx + 8000)
            #     return f"【CDP 网页抓取成功】(截取了包含Data availability声明的片段):\n{text[start:end]}"
            # else:
            #     # return f"【CDP 网页抓取成功】(截取了前4000字符):\n{text[:4000]}"
            #     return f"【CDP 网页抓取成功】(截取了前10000字符):\n{text[:10000]}"
                
    except Exception as e:
        # 记录报错，如果是连接失败，提示用户开启 Chrome 的 debugging 端口
        logger.error(f"无法使用 CDP 连接本地浏览器进行验证。请确保已使用 '--remote-debugging-port=9222' 启动了 Chrome。详细报错: {str(e)}")
        return f"无法使用 CDP 连接本地浏览器进行验证。请确保已使用 '--remote-debugging-port=9222' 启动了 Chrome。详细报错: {str(e)}"
    
        
    # 旧代码：
    # try:
    #     headers = {
    #         "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    #     }
    #     response = requests.get(url_or_doi, headers=headers, timeout=15, allow_redirects=True)
    #     response.raise_for_status()
    #     
    #     soup = BeautifulSoup(response.text, 'html.parser')
    #     for script in soup(["script", "style", "nav", "footer"]):
    #         script.decompose()
    #         
    #     text = soup.get_text(separator=' ', strip=True)
    #     
    #     if "data availability" in text.lower():
    #         idx = text.lower().find("data availability")
    #         start = max(0, idx - 1000)
    #         end = min(len(text), idx + 3000)
    #         return f"【网页抓取成功】(截取了包含Data availability声明的片段):\n{text[start:end]}"
    #     else:
    #         return f"【网页抓取成功】(截取了前4000字符):\n{text[:4000]}"
    #         
    # except requests.exceptions.RequestException as e:
    #     return f"无法访问该URL进行验证，错误信息: {str(e)}。请尝试使用 academic_web_search 工具搜索相关信息。"
    # ----------------- 本地 CDP 浏览器复用 补丁 结束 -----------------
    # ----------------- Content Negotiation 补丁 结束 -----------------

# Agent 可用的工具列表
tools = [academic_web_search, read_and_verify_url]


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
                        "id": tc.get("id", str(uuid.uuid4())),
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["args"])
                        }
                    } for tc in m.tool_calls
                ]
            api_messages.append(msg_dict)
        elif type(m).__name__ == "ToolMessage":
            api_messages.append({
                "role": "tool",
                "tool_call_id": getattr(m, "tool_call_id", ""),
                "content": str(m.content)
            })

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
        tools_to_use = custom_tools if custom_tools is not None else tools
        payload["tools"] = [convert_to_openai_tool(t) for t in tools_to_use]
        
    import time
    max_retries = 6
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=120)
            response.raise_for_status()
            break
        except requests.exceptions.RequestException as e:
            logger.error(f"请求大模型接口失败 (尝试 {attempt+1}/{max_retries}): {e}")
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
    if "error" in data:
        raise Exception(f"大模型 API 返回了错误信息: {data['error']}")
    if "choices" not in data or len(data["choices"]) == 0:
        raise Exception(f"大模型 API 返回的数据格式异常 (无 choices 字段): {data}")
        
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
# ----------------- 手动补丁 (Request 接口改写) 结束 -----------------

class DatasetInfo(BaseModel):
    doi: Optional[str] = Field(description="官方 DOI (10.xxxx/xxxx)，若无明确本体DOI则返回 null", default=None)
    dataset_url: Optional[str] = Field(description="数据集原始链接", default=None)
    doi_landing_page: Optional[str] = Field(description="DOI 解析落地页", default=None)
    dataset_name: Optional[str] = Field(description="数据集名称", default=None)
    version_name: Optional[str] = Field(description="该数据集的具体版本号或年份标识 (例如: '2024', 'v1.2', 'Collection 2')，用于区分同名数据集的不同历史快照，若无则返回 null", default=None)
    
    official_website: Optional[str] = Field(description="数据集官网或托管平台名称 (例如: Zenodo, PANGAEA, ScienceDB, OSTI, GBIF等)，若无则返回 null", default=None)


class DiscoveredVersion(BaseModel):
    version_name: str = Field(description="历史版本名称或年度快照名称")
    hint_url: Optional[str] = Field(description="该版本对应的链接或出处线索", default=None)
    context_info: Optional[str] = Field(description="该版本在检索过程中发现的任何有用上下文或识别特征", default=None)

class DiscoveredVersionList(BaseModel):
    discovered_versions: List[DiscoveredVersion] = Field(description="发现的数据集主版本列表")

class DatasetExtractionList(BaseModel):
    datasets: List[DatasetInfo] = Field(description="基于收集到的所有信息，提取出匹配的数据集版本。如果该数据集存在历年迭代的不同版本，请务必在数组中穷尽列出所有找到的历史版本。")

class TargetApiMatch(BaseModel):
    target_api_name: List[str] = Field(
        description=IntegratedDataRepoFetcher.get_api_schema_desc() + "【语义生态穿透匹配】：请利用你的图情专业知识，判断当前数据集的托管机构或系统简称是否属于上述列表中的某个机构。如果是，请把列表中的准确名称提取出来；如果毫无关联，再返回空列表 []。记住，不用强行越界匹配"
    )

def match_target_api_with_llm(dataset_info: dict, custom_request_llm_invoke) -> List[str]:
    """使用大模型根据提取的数据集信息匹配目标 API"""
    schema_str = json.dumps(TargetApiMatch.model_json_schema(), ensure_ascii=False, indent=2)
    prompt = f"""
你需要根据以下数据集的基本信息，匹配最适合的 API 爬虫。

【数据集信息】
- 名称: {dataset_info.get("dataset_name", "未知")}
- 官网/托管平台: {dataset_info.get("official_website", "未知")}
- URL: {dataset_info.get("dataset_url", "未知")}
- DOI: {dataset_info.get("doi", "未知")}

请严格按照以下 JSON Schema 输出：
{schema_str}
"""
    messages = [
        SystemMessage(content="你是一个专业的图情学数据生态专家。请严格按照要求进行匹配，并返回符合 JSON Schema 的 JSON 对象。"),
        HumanMessage(content=prompt)
    ]
    try:
        response = custom_request_llm_invoke(messages, use_tools=False, json_mode=True)
        content = response.content
        data = json.loads(content)
        return data.get("target_api_name", [])
    except Exception as e:
        logger.error(f"API 匹配 LLM 调用失败: {e}")
        return []

# ==========================================
# 2. Graph 状态定义
# ==========================================
class AgentState(TypedDict):
    # Discovery Phase States
    dataset_id: str                               # 当前处理的数据集ID
    messages: Annotated[List, lambda x, y: x + y] # 用于第一阶段版本发现的消息历史
    dataset_description: str                      # 🌟 专用字段：严格隔离存储当前数据集的描述文本
    discovered_versions: List[dict]               # 由 discovery_extractor 填充的版本列表

    # Deep Dive Phase States
    current_version_idx: int                      # 指向当前正在挖掘的版本的索引
    version_messages: List                        # 专属于当前挖掘版本的独立消息历史

    # Output States
    extracted_datasets: List[dict]                # 最终提取出的 DatasetInfo 列表
    final_results: List[dict]                     # 经过 API 验证后的最终结果

# ==========================================
# 3. Graph 节点实现
# ==========================================

# ----------------------------------
# Phase 1: 发现节点 (Discovery Nodes)
# ----------------------------------
def discovery_researcher(state: AgentState):
    logger.info("⚡ [节点: 发现-检索] 正在全网搜索目标数据集的所有版本...")
    
    # 构建发现提示词，插入到最前面
    original_input = state.get("dataset_description", "Unknown Dataset")
    prompt = f"""
    
    你的任务是调查用户提供的数据集的目标版本或者所有历史主干版本/主快照。，你可以使用网页搜索(academic_web_search)和网页阅读工具(read_and_verify_url)收集信息。
    你只需要找到历史版本号和对应网址，不需要深入寻找每个版本的具体元数据。

    【重要规则】
    如果以下【原始用户请求】中明确指定了某个版本，请**只提取该目标版本**，无需浪费时间去搜索其他无关版本。
    如果用户没有提及具体版本，请穷尽搜索能找到的所有官方标准版本/历史主快照（如系列数据集的每一个年度版本）

    【原始用户请求】：
    {original_input}
    """
    # 因为 LangGraph messages 是累加的，我们在最后再加一个系统提示，强迫模型
    current_msgs = state["messages"] + [SystemMessage(content=prompt)]
    response = custom_request_llm_invoke(current_msgs, use_tools=True)
    return {"messages": [response]}

def discovery_should_continue(state: AgentState):
    search_tool_count = 0
    for m in state["messages"]:
        if hasattr(m, "tool_calls") and m.tool_calls:
            for tc in m.tool_calls:
                if tc.get("name") == "academic_web_search":
                    search_tool_count += 1
    
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        if search_tool_count > MAX_SEARCH_ITERATIONS:
            logger.warning(f"   ⚠️ [发现阶段] 达到搜索上限 ({MAX_SEARCH_ITERATIONS}次)，强制终止。")
            return "discovery_extractor"
            
        logger.info(f"   🔧 [发现阶段] 决定调用工具 (共 {len(last_message.tool_calls)} 个) [累计: {search_tool_count}/{MAX_SEARCH_ITERATIONS}]:")
        for tc in last_message.tool_calls:
            args = tc.get('args', {})
            if tc['name'] == 'academic_web_search':
                logger.info(f"      - 🔍 搜索关键词: {args.get('query')}")
            elif tc['name'] == 'read_and_verify_url':
                logger.info(f"      - 📖 阅读网页: {args.get('url_or_doi')}")
            else:
                logger.info(f"      - ⚙️ {tc['name']}: {args}")
        return "tools"
        
    return "discovery_extractor"

def discovery_extractor(state: AgentState):
    logger.info("⚡ [节点: 发现-提取] 正在总结找到的版本列表...")
    context = "\\n".join([m.content for m in state["messages"] if hasattr(m, "content") and m.content])
    schema_str = json.dumps(DiscoveredVersionList.model_json_schema(), ensure_ascii=False, indent=2)
    original_input = state.get("dataset_description", "Unknown Dataset")
    
    prompt = f"""
你是一个资深的数据科学家。需要提取用户输入的数据集的所有版本或者指定版本

【重要规则】
如果以下【原始用户请求】中明确指定了某个版本，请**只提取该目标版本**。
如果用户没有提及具体版本，请提取能找到的所有官方标准版本/历史主快照（如系列数据集的每一个年度版本）

【原始用户请求】：
{original_input}

【格式要求】
你必须输出合法的 JSON 字符串，符合以下 JSON Schema 结构：
{schema_str}
不要输出任何解释性文本。

【上下文】：
{context}
"""
    response = custom_request_llm_invoke([HumanMessage(content=prompt)], json_mode=True)
    
    raw_json = response.content.strip()
    if raw_json.startswith("```json"): raw_json = raw_json[7:]
    if raw_json.startswith("```"): raw_json = raw_json[3:]
    if raw_json.endswith("```"): raw_json = raw_json[:-3]
    
    try:
        json_data = json.loads(raw_json.strip())
        validated = DiscoveredVersionList(**json_data)
        discovered_versions = [d.model_dump() for d in validated.discovered_versions]
    except Exception as e:
        logger.warning(f"⚠️ 解析版本列表失败: {e}")
        discovered_versions = []
        
    logger.info(f"   ➤ 共发现 {len(discovered_versions)} 个版本目标: {[v.get('version_name') for v in discovered_versions]}")
    
    # 🌟 将 Phase 1 的结果持久化保存为中间缓存
    dataset_id = state.get("dataset_id", "unknown")
    cache_file = os.path.join(OUTPUT_RESULTS_DIR, f"{dataset_id}_versions.json")
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(discovered_versions, f, ensure_ascii=False, indent=2)
        logger.info(f"   💾 中间版本缓存已保存至: {cache_file}")
    except Exception as e:
        logger.warning(f"   ⚠️ 无法保存中间缓存: {e}")
    
    # 彻底隔离，清空 version_messages
    return {
        "discovered_versions": discovered_versions,
        "current_version_idx": 0,
        "version_messages": [] 
    }

# ----------------------------------
# Phase 2: 深度挖掘节点 (Deep Dive Nodes)
# ----------------------------------
def deep_dive_router(state: AgentState):
    discovered = state.get("discovered_versions", [])
    idx = state.get("current_version_idx", 0)
    if idx < len(discovered):
        return "version_researcher"
    return "fetcher"

def version_researcher(state: AgentState):
    idx = state.get("current_version_idx", 0)
    versions = state.get("discovered_versions", [])
    target = versions[idx]
    
    v_name = target.get("version_name", "Unknown")
    v_hint = target.get("hint_url", "Unknown")
    v_ctx = target.get("context_info", "")
    
    original_input = state.get("dataset_description", "Unknown Dataset")
    
    # 如果 version_messages 为空，说明是新开的循环，注入初始 Prompt
    current_msgs = state.get("version_messages", [])
    if not current_msgs:
        logger.info(f"\n   🎯 [节点: 挖掘-检索] 开始专注深挖版本 [{idx+1}/{len(versions)}]: 【所属数据集上下文 / 原始请求】：{original_input} 【当前专注的版本】：{v_name}【线索网址】：{v_hint}，【辅助信息】：{v_ctx}")
        prompt = f"""
你是一个严谨的学术数据馆员。你的唯一任务：为指定的单一版本寻找官方原生 DOI (10.xxxx/xxxx) 

【所属数据集上下文 / 原始请求】：
{original_input}

【当前专注的特定版本】：{v_name}
【线索网址】：{v_hint}
【辅助信息】：{v_ctx}

请使用 read_and_verify_url 读取线索网址{v_hint}找到DOI，或者只针对【{v_name}{v_hint}】构造精准搜索词（如："{v_name}" DOI ）。找到 DOI 或确认没有后即可结束。绝不能关注其他无关数据集！
"""

        current_msgs = [SystemMessage(content=prompt)]
        
    # 调用模型
    response = custom_request_llm_invoke(current_msgs, use_tools=True)
    updated_msgs = current_msgs + [response]
    return {"version_messages": updated_msgs}

def version_should_continue(state: AgentState):
    # 限制单个版本的搜索次数（更小一点以节省时间，比如 3 次）
    search_tool_count = 0
    msgs = state.get("version_messages", [])
    for m in msgs:
        if hasattr(m, "tool_calls") and m.tool_calls:
            for tc in m.tool_calls:
                if tc.get("name") == "academic_web_search":
                    search_tool_count += 1
    
    last_message = msgs[-1] if msgs else None
    if last_message and hasattr(last_message, "tool_calls") and last_message.tool_calls:
        if search_tool_count > 5:
            logger.warning(f"   ⚠️ [深度挖掘] 达到搜索上限，强制终止。")
            return "version_extractor"
            
        logger.info(f"   🔧 [挖掘阶段] 决定调用工具 (共 {len(last_message.tool_calls)} 个) [累计: {search_tool_count}/5]:")
        for tc in last_message.tool_calls:
            args = tc.get('args', {})
            if tc['name'] == 'academic_web_search':
                logger.info(f"      - 🔍 搜索关键词: {args.get('query')}")
            elif tc['name'] == 'read_and_verify_url':
                logger.info(f"      - 📖 阅读网页: {args.get('url_or_doi')}")
            else:
                logger.info(f"      - ⚙️ {tc['name']}: {args}")
        return "version_tools"
        
    return "version_extractor"

def version_extractor(state: AgentState):
    idx = state.get("current_version_idx", 0)
    versions = state.get("discovered_versions", [])
    target = versions[idx]
    v_name = target.get("version_name", "Unknown")
    logger.info(f"⚡ [节点: 挖掘-提取] 正在提取 {v_name} 的元数据...")
    
    current_version_msgs = state.get("version_messages", [])
    context = "\n".join([m.content for m in current_version_msgs if hasattr(m, "content") and m.content])
    schema_str = json.dumps(DatasetInfo.model_json_schema(), ensure_ascii=False, indent=2)
    
    prompt = f"""
请在下述文本中，为你当前唯一的目标版本【{v_name}】提取详细元数据。
你必须像侦探一样抠出它的原生 DOI！(如果出现10.xxxx/xxxx格式，务必提取)。

【格式要求】
你必须输出合法的 JSON 字符串，严格符合以下 JSON Schema 结构：
{schema_str}

【上下文】：
{context}
"""
    response = custom_request_llm_invoke([HumanMessage(content=prompt)], json_mode=True)
    
    raw_json = response.content.strip()
    if raw_json.startswith("```json"): raw_json = raw_json[7:]
    if raw_json.startswith("```"): raw_json = raw_json[3:]
    if raw_json.endswith("```"): raw_json = raw_json[:-3]
    
    extracted_datasets = state.get("extracted_datasets", [])
    try:
        json_data = json.loads(raw_json.strip())
        validated = DatasetInfo(**json_data)
        ds_dict = validated.model_dump()
        ds_dict["target_api_name"] = match_target_api_with_llm(ds_dict, custom_request_llm_invoke)
        extracted_datasets.append(ds_dict)
        logger.info(f"   ✅ {v_name} 提取成功 (DOI: {validated.doi})")
    except Exception as e:
        logger.warning(f"⚠️ {v_name} 提取失败: {e}")
        
    # 清空 version_messages 以便下一个版本使用纯净环境，进入下一循环
    return {
        "extracted_datasets": extracted_datasets,
        "current_version_idx": idx + 1,
        "version_messages": None # 覆盖清空
    }

# ----------------------------------

def resolve_doi_to_url(doi: str) -> str:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"}
        res = requests.get(f"https://doi.org/{doi}", allow_redirects=True, timeout=15, headers=headers)
        return res.url
    except Exception as e:
        logger.error(f"  {doi} ⚠️ [DOI重定向] 解析失败: {e}")
        return ""

def fetch_metadata_node(state: AgentState):
    """根据提取到的信息，循环分别调用三个工具获取所有版本的元数据"""
    logger.info("⚡ [节点: 抓取] 开始从各大 API 获取元数据...")
    raw_extracted_datasets = state.get("extracted_datasets", [])
    
    # 提前解析 doi_landing_page 并按参数去重，保留最新版本
    grouped_datasets = {}
    for ds in raw_extracted_datasets:
        doi = ds.get("doi")
        if doi:
            real_url = resolve_doi_to_url(doi)
            if real_url:
                ds["doi_landing_page"] = real_url
                
        key = (
            str(ds.get("dataset_name") or "").strip().lower(),
            str(ds.get("dataset_url") or "").strip().lower(),
            str(ds.get("doi") or "").strip().lower(),
            str(ds.get("doi_landing_page") or "").strip().lower()
        )
        if key not in grouped_datasets:
            grouped_datasets[key] = []
        grouped_datasets[key].append(ds)
        
    extracted_datasets = []
    for key, group in grouped_datasets.items():
        if len(group) > 1:
            versions = [ds.get("version_name") for ds in group]
            logger.warning(f"   ⚠️ [WARNING] 发现 {len(group)} 个版本具有完全相同的核心参数 (名称/URL/DOI/落地页)。")
            logger.info(f"      涉及的版本有: {versions}")
            logger.info(f"      请人工检查！为避免重复请求，已自动挑选 version 排序最新的版本进行抓取。")
            group_sorted = sorted(group, key=lambda x: str(x.get("version_name") or ""), reverse=True)
            extracted_datasets.append(group_sorted[0])
        else:
            extracted_datasets.append(group[0])
    
    final_results = []
    
    for idx, extracted_info in enumerate(extracted_datasets):
        doi = extracted_info.get("doi")
        
        publisher = extracted_info.get("official_website")
        target_api = extracted_info.get("target_api_name")
        version_name = extracted_info.get("version_name")
        
        display_name = ""
        if version_name:
            display_name = f"版本 {version_name}"
            
        logger.info(f"\n   🔄 [版本 {idx+1}/{len(extracted_datasets)}] 开始抓取流程" + (f" ({display_name})" if display_name else "") + "...")
        logger.info(f"      - DOI: {doi}")
        logger.info(f"      - 官网: {publisher}")
        logger.info(f"      - 目标API: {target_api}")
        
        doi_org_data = {}
        datacite_crossref_data = {}
        official_api_data = {}
    
        # [1] 抓取 doi.org
        if doi:
            logger.info(f"   👉 [doi.org] 请求 DOI: {doi}")
            headers = {"Accept": "application/vnd.citationstyles.csl+json", "User-Agent": "DataLibrarianAgent/4.0"}
            res, err = fetch_with_retry(f"https://doi.org/{doi}", headers=headers, max_retries=3)
            if err:
                doi_org_data = {"error": err}
                import datetime
                with open(REGISTRY_API_LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] DOI: {doi} | Registry: doi.org | ERROR: {err}\n")
            elif res and res.status_code == 200:
                try:
                    doi_org_data = {"source": "doi.org (CSL-JSON)", "data": res.json()}
                    logger.info("      ✅ 成功")
                except Exception as e:
                    doi_org_data = {"error": f"JSON解析错误: {e}"}
                    import datetime
                    with open(REGISTRY_API_LOG_FILE, "a", encoding="utf-8") as f:
                        f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] DOI: {doi} | Registry: doi.org | ERROR: JSON Parse Error {e}\n")
            else:
                status = res.status_code if res else "Unknown"
                doi_org_data = {"error": f"HTTP {status}"}
                import datetime
                with open(REGISTRY_API_LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] DOI: {doi} | Registry: doi.org | ERROR: HTTP {status}\n")
            
        # [2] 抓取 DataCite / Crossref
        if doi:
            logger.info(f"   👉 [DataCite/Crossref] 请求 DOI: {doi}")
            meta, err = fetch_from_datacite(doi)
            if meta:
                datacite_crossref_data = {"source": "DataCite", "data": meta}
                logger.info("      ✅ DataCite 成功")
            else:
                if err:
                    import datetime
                    with open(REGISTRY_API_LOG_FILE, "a", encoding="utf-8") as f:
                        f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] DOI: {doi} | Registry: DataCite | ERROR: {err}\n")
                meta2, err2 = fetch_from_crossref(doi)
                if meta2:
                    datacite_crossref_data = {"source": "Crossref", "data": meta2}
                    logger.info("      ✅ Crossref 成功")
                else:
                    datacite_crossref_data = {"error": f"DataCite error: {err} | Crossref error: {err2}"}
                    if err2:
                        import datetime
                        with open(REGISTRY_API_LOG_FILE, "a", encoding="utf-8") as f:
                            f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] DOI: {doi} | Registry: Crossref | ERROR: {err2}\n")

        # [3] 抓取 官网 API
        target_apis = []
        if target_api:
            if isinstance(target_api, list):
                target_apis = target_api
            elif isinstance(target_api, str):
                target_apis = [target_api]

        if publisher and target_apis:
            logger.info(f"   👉 [官网 API] 智能匹配到插件列表: {target_apis} ...")
            fetcher = IntegratedDataRepoFetcher()
            route_map = fetcher.get_route_map()
        
            success = False
            all_errors = []
            for api_name in target_apis:
                logger.info(f"      ▶ 尝试 API: {api_name}")
                matched_func = route_map.get(api_name)
            
                if not matched_func:
                    err_msg = f"未找到 '{api_name}' 的生成代码"
                    logger.warning(f"      ⚠️ {err_msg}")
                    all_errors.append(err_msg)
                    import datetime
                    with open(API_FALLBACK_LOG_FILE, "a", encoding="utf-8") as f:
                        f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] DOI: {doi} | API: {api_name} | ERROR: {err_msg}\n")
                    continue
                
                try:
                    official_api_data = matched_func(**extracted_info)
                        
                    if "error" in official_api_data:
                        raw_error = official_api_data['error']
                        import re
                        raw_error = re.sub(r'，[^，]*兜底.*', '', raw_error)
                        err_msg = raw_error
                        all_errors.append(err_msg)
                        logger.warning(f"      ⚠️ API 报错: {err_msg}")
                        import datetime
                        with open(API_FALLBACK_LOG_FILE, "a", encoding="utf-8") as f:
                            f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] DOI: {doi} | API: {api_name} | ERROR: {err_msg}\n")
                    else:
                        logger.info(f"      ✅ 官网抓取调用完成 (使用 {api_name})")
                        success = True
                        break # 成功命中并获取数据，跳出循环
                except ValueError as e:
                    err_msg = str(e)
                    all_errors.append(err_msg)
                    logger.warning(f"      ⚠️ 参数不足: {err_msg}")
                    import datetime
                    with open(API_FALLBACK_LOG_FILE, "a", encoding="utf-8") as f:
                        f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] DOI: {doi} | API: {api_name} | ERROR: {err_msg}\n")
                except Exception as e:
                    err_msg = str(e)
                    all_errors.append(err_msg)
                    logger.warning(f"      ⚠️ 调用异常: {err_msg}")
                    import datetime
                    with open(API_FALLBACK_LOG_FILE, "a", encoding="utf-8") as f:
                        f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] DOI: {doi} | API: {api_name} | ERROR: {err_msg}\n")
                
            if not success:
                official_api_data = {"error": " | ".join(all_errors)}
                logger.warning(f"      ⚠️ API 调用失败: {official_api_data['error']}")
                
        # 组装当前版本的结果
        final_result = {
            "input_summary": extracted_info,
            "metadata_sources": {
                "doi_org": doi_org_data,
                "datacite_crossref": datacite_crossref_data,
                "official_api": official_api_data
            }
        }
        final_results.append(final_result)
        
    return {"final_results": final_results}

# ==========================================
# 4. 构建 LangGraph 流程
# ==========================================
def build_agent():
    workflow = StateGraph(AgentState)
    
    # 注册节点
    workflow.add_node("discovery_researcher", discovery_researcher)
    workflow.add_node("discovery_tools", ToolNode(tools))
    workflow.add_node("discovery_extractor", discovery_extractor)
    
    workflow.add_node("version_researcher", version_researcher)
    version_tool_node = ToolNode(tools, messages_key="version_messages")
    workflow.add_node("version_tools", version_tool_node)

    workflow.add_node("version_extractor", version_extractor)
    
    workflow.add_node("fetcher", fetch_metadata_node)
    
    # 流程编排
    def route_entry(state: AgentState):
        if state.get("discovered_versions"):
            return "version_researcher"
        return "discovery_researcher"
        
    workflow.set_conditional_entry_point(
        route_entry,
        {"version_researcher": "version_researcher", "discovery_researcher": "discovery_researcher"}
    )
    
    workflow.add_conditional_edges("discovery_researcher", discovery_should_continue, {"tools": "discovery_tools", "discovery_extractor": "discovery_extractor"})
    workflow.add_edge("discovery_tools", "discovery_researcher")
    
    # 加入路由逻辑
    workflow.add_conditional_edges("discovery_extractor", deep_dive_router, {"version_researcher": "version_researcher", "fetcher": "fetcher"})
    
    workflow.add_conditional_edges("version_researcher", version_should_continue, {"version_tools": "version_tools", "version_extractor": "version_extractor"})
    workflow.add_edge("version_tools", "version_researcher")
    
    # version_extractor 执行完，切回路由器判断是否有下一个版本
    workflow.add_conditional_edges("version_extractor", deep_dive_router, {"version_researcher": "version_researcher", "fetcher": "fetcher"})
    
    workflow.add_edge("fetcher", END)
    
    return workflow.compile()

# ==========================================
# 5. 批量测试与日志输出
# ==========================================
import os
import sys
import datetime
import traceback

if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

def process_target_datasets(target_id=None, use_cache=False):
    # 确保输出目录存在
    output_dir = OUTPUT_RESULTS_DIR
    os.makedirs(output_dir, exist_ok=True)
    
    log_file = os.path.join(output_dir, "batch_process.log")
    if not os.path.exists(INPUT_DATASET_FILE):
        logger.error(f"❌ 找不到输入文件: {INPUT_DATASET_FILE}")
        return
        
    with open(INPUT_DATASET_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    header_line = ""
    # 去除表头并保存
    if len(lines) > 0 and "数据集ID" in lines[0]:
        header_line = lines[0]
        lines = lines[1:]
        
    # 限制处理数量 (如果是单测模式，则不截断)
    if not target_id:
        lines = lines[:MAX_RECORDS_TO_PROCESS]
    
    for line in lines:
        line = line.strip()
        if not line: continue
        parts = line.split('\t')
        if len(parts) < 2: continue
        
        dataset_id = parts[0]
        
        # 如果指定了单测 ID，跳过其他数据
        if target_id and dataset_id != str(target_id):
            continue
            
        dataset_name = parts[1]
        
        # 断点续传逻辑更新：检查是否存在以该 dataset_id- 开头的 JSON 文件
        import glob
        existing_files = glob.glob(os.path.join(output_dir, f"{dataset_id}-*.json"))
        success_files = [f for f in existing_files if not f.endswith("_error.json") and not f.endswith("_crash.json")]
        error_files = [f for f in existing_files if f.endswith("_error.json") or f.endswith("_crash.json")]
        
        should_skip = False
        if STRICT_RESUME_MODE:
            # 严格模式：只有全成功（没有 error/crash 文件）且至少有一个成功文件时才跳过
            if len(success_files) > 0 and len(error_files) == 0:
                should_skip = True
        else:
            # 宽松模式（默认）：只要有一个版本提取成功，就算作成功，跳过整个数据集
            if len(success_files) > 0:
                should_skip = True
                
        if should_skip:
            logger.info(f"⏩ 数据集 ID: {dataset_id} 已满足跳过条件 (成功:{len(success_files)}个, 失败/崩溃:{len(error_files)}个)，跳过处理。")
            continue
            
        # 如果不跳过（即需要重跑），则自动删掉历史的错误或崩溃文件，保持目录干净
        if len(error_files) > 0:
            logger.info(f"♻️ 准备重新处理数据集 ID: {dataset_id}，正在清理 {len(error_files)} 个历史错误记录...")
            for ef in error_files:
                try:
                    os.remove(ef)
                except Exception as e:
                    pass
            
        logger.info(f"--------------------------------------------------")
        logger.info(f"⚡ 开始处理数据集 ID: {dataset_id} | 名称: {dataset_name}")
        
        # 🌟 修复跨数据集污染和 Token 爆炸：每次循环重新构建全新的图实例
        app = build_agent()
        
        test_input = f"【目标数据集描述】\n{line}\n请先搜搜这篇数据，并确认具体信息后再提取。"
        
        system_prompt = """你是一个资深的数据科学家。
你的任务是调查用户提供的数据集描述，你可以使用网页搜索(academic_web_search)和网页阅读工具(read_and_verify_url)收集信息。
【核心纪律】：请优先阅读数据集的官方介绍页。绝对避免反复阅读整篇长达数十页的期刊论文，这会导致上下文超限崩溃！你只需要粗略搜索版本名和DOI即可。
【版本处理规则】：如果用户在描述或URL中明确指定了某个特定版本（如年份、Revision号等），请专门调查该指定版本，该版本为目标版本，不需要再去搜索其他版本；如果用户没有提及具体版本，请穷尽搜索其所有版本的 DOI 和官网信息，把能找到的所有官方标准版本/历史主快照（如系列数据集的每一个年度版本）全查清，这些版本均为目标版本，一个都不漏。
同时，重点留意目标版本的 DOI，务必准确收集到其对应的 DOI 并保留。
收集足够信息后，停止调用工具，流程将自动进入结构化提取节点。"""
        
        initial_state = {
            "dataset_id": dataset_id,
            "messages": [
                SystemMessage(content=system_prompt),
                HumanMessage(content=test_input)
            ],
            "dataset_description": line,
            "discovered_versions": [],
            "extracted_datasets": [],
            "final_results": []
        }
        
        if use_cache:
            cache_file = os.path.join(output_dir, f"{dataset_id}_versions.json")
            if os.path.exists(cache_file):
                try:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        cached_versions = json.load(f)
                    initial_state["discovered_versions"] = cached_versions
                    logger.info(f"   🚀 读取到中间缓存 {cache_file}，直接跳过版本发现阶段 (发现 {len(cached_versions)} 个版本)。")
                except Exception as e:
                    logger.warning(f"   ⚠️ 缓存读取失败，降级重新检索: {e}")
        
        try:
            # 运行 LangGraph，强制加上递归深度限制，为了配合 MAX_SEARCH_ITERATIONS 限制大模型特定工具，这里我们将底层步数设大。
            # 增大 recursion_limit 以支持双阶段多版本循环 (20+ 版本 x 每个版本5步 = 100+ 步)
            final_state = app.invoke(initial_state, config={"recursion_limit": 1000})
            final_results = final_state.get("final_results", [])
            
            if not final_results:
                logger.warning(f"⚠️ 提取失败: 未找到任何数据集版本")
                continue
                
            for idx, final_metadata in enumerate(final_results):
                # 注入初始输入的参数
                final_metadata["original_input"] = {
                    "dataset_name": parts[1] if len(parts) > 1 else "",
                    "url": parts[3] if len(parts) > 3 else ""
                }
                
                input_summary = final_metadata.get("input_summary", {})
                
                # 优先使用 DOI 作为后缀，确保绝对唯一；如果没有则降级使用版本名
                doi_str = input_summary.get("doi")
                version_name = input_summary.get("version_name")
                
                if doi_str and doi_str.strip():
                    raw_suffix = doi_str.strip()
                elif version_name and version_name.strip():
                    raw_suffix = f"version_{version_name.strip()}"
                else:
                    raw_suffix = f"v{idx+1}"
                    
                # 清理后缀中的特殊字符（DOI中的斜杠会被替换为下划线）
                import re
                suffix = re.sub(r'[\\/*?:"<>|]', '_', str(raw_suffix))
                
                # 判断是否成功：如果有 official_api 且没有 error
                api_meta = final_metadata.get("metadata_sources", {}).get("official_api", {})
                has_error = "error" in api_meta if isinstance(api_meta, dict) else False
                
                # 判断是否属于“未命中沉淀知识库”
                is_missing_registry = False
                if not api_meta:
                    is_missing_registry = True
                elif has_error and "未找到" in str(api_meta.get("error", "")):
                    is_missing_registry = True
                
                if not has_error and api_meta:
                    success_file = os.path.join(output_dir, f"{dataset_id}-{suffix}.json")
                    with open(success_file, "w", encoding="utf-8") as f:
                        json.dump(final_metadata, f, ensure_ascii=False, indent=2)
                    logger.info(f"✅ 处理成功！已保存至 {success_file}")
                else:
                    error_file = os.path.join(output_dir, f"{dataset_id}-{suffix}_error.json")
                    with open(error_file, "w", encoding="utf-8") as f:
                        json.dump(final_metadata, f, ensure_ascii=False, indent=2)
                    
                    if is_missing_registry:
                        logger.warning(f"⚠️ 未命中官网知识库 API，已保存至 {error_file}，并追加到 {MISSING_REGISTRY_FILE}")
                        missing_file = MISSING_REGISTRY_FILE
                        # 确保如果写入多个缺失版本，原始文本行也能被追加（这里统一记录该行）
                        # 如果文件不存在，写入表头
                        if not os.path.exists(missing_file) and header_line:
                            with open(missing_file, "w", encoding="utf-8") as f:
                                f.write(header_line.strip() + "\t内部版本标识\t提取到的版本号\t缺失的官网名称(提取值)\t提取的DOI\n")
                        # 实时追加
                        missing_publisher = input_summary.get("official_website") or "Unknown"
                        missing_doi = input_summary.get("doi") or "NULL"
                        extracted_version = input_summary.get("version_name") or "Unknown"
                        
                        with open(missing_file, "a", encoding="utf-8") as f:
                            f.write(f"{line}\t[{suffix}]\t{extracted_version}\t{missing_publisher}\t{missing_doi}\n")
                    else:
                        logger.warning(f"⚠️ 官网API请求报错，已保存至 {error_file}")
                
        except Exception as e:
            error_msg = f"系统异常: {str(e)}\n{traceback.format_exc()}"
            logger.error(f"❌ 运行崩溃: {error_msg}")
            error_file = os.path.join(output_dir, f"{dataset_id}_crash.json")
            with open(error_file, "w", encoding="utf-8") as f:
                json.dump({"error_traceback": error_msg}, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="批量处理数据集")
    parser.add_argument("--id", type=str, help="指定要单独测试的数据集ID", default=None)
    parser.add_argument("--use-cache", action="store_true", help="若开启，优先读取本地保存的版本列表缓存(若存在)，跳过第一阶段的重新检索")
    args = parser.parse_args()
    
    process_target_datasets(target_id=args.id, use_cache=args.use_cache)
