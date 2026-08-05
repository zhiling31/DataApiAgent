# -*- coding: utf-8 -*-
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
INTEGRATED_FETCHER_MODULE = "output0728.fetch_top_dataset_integrated_0728"  # 动态导入抓取脚本的模块路径，方便后续更新

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
        return web_search_tool.invoke({"query": query})
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

    # 以下为被保留的原始抓取逻辑：
    # 旧代码:
    # # 自动补全 DOI 链接
    # if url_or_doi.startswith("10."):
    #     url_or_doi = f"https://doi.org/{url_or_doi}"
    #     
    # try:
    #     # 使用真实的浏览器 User-Agent 防止被简单的反爬虫拦截
    #     headers = {
    #         "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    #     }
    #     # 允许重定向（这对于验证 doi.org 非常重要，它会重定向到真实的 Zenodo/PANGAEA 页面）
    #     response = requests.get(url_or_doi, headers=headers, timeout=10, allow_redirects=True)
    #     response.raise_for_status()
    #     
    #     # 简单的 HTML 文本提取
    #     soup = BeautifulSoup(response.text, 'html.parser')
    #     
    #     # 清理掉 script, style 等无用标签
    #     for script in soup(["script", "style", "nav", "footer"]):
    #         script.decompose()
    #         
    #     text = soup.get_text(separator=' ', strip=True)
    #     
    #     # 为了防止大模型 Context 爆炸，截取前 4000 个字符（通常包含摘要和数据可用性声明）
    #     # 如果是学术文章，"Data availability" 通常在靠后的位置，我们可以做个简单的关键词嗅探
    #     if "data availability" in text.lower():
    #         # 尝试找到包含数据可用性的部分，保留上下文
    #         idx = text.lower().find("data availability")
    #         start = max(0, idx - 1000)
    #         end = min(len(text), idx + 3000)
    #         return f"【网页抓取成功】(截取了包含Data availability声明的片段):\n{text[start:end]}"
    #     else:
    #         return f"【网页抓取成功】(截取了前4000字符):\n{text[:4000]}"
    #         
    # except requests.exceptions.RequestException as e:
    #     return f"无法访问该URL进行验证，错误信息: {str(e)}。请尝试使用 academic_web_search 工具搜索相关信息。"
    
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
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
            default_context = browser.contexts[0]
            page = default_context.new_page()
            # 设置较长的超时以应对复杂的页面加载
            page.goto(url_or_doi, timeout=20000, wait_until="domcontentloaded")
            # 拿到渲染后的纯文本
            text = page.locator("body").inner_text()
            extracted_meta_dict = page.evaluate('''() => {
            const metaData = {};
            
            // 1. 定义常见的学术前缀
            const validPrefixes = ['citation_', 'dc.', 'dc:', 'dcterms.', 'dcterms:', 'prism.', 'og:'];
            
            // 2. 定义核心关键词
            const targetKeywords = ['doi', 'identifier', 'title', 'publisher', 'date', 'issued', 'creator', 'author', 'site_name', 'url', 'version', 'type'];
            
            document.querySelectorAll('meta').forEach(m => {
                const name = (m.getAttribute('name') || m.getAttribute('property') || '').toLowerCase();
                const content = m.getAttribute('content');
                
                if (!content) return;
                
                // 判定规则：只要符合“学术前缀开头”或者“包含核心关键词”
                const isAcademicPrefix = validPrefixes.some(p => name.startsWith(p));
                const hasKeyword = targetKeywords.some(k => name.includes(k));
                
                if (isAcademicPrefix && hasKeyword) {
                    // 如果同一个 key 出现多次（如多个作者），存为数组
                    if (metaData[name]) {
                        if (Array.isArray(metaData[name])) {
                            metaData[name].push(content);
                        } else {
                            metaData[name] = [metaData[name], content];
                        }
                    } else {
                        metaData[name] = content;
                    }
                }
            });
            
            // 3. 提取 JSON-LD 元数据 (保持不变)
            document.querySelectorAll('script[type="application/ld+json"]').forEach(s => {
                try {
                    const data = JSON.parse(s.textContent);
                    if (data.identifier) metaData['jsonld_identifier'] = JSON.stringify(data.identifier);
                    if (data.name || data.title) metaData['jsonld_title'] = data.name || data.title;
                    if (data.doi) metaData['jsonld_doi'] = data.doi;
                } catch(e) {}
            });
            
            return metaData;
        }''')
            page.close()
            browser.close()
            
            # 清理多余的空白符
            import re
            text = re.sub(r'\s+', ' ', text).strip()
            
            # 3. 组装成清晰的双层 Context 给大模型判断
            header_summary = "\n".join([f"  - {k}: {v}" for k, v in extracted_meta_dict.items()])
            full_context = f"""【网页头部结构化元数据 (Header Meta & JSON-LD)】:
            {header_summary if header_summary else "  (未提取到标准学术 Meta 标签)"}
            【网页正文内容 (Body Snippet)】:
            {text[:10000]}
            """
            return full_context
                
    except Exception as e:
        # 记录报错，如果是连接失败，提示用户开启 Chrome 的 debugging 端口
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


