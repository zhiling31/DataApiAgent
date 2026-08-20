import json
import logging
import importlib
from typing import List, Optional, TypedDict, Annotated
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.tools import tool
from langchain_tavily import TavilySearch
import os
import sys
import requests
import uuid

logger = logging.getLogger('DatasetAgent')
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

SYSTEM_PROMPT = """你是一个资深的数据科学家。
你的任务是根据用户提供的数据集描述，定位该数据集的目标版本以及目标版本的DOI、数据集链接（落地页）和数据托管平台名称。
你可以使用网页搜索(academic_web_search)和网页阅读工具(read_and_verify_url)收集信息。
【版本处理规则】：
1、如果用户在描述或URL中明确指定了某个特定版本（如年份、Revision号等），请专门调查该指定版本，该版本为目标版本，不需要再去搜索其他版本；
2、如果用户没有提及具体版本，请务必找到最新的官方标准版本/历史主快照，设定为目标版本。
    【重要】最新版本定位法则（颗粒度严格对齐）：
        1. 如果用户请求的是【特定子数据集/单项数据】：
        - 你的目标【必须且只能】是该【特定子数据集本身】！
        - 如果该子数据集有自己独立的专有 DOI，必须提取该子数据集的专有 DOI！绝对禁止用其父级大集合的 DOI 或 URL 来顶替！
        
        2. 如果用户请求的是【宏观大型集合/数据库】：
        - 请提取该大集合在官方仓库中最新发布的官方标准归档版（拥有独立归档页面/独立 DOI)的最新版本。
        - 严禁将网页上宣传的实时动态更新标语识别为版本！因为动态更新服务在档案馆中没有打包存档链接。
        - 必须提取指向具体数据集归档页面的落地页 URL。
        - 绝对不要提取子数据集充当宏观大型集合

【DOI提取】重点留意目标版本的 DOI，务必准确收集到其对应的 DOI 并保留。

【核心纪律1】：请优先阅读数据集的官方介绍页。绝对避免反复阅读整篇长达数十页的期刊论文，这会导致上下文超限崩溃！你只需要粗略搜索目标版本的DOI、数据集链接、数据托管平台即可。
1. 优先调用 `read_and_verify_url` 读取用户输入的线索网址或官方主页。
2. 只要通过 `read_and_verify_url` 或搜索拿到了【与用户请求颗粒度完全对齐】的官方落地页 URL 、 10.xxxx/xxxx DOI和数据托管平台，【立刻停止发起任何进一步搜索】！直接进入结构化提取！

【核心纪律2】：宁缺毋滥，用户输入的 URL 实体即为检索与提取的最高物理边界，绝对禁止跨越实体边界去强行拼凑其他地理/项目子集的 DOI。仔细核对你找的数据集内容与用户描述的目标数据集名称以及URL内容是否一致，如果不一致，则不予收集，不要强行搜集DOI。根据最终确认的数据集链接确认数据存储官网。
如果搜索到的 DOI 只是某篇引用该数据的论文 DOI 或个人临时导出包 DOI，绝对不要强行收集，不要误当作数据集官方本体 DOI！此类动态 DOI 必须排除，`doi` 返回 null

"""

# 提取相关模型定义

class DatasetInfo(BaseModel):
    doi: Optional[str] = Field(description="官方 DOI (10.xxxx/xxxx)，若无明确本体DOI则返回 null", default=None)
    dataset_url: Optional[str] = Field(description="用户提供的初始 URL（用户输入的线索网址），如果标准快照归档在其他网址，该网址也一起合并到url中，如果存在多个网址，用;分隔", default=None)
    doi_landing_page: Optional[str] = Field(description="DOI 解析落地页", default=None)
    dataset_name: Optional[str] = Field(description="数据集名称", default=None)
    version_name: Optional[str] = Field(description="该数据集的具体版本号或年份标识 (例如: '2024', 'v1.2', 'Collection 2')，用于区分同名数据集的不同历史快照，若无则返回 null", default=None)
    official_websites: Optional[List[str]] = Field(description="按照关联度、优先级排序返回候选的数据集官网或托管平台名称 (例如: Zenodo, PANGAEA, ScienceDB, OSTI, GBIF等)。宁缺毋滥，不用过度返回。若无则返回空列表", default_factory=list)

class DatasetExtractionList(BaseModel):
    datasets: List[DatasetInfo] = Field(description="基于收集到的所有信息，提取出匹配的数据集")

