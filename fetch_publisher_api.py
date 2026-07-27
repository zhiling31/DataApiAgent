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
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_core.tools import tool
from langchain_tavily import TavilySearch
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

# 配置 Tavily API Key
# "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"
# zhizhi333333@gmail.com           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
# 2524258132@qq.com    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
os.environ["TAVILY_API_KEY"] = "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"

# ==========================================
# 0. 全局配置 (文件路径修改区)
# ==========================================
# 你可以在这里修改所有的输入输出文件路径
INPUT_DATASET_FILE = "45个数据集target_datasets.txt"       # 输入的原始数据集文件 (制表符分隔)
OUTPUT_RESULTS_FILE = "publisher_api_results_0722.xlsx"  # 增量保存的提取结果文件
OUTPUT_TRACE_FILE = "publisher_api_trace_0722.json"      # 大模型探索日志与思考过程文件
REGISTRY_FILE = "platform_api_registry_new.json"         # 大模型生成的 API 知识库 (存放 Python 代码)
TARGET_INJECT_FILE = "fetch_top_dataset_integrated_new.py"   # 生成的 Python 代码最终注入的目标文件

# ==========================================
# 1. 定义严格的 Pydantic 结构化输出模型 (防幻觉核心)
# ==========================================
class APIAttempt(BaseModel):
    api_template: str = Field(description="测试的 API 模板")
    test_dataset_id: str = Field(description="代入的参数 (dataset_id 或 doi 等)")
    tested_url: str = Field(description="实际请求的完整 URL")
    is_successful: bool = Field(description="验证是否通过")
    error_message_or_response: str = Field(description="如果失败，记录报错原因/状态码；如果成功，可简略记录返回或状态")

class PublisherAPIResult(BaseModel):
    publisher_name: str = Field(description="目标数据存储平台/Publisher名称")
    python_code: Optional[str] = Field(description="为该平台量身定制的完整 Python 获取函数代码。函数签名必须为 `def fetch_metadata(self, **kwargs):`。代码内需要实现多步请求、防错容错、参数提取(从kwargs)和最终请求。必须返回一个字典，如 `return {'source': '...', 'data': ...}`。如果没有可用API则返回 null。", default=None)
    test_dataset_id: Optional[str] = Field(description="用于验证的真实 Dataset ID 或 DOI，如未找到则返回 null", default=None)
    is_verified: bool = Field(description="是否找到了真实存在的 API。如果测试返回 200，或者返回 401/403 (说明接口确实存在，只是需要鉴权)，都必须填 True！不要因为 401/403 报错就填 False！", default=False)
    requires_auth: bool = Field(description="该 API 是否需要身份验证 (如 API Key、Token 等) 才能访问。如果测试返回 401/403，则填 True。", default=False)
    has_anti_crawler_risk: bool = Field(description="该API是否存在明显的反爬虫合规风险（如 Cloudflare 拦截、验证码拦截等，注意：单纯的 401 鉴权不属于反爬虫）", default=False)
    risk_level: str = Field(description="风险等级：'极低风险'（从官网API文档获取），'低风险'或'中风险'（从非官网API文档获取）", default="中风险")
    has_432_error: bool = Field(description="是否在搜索过程中遭遇了 432 额度耗尽错误（脚本自动记录）", default=False)
    has_reached_search_limit: bool = Field(description="是否在搜索过程中因绕圈子触发了本地最大搜索次数上限（脚本自动记录）", default=False)
    api_attempts: List[APIAttempt] = Field(description="所有测试过的 API（包括成功和失败的详细记录）", default_factory=list)
    reasoning_summary: str = Field(description="对整个搜索和验证过程的简短总结（不超过200字）", default="")

# ==========================================
# 2. 定义 Agent 状态与工具
# ==========================================
class AgentState(TypedDict):
    messages: Annotated[List, lambda x, y: x + y]
    publisher: str
    dataset_name: str
    dataset_url: str
    dataset_doi: str
    true_publisher: str
    is_cached: bool
    final_metadata: dict # 最终提取的字典