def custom_request_llm_invoke(messages, use_tools=False, json_mode=False):
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
        payload["tools"] = [convert_to_openai_tool(t) for t in tools]
        
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
    target_api_name: Optional[List[str]] = Field(
        description=IntegratedDataRepoFetcher.get_api_schema_desc() + " 语义生态穿透匹配】：请利用你的图情专业知识，判断当前数据集的托管机构或系统简称是否属于上述列表中的生态。如果是，请把列表中的准确名称提取出来；如果毫无关联，再返回空列表 []。",
        default=None
    )

class DatasetExtractionList(BaseModel):
    datasets: List[DatasetInfo] = Field(description="基于收集到的所有信息，提取出匹配的数据集版本。如果该数据集存在历年迭代的不同版本，请务必在数组中穷尽列出所有找到的历史版本。")

# ==========================================
# 2. Graph 状态定义
# ==========================================
class AgentState(TypedDict):
    messages: Annotated[List, lambda x, y: x + y] # 用于 ReAct 循环的消息历史
    extracted_datasets: List[dict]    # LLM 提取出来的 DatasetInfo 列表
    final_results: List[dict]         # 最终抓取并组装好的所有版本的 JSON 列表

# ==========================================
# 3. Graph 节点实现
# ==========================================

# ----------------------------------
# (1) 智能体检索节点 (使用全网搜索与工具)
# ----------------------------------
def research_and_verify_node(state: AgentState):
    """复用 agent_doi 的检索节点：使用 LLM 决定是否调用工具进行信息收集"""
    logger.info("⚡ [节点: 检索] 大模型正在思考是否需要使用全网搜索或抓取工具...")
    messages = state["messages"]
    # 开启工具调用
    response = custom_request_llm_invoke(messages, use_tools=True)
    return {"messages": [response]}

def should_continue(state: AgentState):
    """判断是否需要继续调用工具，还是进入信息提取节点"""
    # 专门统计调用 academic_web_search (Tavily) 的次数
    search_tool_count = 0
    for m in state["messages"]:
        if hasattr(m, "tool_calls") and m.tool_calls:
            for tc in m.tool_calls:
                if tc.get("name") == "academic_web_search":
                    search_tool_count += 1
    
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        # 如果历史累计调用加上这一次请求超过了最大限制，则强制拦截
        if search_tool_count > MAX_SEARCH_ITERATIONS:
            logger.warning(f"   ⚠️ 已达到最大 Tavily 搜索次数上限 ({MAX_SEARCH_ITERATIONS}次)，强制终止检索并进入提取阶段！")
            return "extract"
            
        logger.info(f"   🔧 决定调用工具 (共 {len(last_message.tool_calls)} 个) [Tavily搜索累计: {search_tool_count}/{MAX_SEARCH_ITERATIONS}]:")
        for tc in last_message.tool_calls:
            args = tc.get('args', {})
            if tc['name'] == 'academic_web_search':
                logger.info(f"      - 🔍 搜索关键词: {args.get('query')}")
            elif tc['name'] == 'read_and_verify_url':
                logger.info(f"      - 📖 阅读网页/DOI: {args.get('url_or_doi')}")
            else:
                logger.info(f"      - ⚙️ {tc['name']}: {args}")
        return "tools"
    
    # 打印大模型在检索阶段最后的总结论
    conclusion = getattr(last_message, "content", "无结论")
    if conclusion:
        # 如果结论太长，可能需要截断显示或者完整显示，这里展示完整结论
        logger.info(f"   💡 检索阶段得出结论:\n      {conclusion.strip()}")
    else:
        logger.info("   ✅ 检索完毕 (未输出结论文本)")
        
    logger.info("   ✅ 准备提取结构化数据...")
    return "extract"