def run_extraction(messages, custom_request_llm_invoke):
    """基于前期检索到的信息，强制结构化输出 DatasetExtractionList"""
    logger.info("⚡ [节点: 提取] 开始从收集到的信息中获取目标版本的数据集...")
    context = "\n".join([m.content for m in messages if hasattr(m, "content") and m.content])
    original_input = getattr(messages[1], "content", "") if len(messages) > 1 else ""
    
    schema_str = json.dumps(DatasetExtractionList.model_json_schema(), ensure_ascii=False, indent=2)
    
    extraction_prompt = f"""
基于以下收集到的信息，严格提取目标版本的数据集的版本信息、DOI、落地页。
如果没有找到某个字段对应的值，请返回 null。

【目标版本数据集提取】
1. 若用户的初始描述或URL中明确指定了某个特定版本，你【必须且只能】提取这一个指定的版本，严禁提取任何历史旧版或新版本或平行版本！
2. 若用户【没有】提及具体版本，请遵循保留最新的版本的逻辑：务必提取与用户初始描述完全匹配的标准版/科学版数据集。对于跨越多年度的系列数据集，请找出最新的官方发布的该年度/历史主快照。严禁提取任何非官方的衍生版、附加版。
    【重要】最新版本定位法则：
        1. 如果用户请求的是【特定子数据集/单项数据】：
        - 你的目标【必须且只能】是该【特定子数据集本身】！
        - 如果该子数据集有自己独立的专有 DOI，必须提取该子数据集的专有 DOI！绝对禁止用其父级大集合的 DOI 或 URL 来顶替！
        
        2. 如果用户请求的是【宏观大型集合/数据库】：
        - 请提取该大集合在官方仓库中最新发布的官方标准归档版（拥有独立归档页面/独立 DOI)的最新版本。
        - 严禁将网页上宣传的实时动态更新标语识别为版本！因为动态更新服务在档案馆中没有打包存档链接。
        - 必须提取指向具体数据集归档页面的落地页 URL。
        - 绝对不要提取子数据集充当宏观大型集合

【目标版本数据集的DOI 提取】
请务必仔细检查目标版本在上下文中的元数据，只要上下文中出现了该版本的 DOI（通常以 10.xxxx/xxxx 的格式出现），你【必须】将其提取到 doi 字段中，绝不允许漏提 DOI！请务必在收到的文本中仔细排查 DOI。

【核心纪律】：宁缺毋滥，用户输入的 URL 实体即为检索与提取的最高物理边界，绝对禁止跨越实体边界去强行拼凑其他地理/项目子集的 DOI。仔细核对你找的数据集内容与用户描述的目标数据集名称以及URL内容是否一致，如果不一致，则不予收集，不要强行搜集DOI。根据最终确认的数据集链接确认数据存储官网。
如果搜索到的 DOI 只是某篇引用该数据的论文 DOI 或个人临时导出包 DOI，绝对不要强行收集，不要误当作数据集官方本体 DOI！此类动态 DOI 必须排除，`doi` 返回 null


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
    return response, extracted_datasets

if "TAVILY_API_KEY" not in os.environ:
    os.environ["TAVILY_API_KEY"] = "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"
web_search_tool = TavilySearch(max_results=5, include_answer=True, search_depth="advanced")

@tool
def academic_web_search(query: str) -> str:
    """【发现工具】用于全网关键词检索，寻找未知的标杆论文或数据托管平台。"""
    try:
        result = web_search_tool.invoke({"query": query})
        result_str = str(result)
        logger.info(f"Tavily search result (first 100 chars): {result_str[:100]}")
        if "Error 432: This request exceeds your plan's set usage limit" in result_str:
            logger.error(f"Encountered 432 error: {result_str}. Exiting program.")
            sys.exit(1)
        return result
    except Exception as e:
        return f"搜索失败: {str(e)}"

@tool
def read_and_verify_url(url_or_doi: str) -> str:
    """【精准阅读与验证工具】用于解析具体的 URL 网页内容，或验证 DOI 是否真实存在并指向数据。"""
    import re
    doi = ""
    doi_match = re.search(r'(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)', url_or_doi)
    if doi_match:
        doi = doi_match.group(1)
        
    if doi:
        try:
            headers = {"Accept": "application/vnd.citationstyles.csl+json", "User-Agent": "DataLibrarianAgent/1.0"}
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
            pass

    if not url_or_doi.startswith("http"):
        if url_or_doi.startswith("10."):
            url_or_doi = f"https://doi.org/{url_or_doi}"
        else:
            url_or_doi = f"https://{url_or_doi}"
            
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp("http://127.0.0.1:9223")
            default_context = browser.contexts[0]
            page = default_context.new_page()
            page.goto(url_or_doi, timeout=60000, wait_until="domcontentloaded")
            text = page.locator("body").inner_text()
            page.close()
            text = re.sub(r'\s+', ' ', text).strip()
            return f"【CDP 网页抓取成功】(截取了前10000字符):\n{text[:10000]}"
    except Exception as e:
        logger.error(f"无法使用 CDP 连接本地浏览器进行验证: {str(e)}")
        return f"无法使用 CDP 连接本地浏览器进行验证: {str(e)}"

tools = [academic_web_search, read_and_verify_url]
MAX_SEARCH_ITERATIONS = 35

class ExtractorState(TypedDict):
    messages: Annotated[List, lambda x, y: x + y]
    extracted_datasets: List[dict]
    custom_request_llm_invoke: callable
    dataset_info_dict: dict

def research_and_verify_node(state: ExtractorState):
    logger.info("⚡ [节点: 检索] 大模型正在思考是否需要使用全网搜索或抓取工具...")
    messages = state["messages"]
    custom_request_llm_invoke = state["custom_request_llm_invoke"]
    response = custom_request_llm_invoke(messages, use_tools=True, custom_tools=tools)
    return {"messages": [response]}

def should_continue(state: ExtractorState):
    search_tool_count = sum(1 for m in state["messages"] if hasattr(m, "tool_calls") and getattr(m, "tool_calls", None) for tc in m.tool_calls if tc.get("name") == "academic_web_search")
    
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        if search_tool_count > MAX_SEARCH_ITERATIONS:
            logger.warning(f"   ⚠️ 已达到最大 Tavily 搜索次数上限 ({MAX_SEARCH_ITERATIONS}次)，强制终止检索并进入提取阶段！")
            return "extract"
            
        logger.info(f"   🔧 决定调用工具 (共 {len(last_message.tool_calls)} 个) [Tavily搜索累计: {search_tool_count}/{MAX_SEARCH_ITERATIONS}]:")
        for tc in last_message.tool_calls:
            args = tc.get('args', {})
            if tc['name'] == 'academic_web_search':
                logger.info(f"      - 🔍 搜索关键词: {args.get('query')}")
            elif tc['name'] == 'read_and_verify_url':
                logger.info(f"      - 📖 阅读网页: {args.get('url_or_doi')}")
            else:
                logger.info(f"      - ⚙️ {tc['name']}: {args}")
        return "tools"
    
    conclusion = getattr(last_message, "content", "无结论")
    if conclusion:
        logger.info(f"   💡 检索阶段得出结论:\n      {conclusion.strip()}")
    else:
        logger.info("   ✅ 检索完毕 (未输出结论文本)")
        
    logger.info("   ✅ 准备提取结构化数据...")
    return "extract"

def extract_node(state: ExtractorState):
    response, extracted_datasets = run_extraction(state["messages"], state["custom_request_llm_invoke"])
    return {"messages": [response], "extracted_datasets": extracted_datasets}

def verify_semantic_node(state: ExtractorState):
    logger.info("⚡ [节点: 语义验证] 验证提取的数据集实体是否准确匹配目标数据集...")
    extracted_datasets = state.get("extracted_datasets", [])
    custom_request_llm_invoke = state["custom_request_llm_invoke"]
    dataset_info_dict = state.get("dataset_info_dict", {})
    
    target_name = dataset_info_dict.get("dataset_name", "")
    target_desc = dataset_info_dict.get("dataset_description", "")
    
    if not target_name and not target_desc:
        logger.info("   ⚠️ 目标数据集名称和描述均为空，跳过语义验证。")
        return {"extracted_datasets": extracted_datasets}
        
    valid_datasets = []
    for ds in extracted_datasets:
        doi = ds.get("doi")
        
        if not doi:
            logger.info("   ⚠️ 提取结果中没有 DOI，跳过 DOI 语义验证，默认放行。")
            valid_datasets.append(ds)
            continue
            
        logger.info(f"   ▶ 开始验证 DOI 落地页: {doi}")
        content_snippet = ""
        
        # 1. 尝试使用 content negotiation 获取 DOI 的元数据
        if doi:
            try:
                headers = {"Accept": "application/vnd.citationstyles.csl+json", "User-Agent": "DataAgent/1.0"}
                response = requests.get(f"https://doi.org/{doi}", headers=headers, timeout=10, allow_redirects=True)
                if response.status_code == 200:
                    data = response.json()
                    title = data.get("title", "")
                    abstract = data.get("abstract", "")
                    content_snippet = f"标题(Title): {title}\n摘要(Abstract): {abstract}\n完整内容: {json.dumps(data, ensure_ascii=False)[:1000]}"
            except Exception:
                pass
                
        # 2. 如果拿不到 CSL-JSON，使用 read_and_verify_url 获取网页
        if not content_snippet:
            try:
                content_snippet = read_and_verify_url.invoke({"url_or_doi": doi})
            except Exception:
                pass
                
        if not content_snippet or "无法使用" in content_snippet or "提取失败" in content_snippet:
             logger.warning(f"   ⚠️ 无法获取 {doi} 的落地页内容，跳过语义验证。")
             valid_datasets.append(ds)
             continue
             
        content_snippet = str(content_snippet)[:3000]
        
        doi_reference_info = f"【目标指纹】\n- 目标名称: {target_name}\n"
        if target_desc:
            doi_reference_info += f"- 目标描述: {target_desc}\n"
            
        prompt = f"""你是一个严格的数据集语义校验专家。