web_search_tool = TavilySearch(
    max_results=5,
    include_answer=True,
    search_depth="advanced"
)

# 全局搜索限制机制
search_call_count = 0
search_432_error = False
search_limit_reached = False
MAX_SEARCH_LIMIT = 25

@tool
def tavily_search(query: str) -> str:
    """
    【搜索引擎工具】用于全网关键词检索，寻找目标数据平台的官方 API 文档或可用的真实 Dataset ID。
    使用示例：
    - 搜索 API："{Publisher Name} REST API for dataset metadata"
    - 搜索 Dataset ID："{Publisher Name} dataset example DOI or ID"
    """
    global search_call_count, search_432_error, search_limit_reached
    
    if search_432_error:
        return "【系统硬性提示】: 搜索API额度已耗尽 (Error 432)！你**绝对不能**再调用搜索工具了。请立即停止探索并输出最终结果。"
        
    if search_call_count >= MAX_SEARCH_LIMIT:
        search_limit_reached = True
        return f"【系统硬性提示】: 调用 tavily_search 的次数已达到上限 ({MAX_SEARCH_LIMIT}次)！你**绝对不能**再搜索了。请立即停止探索，直接根据你目前掌握的所有线索（哪怕是不完美的）输出最终结果，或者用 verify_api_endpoint 验证已知接口！"
        
    try:
        search_call_count += 1
        result = web_search_tool.invoke({"query": query})
        return result
    except Exception as e:
        err_str = str(e).lower()
        if "Error 432: This request exceeds your plan's set usage limit" in err_str:
            search_432_error = True
            return "【系统硬性提示】: 搜索额度已耗尽 (Error 432)。你**绝对不能**再调用搜索工具了。请立即停止探索并输出最终结果。"
        return f"搜索失败: {str(e)}"

@tool
def verify_api_endpoint(api_url: str) -> str:
    """
    【API验证工具】尝试使用 HTTP GET 请求访问目标 API。
    请确保传入的 api_url 包含了具体的真实的 Dataset ID，例如 "https://zenodo.org/api/records/1234567"。
    该工具会返回 HTTP 状态码及返回的 JSON 结构的前 500 个字符。
    如果返回 401/403，说明 API 存在且需要鉴权，这同样也是有用的发现。
    """
    try:
        headers = {
            "Accept": "application/json",
            "User-Agent": "DataLibrarianAgent/1.0"
        }
        response = requests.get(api_url, headers=headers, timeout=10, allow_redirects=True)
        status_code = response.status_code
        
        try:
            data = response.json()
            data_str = json.dumps(data, ensure_ascii=False)[:500]
            is_json = True
        except Exception:
            data_str = response.text[:500]
            is_json = False
            
        anti_crawler_keywords = ["cloudflare", "captcha", "attention required!", "access denied", "please enable cookies", "security check"]
        has_risk = not is_json and any(kw in data_str.lower() for kw in anti_crawler_keywords)
        risk_warning = "\n【注意】：检测到明显的反爬虫特征（如 Cloudflare 盾或验证码），存在合规与爬取风险！" if has_risk else ""
        
        html_warning = ""
        if not is_json and ("<html" in data_str.lower() or "<body" in data_str.lower() or "<!doctype html>" in data_str.lower()):
            html_warning = "\n【警告】：返回的内容似乎是 HTML 网页，而非结构化数据 API。根据约束规则，我们绝对不能接受 HTML 网页，且不能使用爬虫！"
            
        if 200 <= status_code < 300:
            return f"【验证成功】Status: {status_code}\n部分内容: {data_str}{risk_warning}{html_warning}"
        elif status_code in [401, 403]:
            return f"【验证成功但需要鉴权】Status: {status_code}\n部分内容: {data_str}\n结论：这是一个真实存在的 API，但需要提供 API Key 或 Token。{risk_warning}{html_warning}"
        else:
            return f"【验证失败】Status: {status_code}\n部分内容: {data_str}{risk_warning}{html_warning}"
            
    except requests.exceptions.RequestException as e:
        return f"【验证请求错误】错误信息: {str(e)}"