# ----------------------------------
# (2) 结构化提取节点
# ----------------------------------
def extract_node(state: AgentState):
    """基于前期检索到的信息，强制结构化输出 DatasetExtractionList"""
    logger.info("⚡ [节点: 提取] 开始从收集到的信息中穷尽提取所有版本的数据集...")
    context = "\n".join([m.content for m in state["messages"] if hasattr(m, "content") and m.content])
    
    # 提取用户最初的描述，它通常是 messages[1]
    original_input = ""
    if len(state["messages"]) > 1:
        original_input = getattr(state["messages"][1], "content", "")
    
    schema_str = json.dumps(DatasetExtractionList.model_json_schema(), ensure_ascii=False, indent=2)
    
    extraction_prompt = f"""
基于以下收集到的信息，严格提取数据集的元数据。
如果没有找到某个字段对应的值，请返回 null。
如果包含多个年度版本，请在 datasets 数组中把每一个版本单独列出。

【严格过滤规则 - 动态版本控制】
1. 若用户的初始描述或URL中明确指定了某个特定版本，你【必须且只能】提取这一个指定的版本，严禁提取任何历史旧版或平行版本！
2. 若用户【没有】提及具体版本，请遵循全量保留逻辑：务必提取与用户初始描述完全匹配的标准版/科学版数据集。对于跨越多年度的系列数据集，即使早期版本记录简陋、缺乏 DOI、或不确定是否为标准版，只要是官方发布的该年度/历史主快照，请务必全量保留，绝对不可因“不确定”而丢弃任何一个历史版本！
严禁提取任何非官方的衍生版、附加版。

【重点关注：DOI 提取】
请务必仔细检查目标版本在上下文中的元数据，只要上下文中出现了该版本的 DOI（通常以 10.xxxx/xxxx 的格式出现），你【必须】将其提取到 doi 字段中，绝不允许漏提 DOI！请务必在收到的文本中仔细排查 DOI。


【格式要求】
你必须输出一段合法的 JSON 字符串，且必须严格符合以下 JSON Schema 结构：
{schema_str}
不要输出任何解释性文本或 markdown 代码块语法，只能输出 JSON 数据本身。

========================
【原始用户请求】（这是判断是否指定了特定版本的唯一依据）：
{original_input}
========================

【大模型检索总结与收集到的上下文】：
{context}
"""
    # 强制让 LLM 只输出 JSON
    response = custom_request_llm_invoke(
        [HumanMessage(content=extraction_prompt)], 
        json_mode=True
    )
    
    # 清理 markdown 标签
    raw_json_str = response.content.strip()
    if raw_json_str.startswith("```json"): raw_json_str = raw_json_str[7:]
    if raw_json_str.startswith("```"): raw_json_str = raw_json_str[3:]
    if raw_json_str.endswith("```"): raw_json_str = raw_json_str[:-3]
    
    try:
        json_data = json.loads(raw_json_str.strip())
        validated_obj = DatasetExtractionList(**json_data)
        extracted_datasets = [d.model_dump() for d in validated_obj.datasets]
    except Exception as e:
        logger.warning(f"⚠️ 解析 LLM 输出失败: {e}")
        extracted_datasets = []
        
    logger.info(f"   ➤ 提取到 {len(extracted_datasets)} 个版本结果")
    return {"messages": [response], "extracted_datasets": extracted_datasets}