请判断以下从数据集落地页获取的内容片段，是否与我们正在寻找的目标数据集精确匹配？

{doi_reference_info}

请执行严格的【实体对齐与颗粒度鉴定】：
仔细阅读下方获取到的内容片段，它是否【精确描述】了我们正在寻找的目标数据集？

【一票否决标准 (只要触犯即判定为 NO)】：
1. 【实体错位 / 张冠李戴】：获取的网页标题和描述与目标指纹完全不符，或者是一个毫不相关的论文。
2. 【子实体/地名越界错位】：如果目标指纹请求的是一个【全局/宏观/不限定地名的数据集】，而落地页内容中强行限定了某个【具体国家/州/地方名】，这属于典型的子实体错位！必须判定 VALID: NO！
3. 【非数据集本体DOI】描述不是数据集本体，而是论文，一票否决

【防误杀】
即使DOI落地页的内容类型type 显示为 "article"，也可能是数据集本体，type并不准确，不可作为一票否决的条件。 例如数据集出版系列旗下包含了多个子数据集，有时候type就是 "article"，需要仔细甄别。 重点判断目标数据集与落地页内容描述是否一致，不要被无关信息干扰

请严格按照以下 2 行格式输出（不要输出任何多余字符）：
VALID: [YES 或 NO]
REASON: [一句话说明放行或拦截的理由]