tools = [tavily_search, verify_api_endpoint]

# ==========================================
# 3. 大模型调用逻辑
# ==========================================
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
            print(f"请求大模型接口失败 (尝试 {attempt+1}/{max_retries}): {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"响应内容: {e.response.text}")
                if e.response.status_code == 429:
                    print("🚦 触发接口限流 (429 Too Many Requests)，等待 30 秒后重试...")
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
SYSTEM_PROMPT = """你是一个资深的研发工程师，负责为各种学术数据存储平台寻找“元数据获取 REST API”并编写稳健的 Python 抓取代码。
任务要求：
【核心决策树 - 多步推理策略】
你必须严格按照以下步骤进行思考和行动：
1. 【API 定位】：利用 tavily_search 查阅官方文档，找到拉取元数据的终极 REST API。
2. 【参数解构】：分析该 API 到底需要什么参数（例如：纯数字 ID、内部 UUID、short_name）。
3. 【多源参数提取与 TDD 验证】：仔细审视用户提供给你的【测试样例数据集链接】或【数据集名称】。
   - 尝试从 URL 或 DOI 中提取参数。如果发现 DOI 无法直接填入目标 API（例如 API 需要 UUID，但你只有 DOI），此时必须触发决断机制！
   - 如果没有 DOI，你必须主动尝试用 Python 代码（如 `url.split('/')[-1]` 等）从 `dataset_url` 路径中挖掘隐藏的 ID。
4. 【解析层探索 (Resolution)】：如果你在第 3 步发现拿到的参数（如 DOI）不符合终极 API 的格式要求（如 UUID），你必须强制调用搜索工具，寻找“如何将 DOI 转换为内部 UUID”的中间解析接口（例如 SPARQL 端点、PID resolution API）。
5. 【代码拼装与强制验证】：将你的请求逻辑用 Python 串联起来。你必须使用 `verify_api_endpoint` 或自己构思逻辑跑通验证。只有真实跑通了，才能在最后输出 `python_code`！

【代码生成要求】
最终抽取的 `python_code` 必须是一个完整的 Python 函数，签名固定为：`def fetch_metadata(self, **kwargs):`。
- 在函数内部，你可以使用 `kwargs.get('doi')`, `kwargs.get('dataset_url')`, `kwargs.get('dataset_shortname')` 以及 `kwargs.get('extracted_api_params', {})`。
- 你必须在代码中写明 `if-else` 判断，如果缺 DOI 就尝试从 URL 截取，如果查不到就返回错误。
- 凡是发起 HTTP 请求，请使用 `self._get_with_retry(url, headers=custom_headers)`，你可以在 `custom_headers` 中覆盖 `Accept`（例如 `Accept: application/json`）。
- 成功时必须返回类似 `{"source": "平台名-Custom", "data": response.json()}` 的字典。失败时返回 `{"error": "报错原因"}`。
- 绝不接受需要解析 HTML DOM 树的代码（爬虫）。

【其余核心约束】
- 我们只需要“集合级”元数据 (Collection-level)，不需要具体文件列表或颗粒下载链接。
- 绝不要提供 DOI 注册机构的通用 API (api.datacite.org, crossref.org)。只能用该平台自己的原生接口或底层的如 OSTI。
- 如果请求返回 401/403，说明需要鉴权，这是合法的 API，请将 `is_verified=true`，并在总结中提示。
- 在最终输出的 `api_attempts` 中记录你踩过的所有坑（如哪些参数不匹配、哪些 URL 是 404）。
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

def identify_platform_node(state: AgentState):
    """节点：利用大模型+TavilySearch 严谨判断实际的数据托管平台并提取官方 DOI"""
    ds_name = state.get("dataset_name", "未知")
    ds_url = state.get("dataset_url", "未知")
    domain = state["publisher"]
    
    # 获取沉淀知识库中已有的平台列表
    registry = load_registry()
    known_platforms = list(registry.keys())
    known_platforms_str = ", ".join(known_platforms) if known_platforms else "暂无"
    
    # 为了防止多搜（控制 token），我们在喂给大模型前先执行一次极其精准的深度搜索
    query = f'"{ds_name}" {ds_url} data repository platform official DOI'
    try:
        search_res = web_search_tool.invoke({"query": query})
    except Exception as e:
        search_res = str(e)

    prompt = f"""你是一个顶尖的数据图情专家（Data Librarian）。
你的唯一任务是：基于以下网络搜索结果，精确找准该数据集的【首要数据托管平台】以及【官方 DOI】。

已知数据集线索：
- 数据集名称: {ds_name}
- 提供的链接/原始域名: {ds_url} (原始域名: {domain})

搜索结果：
{search_res}

已有已知平台池: [{known_platforms_str}]

【行动指南与领域排他规则】
1. 仔细阅读搜索结果，搞清楚该数据集究竟是由谁发布、被托管在哪里的。
2. 【排他规则】：很多科学数据集会在“领域级数据中心”（例如 ICOS Carbon Portal, NASA DAAC, NSIDC, Pangaea 等）和“通用数据仓库”（例如 Zenodo, Figshare, Dryad 等）同时拥有镜像。
   此时，你必须强行选择“领域级数据中心”作为首要托管平台！绝对不允许用通用仓库（如 Zenodo）来糊弄。
3. 如果实质属于已知平台池中的某家，请直接返回池子里的那个确切名称。如果不属于，请返回新平台的标准名称。
4. 【极其重要】：你必须在找到真正平台的同时，顺便提取出该数据集在该平台上的官方 DOI。如果没有严格的 DOI（以 10. 开头），则提取空白。

你必须严格输出一段纯 JSON，格式如下（绝对不能包含 Markdown 标记或其他多余文字）：
{{
    "platform": "识别出的平台名称",
    "doi": "找到的官方DOI，例如 10.18160/GCP-2023，如果没有则留空"
}}
"""
    
    response = custom_request_llm_invoke([HumanMessage(content=prompt)], use_tools=False)
    import json
    try:
        content = response.content.strip()
        if content.startswith("```json"):
            content = content.strip("`").replace("json\n", "", 1).strip()
        elif content.startswith("```"):
            content = content.strip("`").strip()
        res_json = json.loads(content)
        true_platform = res_json.get("platform", "").strip()
        dataset_doi = res_json.get("doi", "").strip()
    except Exception as e:
        print(f"解析 identify_platform_node JSON 失败: {e}，回退到原域名")
        true_platform = domain
        dataset_doi = ""

    print(f"识别出的平台: {true_platform} | DOI: {dataset_doi}")
    return {"true_publisher": true_platform, "dataset_doi": dataset_doi}

def check_cache_node(state: AgentState):
    """检查识别出的平台是否已在沉淀知识库中"""
    true_pub = state.get("true_publisher", "")
    registry = load_registry()
    
    matched_key = None
    for k in registry.keys():
        if k.lower() == true_pub.lower():
            matched_key = k
            break
            
    import sys
    force_test = "--dataset-id" in sys.argv
    if matched_key and not force_test:
        print(f"🎯 命中沉淀知识库！直接提取平台: {matched_key} 的 API。")
        cached_data = registry[matched_key]
        return {"is_cached": True, "final_metadata": cached_data}
    else:
        print(f"❌ 未命中沉淀知识库，开始探索: {true_pub} 的 API。")
        new_sys = SystemMessage(content=SYSTEM_PROMPT)
        ds_name = state.get('dataset_name', '')
        ds_url = state.get('dataset_url', '')
        ds_doi = state.get('dataset_doi', '')
        
        task_content = f"请寻找目标数据存储平台的元数据获取 API：\n【平台名称】：{true_pub}\n"
        task_content += f"【测试样例数据集名称】：{ds_name}\n【测试样例数据集链接】：{ds_url}\n"
        if ds_doi:
            task_content += f"【官方明确 DOI (极其重要)】：{ds_doi}\n"
        task_content += "请你必须解决：如何从这个真实样例的 URL、名称或 DOI 中，提取出目标 API 所需的 ID/参数，进行 TDD 验证，并最终输出 Python 代码！"
        
        new_human = HumanMessage(content=task_content)
        return {"is_cached": False, "messages": [new_sys, new_human]}

def route_after_cache(state: AgentState):
    if state.get("is_cached", False):
        return "END"
    else:
        return "researcher"

def save_to_cache_node(state: AgentState):
    final_json = state.get("final_metadata") or {}
    if final_json.get("is_verified") == True and not final_json.get("has_432_error"):
        registry = load_registry()
        pub_name = final_json.get("publisher_name")
        if pub_name:
            # 如果原缓存不存在，或者原缓存里没有 python_code (旧版格式)，或者是强制刷新，则覆盖
            if pub_name not in registry or not registry[pub_name].get("python_code"):
                registry[pub_name] = final_json
                save_registry(registry)
                print(f"💾 已将新验证的 API (带有 Python Code) 沉淀至知识库: {pub_name}")
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
    context = "\n".join([m.content for m in state["messages"] if hasattr(m, "content") and m.content])
    schema_str = json.dumps(PublisherAPIResult.model_json_schema(), ensure_ascii=False, indent=2)
    
    extraction_prompt = f"""
    基于之前的搜索和验证结果，提取最终的 API 信息。
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
    except Exception as e:
        print(f"[Warning] JSON解析失败: {e}")
        metadata_obj = PublisherAPIResult(publisher_name=state["publisher"])
        
    return {"messages": [response], "final_metadata": metadata_obj.model_dump()}

workflow = StateGraph(AgentState)
workflow.add_node("identify_platform", identify_platform_node)
workflow.add_node("check_cache", check_cache_node)
workflow.add_node("researcher", research_and_verify_node)
workflow.add_node("tools", ToolNode(tools))
workflow.add_node("extractor", structured_extraction_node)
workflow.add_node("save_cache", save_to_cache_node)

workflow.set_entry_point("identify_platform")
workflow.add_edge("identify_platform", "check_cache")
workflow.add_conditional_edges("check_cache", route_after_cache, {"END": END, "researcher": "researcher"})
workflow.add_conditional_edges("researcher", should_continue, {"tools": "tools", "extract": "extractor"})
workflow.add_edge("tools", "researcher")
workflow.add_edge("extractor", "save_cache")
workflow.add_edge("save_cache", END)
app = workflow.compile()

# ==========================================
# 5. 主执行逻辑
# ==========================================
def main():
    import sys
    if "--generate-only" in sys.argv:
        print("\n🚀 [快速模式] 直接基于 platform_api_registry.json 重新生成代码...")
        inject_generated_methods_to_fetcher()
        return

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", type=int, default=0, help="如果 > 0，则仅测试前几个 publisher。否则测试全部。")
    parser.add_argument("--dataset-id", type=str, default="", help="指定测试 45个数据集target_datasets.txt 中的特定 数据集ID")
    args = parser.parse_args()

    input_file = INPUT_DATASET_FILE
    if not os.path.exists(input_file):
        print(f"找不到 {input_file}")
        return

    try:
        df = pd.read_csv(input_file, sep='\t', dtype=str)
    except Exception as e:
        print(f"读取文件失败: {e}")
        return

    if args.dataset_id:
        df = df[df.iloc[:, 0].astype(str) == str(args.dataset_id)]
        if df.empty:
            print(f"⚠️ 在文件中找不到 数据集ID 为 {args.dataset_id} 的记录。")
            return
            
    publisher_samples = {}
    for _, row in df.iterrows():
        # 由于我们没有 "数据存储官网" 列，我们使用原始域名提取平台名，这里先用下载链接的域名代替
        ds_url = str(row.iloc[3]) if len(row) > 3 else "未知链接"
        ds_name = str(row.iloc[1]) if len(row) > 1 else "未知数据集"
        
        # 尝试从 URL 提取域名作为 key
        try:
            from urllib.parse import urlparse
            parsed_uri = urlparse(ds_url)
            pub = '{uri.netloc}'.format(uri=parsed_uri)
            if not pub: pub = ds_url
        except:
            pub = ds_url

        if pub not in publisher_samples:
            publisher_samples[pub] = {
                "dataset_name": ds_name,
                "url": ds_url
            }
            
    publishers = list(publisher_samples.keys())
    
    if args.test > 0 and not args.dataset_id:
        publishers = publishers[:args.test]

    results_file = OUTPUT_RESULTS_FILE
    trace_file = OUTPUT_TRACE_FILE

    # 断点续传初始化
    existing_pubs = set()
    all_results = []
    
    if os.path.exists(results_file):
        try:
            existing_df = pd.read_excel(results_file)
            if 'publisher_name' in existing_df.columns:
                existing_pubs = set(existing_df['publisher_name'].dropna().tolist())
                print(f"检测到历史进度，已跳过 {len(existing_pubs)} 个已处理的平台。")
            all_results = existing_df.to_dict('records')
        except Exception as e:
            print(f"无法读取历史结果文件: {e}")

    all_traces = []
    if os.path.exists(trace_file):
        try:
            with open(trace_file, "r", encoding="utf-8") as f:
                all_traces = json.load(f)
        except Exception as e:
            print(f"无法读取历史日志文件: {e}")

    # 针对强行测试某个 dataset_id，清理其历史记录和本地缓存
    if args.dataset_id and len(publishers) > 0:
        target_pub = publishers[0]
        if target_pub in existing_pubs:
            existing_pubs.remove(target_pub)
        
        # 将其从 registry 中移除以强制重新探索
        registry = load_registry()
        if target_pub in registry:
            del registry[target_pub]
            save_registry(registry)
            print(f"🧹 已清理 {target_pub} 的本地缓存，强制重新探索。")

    for pub in publishers:
        if pub in existing_pubs and not args.dataset_id:
            print(f"⏩ {pub} 已经处理过，跳过。")
            continue
        print(f"\n===========================================")
        print(f"🔍 正在处理: {pub}")
        print(f"===========================================")
        sample_info = publisher_samples.get(pub, {"dataset_name": "未知数据集", "url": "未知链接"})
        ds_name = sample_info["dataset_name"]
        ds_url = sample_info["url"]
        
        initial_state = {
            "messages": [], # 空的 messages，由后续节点填充
            "publisher": pub,
            "dataset_name": ds_name,
            "dataset_url": ds_url,
            "dataset_doi": "",
            "true_publisher": "",
            "is_cached": False,
            "final_metadata": {}
        }
        
        trace_log = {"publisher": pub, "steps": []}
        
        # 针对每个平台，重置搜索次数和状态标识
        global search_call_count, search_432_error, search_limit_reached
        search_call_count = 0
        search_432_error = False
        search_limit_reached = False
        
        try:
            current_state = initial_state.copy()
            for step in app.stream(initial_state):
                for node_name, state_update in step.items():
                    print(f"\n--- ⚡ 节点执行完毕: {node_name} ---")
                    if state_update is None:
                        continue
                        
                    # Accumulate state to avoid losing final_metadata when the last node returns empty
                    if "messages" in state_update:
                        current_state["messages"].extend(state_update["messages"])
                    if "final_metadata" in state_update:
                        current_state["final_metadata"] = state_update["final_metadata"]
                    if "true_publisher" in state_update:
                        current_state["true_publisher"] = state_update["true_publisher"]
                        
                    messages = state_update.get("messages", [])
                    latest_msg = messages[-1] if messages else None
                    
                    if node_name == "researcher" and latest_msg:
                        reasoning = latest_msg.additional_kwargs.get("reasoning_content", "")
                        if reasoning:
                            print(f"\n[思考过程]: {reasoning[:300]}...\n")
                            
                        if hasattr(latest_msg, "tool_calls") and latest_msg.tool_calls:
                            print("🧠 [大模型调用工具]:")
                            for tc in latest_msg.tool_calls:
                                print(f"   🔧 工具: {tc['name']}, 参数: {tc['args']}")
                        else:
                            print("🧠 [大模型决策] 思考完毕，准备抽取。")
                            
                        trace_log["steps"].append({
                            "node": "researcher",
                            "reasoning": reasoning,
                            "content": latest_msg.content,
                            "tool_calls": latest_msg.tool_calls if hasattr(latest_msg, "tool_calls") else []
                        })
                            
                    elif node_name == "tools" and latest_msg:
                        content_preview = str(latest_msg.content)[:300] + "..." if len(str(latest_msg.content)) > 300 else str(latest_msg.content)
                        print(f"🛠️ [工具返回]:\n   📤 {content_preview}")
                        trace_log["steps"].append({
                            "node": "tools",
                            "tool_name": getattr(latest_msg, "name", "unknown_tool"),
                            "tool_call_id": getattr(latest_msg, "tool_call_id", ""),
                            "result": latest_msg.content
                        })
                    
            if current_state.get("final_metadata"):
                final_json = current_state["final_metadata"].copy() # 避免直接修改 state 里的数据
                
                # 记录原始域名与真实提取出来的平台名
                final_json["original_domain"] = pub
                final_json["true_publisher"] = current_state.get("true_publisher", "")
                
                # 确保 publisher_name 一致，防止断点续传失效
                final_json["publisher_name"] = pub 
                final_json["has_432_error"] = search_432_error
                final_json["has_reached_search_limit"] = search_limit_reached
                
                # 将嵌套列表转换为字符串
                if "api_attempts" in final_json and isinstance(final_json["api_attempts"], list):
                    final_json["api_attempts"] = json.dumps(final_json["api_attempts"], ensure_ascii=False, indent=2)
                    
                all_results.append(final_json)
                trace_log["steps"].append({
                    "node": "final_output",
                    "extracted": final_json
                })

            all_traces.append(trace_log)
            existing_pubs.add(pub)
            
            # 增量保存
            results_df = pd.DataFrame(all_results)
            try:
                results_df.to_excel(results_file, index=False)
            except PermissionError:
                alt_name = results_file.replace(".xlsx", "_temp.xlsx")
                results_df.to_excel(alt_name, index=False)
                print(f"⚠️ 无法写入 {results_file} (可能被Excel占用)，已保存为 {alt_name}")
            
            with open(trace_file, "w", encoding="utf-8") as f:
                json.dump(all_traces, f, ensure_ascii=False, indent=2)
            print(f"💾 {pub} 处理完成，已增量保存。")
            
        except Exception as e:
            import traceback
            print(f"处理 {pub} 时发生错误: {e}")
            traceback.print_exc()

    print(f"\n✅ 所有平台处理完成！")
    
    # 最后，基于已沉淀的注册表自动生成请求代码
    try:
        print("\n🚀 正在自动生成/更新 API 抓取代码至 fetch_top_dataset_integrated.py ...")
        inject_generated_methods_to_fetcher()
    except Exception as e:
        print(f"⚠️ 自动生成代码失败: {e}")

def inject_generated_methods_to_fetcher():
    import re
    registry = load_registry()
    code_lines = []
    route_map = {}
    valid_apis_desc = []
    
    with open(TARGET_INJECT_FILE, 'r', encoding='utf-8') as f:
        fetcher_content = f.read()
    
    # 提取已有的手写函数名（在生成标记之前的代码中）
    start_marker = "# --- AUTOGENERATED API FETCHERS START ---"
    handwritten_code = fetcher_content.split(start_marker)[0] if start_marker in fetcher_content else fetcher_content
    handwritten_methods = set(re.findall(r'def (fetch_[a-zA-Z0-9_]+)\(', handwritten_code))

    for hw_method in handwritten_methods:
        pub_key = hw_method.replace("fetch_", "").replace("_", " ").title()
        if pub_key.lower() == "osti": pub_key = "OSTI"
        elif pub_key.lower() == "zenodo": pub_key = "Zenodo"
        elif pub_key.lower() == "nasa laads daac": pub_key = "LAADS DAAC"
        elif pub_key.lower() == "icos carbon portal": pub_key = "ICOS Carbon Portal"
        elif pub_key.lower() == "doe gdr": pub_key = "DOE GDR"
        elif pub_key.lower() == "pangaea": pub_key = "PANGAEA"
        elif pub_key.lower() == "sciencedb": pub_key = "ScienceDB"
        elif pub_key.lower() == "ess dive": pub_key = "ESS-DIVE"
        elif pub_key.lower() == "figshare": pub_key = "Figshare"
        elif pub_key.lower() == "gbif": pub_key = "GBIF"
        elif pub_key.lower() == "usgs sciencebase": pub_key = "USGS ScienceBase"
        elif pub_key.lower() == "opentopography": pub_key = "OpenTopography"
        elif pub_key.lower() == "mendeley": pub_key = "Mendeley"
        
        if pub_key not in route_map and pub_key.lower() not in [k.lower() for k in route_map.keys()]:
            route_map[pub_key] = hw_method
            valid_apis_desc.append(f"'{pub_key}'")

    for pub_name, data in registry.items():
        if not data.get('is_verified'): continue
        
        python_code = data.get('python_code')
        if not python_code: continue
        
        clean_name = re.sub(r'[^a-zA-Z0-9]', '_', pub_name).lower()
        base_method_name = f'fetch_{clean_name}'
        
        # 无论是否有冲突，所有自动生成的代码统一加上 auto_ 前缀，便于查看
        method_name = f'auto_{base_method_name}'
        if base_method_name in handwritten_methods:
            route_map[pub_name] = base_method_name # 如果有手写函数，路由优先指向手写版本
        else:
            route_map[pub_name] = method_name # 如果没有手写版本，路由指向 auto_ 自动生成版本
        
        if f"'{pub_name}'" not in valid_apis_desc:
            valid_apis_desc.append(f"'{pub_name}'")
        
        # 清理可能被包裹的 markdown
        code_str = python_code.strip()
        if code_str.startswith("```python"): code_str = code_str[9:]
        if code_str.startswith("```"): code_str = code_str[3:]
        if code_str.endswith("```"): code_str = code_str[:-3]
        code_str = code_str.strip()
        
        # 强制替换函数名为自动生成的命名
        code_str = re.sub(r'^def\s+[a-zA-Z0-9_]+\s*\(', f'def {method_name}(', code_str, count=1, flags=re.MULTILINE)
        
        # 缩进处理（给代码整体加上 4 个空格，因为它在 FetchTopDataset 类中）
        indented_code = '\n'.join('    ' + line if line.strip() else line for line in code_str.split('\n'))
        
        code_lines.append(indented_code)
        code_lines.append('')
        
    code_lines.append('    def get_route_map(self):')
    code_lines.append('        \"\"\"返回动态生成的 API 路由映射\"\"\"')
    code_lines.append('        return {')
    for pub, method in route_map.items():
        code_lines.append(f'            \"{pub}\": self.{method},')
    code_lines.append('        }')
    code_lines.append('')
    code_lines.append('    @staticmethod')
    code_lines.append('    def get_api_schema_desc():')
    code_lines.append('        \"\"\"返回给大模型用的 API Schema 动态提示词\"\"\"')
    schema_string = "基于官网名称，智能匹配目标API。请按最可能的优先级提供一个匹配列表。**严禁强行凑数！**如果列表中没有任何平台明确、直接地匹配该数据集的官方来源，请务必返回空列表 []。宁可返回空，也不要错误归类：[" + ", ".join(valid_apis_desc) + "]"
    code_lines.append(f'        return \"\"\"{schema_string}\"\"\"')
    
    generated_code = '\n'.join(code_lines)
    
    end_marker = "# --- AUTOGENERATED API FETCHERS END ---"
    
    if start_marker in fetcher_content and end_marker in fetcher_content:
        start_idx = fetcher_content.find(start_marker) + len(start_marker)
        end_idx = fetcher_content.find(end_marker)
        new_content = fetcher_content[:start_idx] + "\n" + generated_code + "\n    " + fetcher_content[end_idx:]
        with open(TARGET_INJECT_FILE, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print("✅ 成功注入生成的代码")
    else:
        print("❌ 找不到注入标记 # --- AUTOGENERATED API FETCHERS START ---")

if __name__ == "__main__":
    main()