# ----------------------------------
# 辅助函数：记录抓取失败以供后续优化
# ----------------------------------
def log_api_failure(dataset_record: dict, reason: str):
    error_file = "api_failures_for_optimization.json"
    failures = []
    if os.path.exists(error_file):
        try:
            with open(error_file, 'r', encoding='utf-8') as f:
                failures = json.load(f)
        except Exception:
            pass
    dataset_record["error_reason"] = reason
    failures.append(dataset_record)
    with open(error_file, 'w', encoding='utf-8') as f:
        json.dump(failures, f, ensure_ascii=False, indent=2)
    logger.warning(f"   ⚠️ 已将失败记录保存至 {error_file}，原因: {reason}")
# 2. 废弃版过滤：如果页面明确标明某个版本已经“Retired（退休）”、“Deprecated（废弃）”或“Terminated（彻底下线删除）”，请直接丢弃该版本。但请注意区分：**正常的年度历史快照不属于废弃版，必须正常保留和提取**，只丢弃那些被官方明确打上作废/瑕疵标签的版本。
def resolve_doi_to_url(doi: str) -> str:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"}
        res = requests.get(f"https://doi.org/{doi}", allow_redirects=True, timeout=15, headers=headers)
        return res.url
    except Exception as e:
        logger.warning(f"   ⚠️ [DOI重定向] 解析失败: {e}")
        return ""

# ----------------------------------
# (3) API 抓取节点
# ----------------------------------
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
                log_api_failure(extracted_info, reason=official_api_data["error"])
                
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
    
    workflow.add_node("researcher", research_and_verify_node)
    workflow.add_node("tools", ToolNode(tools))
    workflow.add_node("extractor", extract_node)
    workflow.add_node("fetcher", fetch_metadata_node)
    
    # 流程编排
    workflow.set_entry_point("researcher")
    # 如果大模型调用工具，去 tools；否则去提取
    workflow.add_conditional_edges("researcher", should_continue, {"tools": "tools", "extract": "extractor"})
    workflow.add_edge("tools", "researcher") # 工具执行完返回给大脑
    workflow.add_edge("extractor", "fetcher")
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

def process_target_datasets(target_id=None):
    app = build_agent()
    
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
        
        test_input = f"【目标数据集描述】\n{line}\n请先搜搜这篇数据，并确认具体信息后再提取。"
        
        system_prompt = """你是一个资深的数据科学家。
你的任务是调查用户提供的数据集描述，你可以使用网页搜索(academic_web_search)和网页阅读工具(read_and_verify_url)收集信息。
【核心纪律】：请优先阅读数据集的官方介绍页。绝对避免反复阅读整篇长达数十页的期刊论文，这会导致上下文超限崩溃！你只需要粗略搜索版本名和DOI即可。
【版本处理规则】：如果用户在描述或URL中明确指定了某个特定版本（如年份、Revision号等），请专门调查该指定版本，该版本为目标版本，不需要再去搜索其他版本；如果用户没有提及具体版本，请穷尽搜索其所有版本的 DOI 和官网信息，把能找到的所有官方标准版本/历史主快照（如系列数据集的每一个年度版本）全查清，这些版本均为目标版本，一个都不漏。
同时，重点留意目标版本的 DOI，务必准确收集到其对应的 DOI 并保留。
收集足够信息后，停止调用工具，流程将自动进入结构化提取节点。"""
        
        initial_state = {
            "messages": [
                SystemMessage(content=system_prompt),
                HumanMessage(content=test_input)
            ],
            "extracted_datasets": [],
            "final_results": []
        }
        
        try:
            # 运行 LangGraph，强制加上递归深度限制，为了配合 MAX_SEARCH_ITERATIONS 限制大模型特定工具，这里我们将底层步数设大。
            final_state = app.invoke(initial_state, config={"recursion_limit": MAX_SEARCH_ITERATIONS * 2 + 10})
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
    args = parser.parse_args()
    
    process_target_datasets(target_id=args.id)