【从落地页 ({doi}) 获取的内容片段】：
{content_snippet}
"""
        try:
            response = custom_request_llm_invoke([
                SystemMessage(content="你是一个严格的数据集语义校验专家。"),
                HumanMessage(content=prompt)
            ], use_tools=False)
            
            result_text = response.content.strip()
            is_valid = False
            reason = ""
            for line in result_text.split('\n'):
                line = line.strip().upper()
                if line.startswith("VALID:"): is_valid = "YES" in line
                elif line.startswith("REASON:"): reason = line.split(":", 1)[1].strip() if ":" in line else line.replace("REASON", "")
                
            if is_valid:
                logger.info(f"      ✅ [验证通过]: {reason}")
                valid_datasets.append(ds)
            else:
                logger.warning(f"      ❌ [验证拦截] 实体错位: {reason}")
                
        except Exception as e:
            logger.warning(f"      ⚠️ 大模型验证调用异常: {e}，默认放行。")
            valid_datasets.append(ds)
            
    return {"extracted_datasets": valid_datasets}

def extract_dataset_info(dataset_info_dict: dict, custom_request_llm_invoke) -> List[dict]:
    """统一的黑盒提取入口：执行搜寻和结构化提取，返回 DatasetInfo 字典列表"""
    workflow = StateGraph(ExtractorState)
    
    workflow.add_node("researcher", research_and_verify_node)
    workflow.add_node("tools", ToolNode(tools))
    workflow.add_node("extractor", extract_node)
    workflow.add_node("verify_semantic", verify_semantic_node)
    
    workflow.set_entry_point("researcher")
    workflow.add_conditional_edges("researcher", should_continue, {"tools": "tools", "extract": "extractor"})
    workflow.add_edge("tools", "researcher")
    workflow.add_edge("extractor", "verify_semantic")
    workflow.add_edge("verify_semantic", END)
    
    app = workflow.compile()
    
    formatted_desc = "\n".join([f"{k}: {v}" for k, v in dataset_info_dict.items() if v])
    test_input = f"【目标数据集描述】\n{formatted_desc}\n请先搜搜这篇数据，并确认具体信息后再提取。"
    initial_state = {
        "messages": [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=test_input)
        ],
        "extracted_datasets": [],
        "custom_request_llm_invoke": custom_request_llm_invoke,
        "dataset_info_dict": dataset_info_dict
    }
    
    final_state = app.invoke(initial_state, config={"recursion_limit": 1000})
    return final_state.get("extracted_datasets", [])

