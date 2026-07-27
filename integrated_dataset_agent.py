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
INPUT_DATASET_FILE = "45个数据集target_datasets.txt"       # 输入的原始数据集文件 (制表符分隔)
OUTPUT_RESULTS_DIR = "agent_results0724"                     # 运行结果(成功或报错的 JSON)的保存目录
MISSING_REGISTRY_FILE = "agent_results0724/missing_registry_datasets.txt"  # 未命中知识库的数据集保存文件
API_FALLBACK_LOG_FILE = "agent_results0724/api_fallback_errors.log"            # 多API尝试时，中间失败的日志
REGISTRY_API_LOG_FILE = "agent_results0724/registry_api_errors.log"            # 注册机构(doi.org, DataCite, Crossref)的报错日志
MAX_RECORDS_TO_PROCESS = 10                               # 每次批量测试的最大数量
STRICT_RESUME_MODE = False                               # 续传模式: False=只要有1个成功版就跳过; True=只要有报错版(或全错)就必须重跑
MAX_SEARCH_ITERATIONS = 25                               # 大模型检索的最大循环思考次数 (默认25，值过大会增加死循环和Token爆炸的风险)

# ==========================================
# 1. 导入已有工具模块
# ==========================================
from fetch_top_dataset_integrated_new import IntegratedDataRepoFetcher
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
            page.close()
            browser.close()
            
            # 清理多余的空白符
            import re
            text = re.sub(r'\s+', ' ', text).strip()
            
            # 【治本：防止大模型被几万字的论文撑死】
            # 只截取前 4000 个字符，对于找数据集 DOI 和版本信息已经足够
            return f"【CDP 网页抓取成功】(截取了前4000字符):\n{text[:4000]}"
                
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

# @tool
# def verify_and_search_metadata(query: str) -> str:
#     """
#     全网检索工具。用于检索数据集的官方主页、数据发布本体以及标杆论文。
#     【注意：你需要自己根据情况构造高质量的 query】
#     以下是一些示例，仅供参考。
#     - 如果找论文：可以构造包含 "数据集名称" AND ("data descriptor" OR "methodology" OR "article") 的 query。
#     - 如果找数据本体：可以构造包含 "数据集名称" AND ("repository" OR "Zenodo" OR "PANGAEA" OR "DOI") 的 query。
#     - 如果验证DOI：直接将候选 DOI 作为 query 进行搜索，看其指向的具体页面内容。
#     """
#     return web_search_tool.invoke({"query": query})

# # 只给大模型提供这一个极其自由且强大的工具
# tools = [verify_and_search_metadata]

# @tool
# def search_dataset_metadata(query: str) -> str:
#     """
#     用于搜索数据集的官方论文(Data Descriptor)、数据仓库(Repository)或验证DOI。
#     请根据用户提供的数据集名称、作者、机构或URL，自主构造精准的搜索词。
#     例如：'"Dataset Name" repository DOI' 或 '"Author Name" "data descriptor"'。
#     """
#     # Tool 内部不再写死任何关键词，只做纯粹的搜索执行
#     return web_search_tool.invoke(query)

# tools = [search_dataset_metadata]

# @tool
# def verify_doi_and_platform(doi_or_url: str) -> str:
#     """用于验证 DOI 是否真实存在，或查询某个数据集的官方托管平台。"""
#     # 这里实际上会调用 web_search_tool，为了简化，我们直接复用搜索
#     query = f"DOI {doi_or_url} repository OR 'data descriptor' OR 'ESSD'"
#     return web_search_tool.invoke(query)

# tools = [web_search_tool, verify_doi_and_platform]

# ==========================================
# 3. 构建 LangGraph 节点
# ==========================================

# ----------------- 手动补丁 (Request 接口改写) 开始 -----------------
# 修改时间: 2026-06-29
# 修改原因: 将原本依赖 langchain_openai.ChatOpenAI 的调用方式，改为最纯粹的 requests 接口调用，
# 以便对接任何标准 API 接口，并彻底解决 reasoning_content（思维链）在复杂封装中丢失的问题。
import uuid
from langchain_core.utils.function_calling import convert_to_openai_tool


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
    data_doi: Optional[str] = Field(description="干净的数据DOI号 (10.xxxx/xxxx)，若无明确本体DOI则返回 null", default=None)
    official_website: Optional[str] = Field(description="数据集官网或托管平台名称 (例如: Zenodo, PANGAEA, ScienceDB, OSTI, GBIF等)，若无则返回 null", default=None)
    official_website_id: Optional[str] = Field(description="数据集在官网内部的具体ID或编号，若无则返回 null", default=None)
    dataset_shortname: Optional[str] = Field(description="数据集简称或代号(shortname)，对于NASA或LAADS DAAC等平台非常重要，若无则返回 null", default=None)
    version_name: Optional[str] = Field(description="该数据集的具体版本号或年份标识 (例如: '2024', 'v1.2', 'Collection 2')，用于区分同名数据集的不同历史快照，若无则返回 null", default=None)
    extracted_api_params: Optional[dict] = Field(
        description="根据目标 API 所需的参数提取对应的值。例如如果目标 API 提示(需要参数: ['short_name'])，则在这里提取 {'short_name': 'MOD11A1'} 等键值对。",
        default=None
    )
    target_api_name: Optional[List[str]] = Field(
        description=IntegratedDataRepoFetcher.get_api_schema_desc() + " 【绝对禁令】：只有当 official_website 在字面上与列表中的某个平台名称高度吻合时才能选择。绝不允许做语义联想。如果不严格匹配，必须输出空列表 [] ！！！",
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
    print("⚡ [节点: 检索] 大模型正在思考是否需要使用全网搜索或抓取工具...")
    messages = state["messages"]
    # 开启工具调用
    response = custom_request_llm_invoke(messages, use_tools=True)
    return {"messages": [response]}

def should_continue(state: AgentState):
    """判断是否需要继续调用工具，还是进入信息提取节点"""
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        print(f"   🔧 决定调用工具 (共 {len(last_message.tool_calls)} 个):")
        for tc in last_message.tool_calls:
            args = tc.get('args', {})
            if tc['name'] == 'academic_web_search':
                print(f"      - 🔍 搜索关键词: {args.get('query')}")
            elif tc['name'] == 'read_and_verify_url':
                print(f"      - 📖 阅读网页/DOI: {args.get('url_or_doi')}")
            else:
                print(f"      - ⚙️ {tc['name']}: {args}")
        return "tools"
    
    # 打印大模型在检索阶段最后的总结论
    conclusion = getattr(last_message, "content", "无结论")
    if conclusion:
        # 如果结论太长，可能需要截断显示或者完整显示，这里展示完整结论
        print(f"   💡 检索阶段得出结论:\n      {conclusion.strip()}")
    else:
        print("   ✅ 检索完毕 (未输出结论文本)")
        
    print("   ✅ 准备提取结构化数据...")
    return "extract"

# ----------------------------------
# (2) 结构化提取节点
# ----------------------------------
def extract_node(state: AgentState):
    """基于前期检索到的信息，强制结构化输出 DatasetExtractionList"""
    print("⚡ [节点: 提取] 开始从收集到的信息中穷尽提取所有版本的数据集...")
    context = "\n".join([m.content for m in state["messages"] if hasattr(m, "content") and m.content])
    
    schema_str = json.dumps(DatasetExtractionList.model_json_schema(), ensure_ascii=False, indent=2)
    
    extraction_prompt = f"""
基于以下收集到的信息，严格提取数据集的元数据。
如果没有找到某个字段对应的值，请返回 null。
如果包含多个年度版本，请在 datasets 数组中把每一个版本单独列出。

【严格过滤规则】
衍生版过滤：请务必只提取与用户初始描述**完全匹配**的标准版/科学版数据集。严禁提取任何衍生版、附加版。【特别例外】：对于跨越多年度的系列数据集，即使早期版本记录简陋、缺乏 DOI、或不确定是否为标准版，只要是官方发布的该年度主快照，请务必全量保留，绝对不可因“不确定”而丢弃！


【格式要求】
你必须输出一段合法的 JSON 字符串，且必须严格符合以下 JSON Schema 结构：
{schema_str}
不要输出任何解释性文本或 markdown 代码块语法，只能输出 JSON 数据本身。

【收集到的信息】：
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
        print(f"⚠️ 解析 LLM 输出失败: {e}")
        extracted_datasets = []
        
    print(f"   ➤ 提取到 {len(extracted_datasets)} 个版本结果")
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
    print(f"   ⚠️ 已将失败记录保存至 {error_file}，原因: {reason}")
# 2. 废弃版过滤：如果页面明确标明某个版本已经“Retired（退休）”、“Deprecated（废弃）”或“Terminated（彻底下线删除）”，请直接丢弃该版本。但请注意区分：**正常的年度历史快照不属于废弃版，必须正常保留和提取**，只丢弃那些被官方明确打上作废/瑕疵标签的版本。
# ----------------------------------
# (3) API 抓取节点
# ----------------------------------
def fetch_metadata_node(state: AgentState):
    """根据提取到的信息，循环分别调用三个工具获取所有版本的元数据"""
    print("⚡ [节点: 抓取] 开始从各大 API 获取元数据...")
    extracted_datasets = state.get("extracted_datasets", [])
    
    final_results = []
    
    for idx, extracted_info in enumerate(extracted_datasets):
        doi = extracted_info.get("data_doi")
        publisher = extracted_info.get("official_website")
        official_id = extracted_info.get("official_website_id")
        target_api = extracted_info.get("target_api_name")
        version_name = extracted_info.get("version_name")
        shortname = extracted_info.get("dataset_shortname")
        
        display_name = ""
        if shortname and version_name:
            display_name = f"{shortname} {version_name}"
        elif version_name:
            display_name = f"版本 {version_name}"
        elif shortname:
            display_name = f"{shortname}"
            
        print(f"\n   🔄 [版本 {idx+1}/{len(extracted_datasets)}] 开始抓取流程" + (f" ({display_name})" if display_name else "") + "...")
        print(f"      - DOI: {doi}")
        print(f"      - 官网: {publisher} (内部ID: {official_id})")
        print(f"      - 目标API: {target_api}")
        
        doi_org_data = {}
        datacite_crossref_data = {}
        official_api_data = {}
    
        # [1] 抓取 doi.org
        if doi:
            print(f"   👉 [doi.org] 请求 DOI: {doi}")
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
                    print("      ✅ 成功")
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
            print(f"   👉 [DataCite/Crossref] 请求 DOI: {doi}")
            meta, err = fetch_from_datacite(doi)
            if meta:
                datacite_crossref_data = {"source": "DataCite", "data": meta}
                print("      ✅ DataCite 成功")
            else:
                if err:
                    import datetime
                    with open(REGISTRY_API_LOG_FILE, "a", encoding="utf-8") as f:
                        f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] DOI: {doi} | Registry: DataCite | ERROR: {err}\n")
                meta2, err2 = fetch_from_crossref(doi)
                if meta2:
                    datacite_crossref_data = {"source": "Crossref", "data": meta2}
                    print("      ✅ Crossref 成功")
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
            print(f"   👉 [官网 API] 智能匹配到插件列表: {target_apis} ...")
            fetcher = IntegratedDataRepoFetcher()
            route_map = fetcher.get_route_map()
        
            success = False
            all_errors = []
            for api_name in target_apis:
                print(f"      ▶ 尝试 API: {api_name}")
                matched_func = route_map.get(api_name)
            
                if not matched_func:
                    err_msg = f"未找到 '{api_name}' 的生成代码"
                    print(f"      ⚠️ {err_msg}")
                    all_errors.append(err_msg)
                    import datetime
                    with open(API_FALLBACK_LOG_FILE, "a", encoding="utf-8") as f:
                        f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] DOI: {doi} | API: {api_name} | ERROR: {err_msg}\n")
                    continue
                
                try:
                    import inspect
                    sig = inspect.signature(matched_func)
                    has_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
                
                    if has_kwargs:
                        official_api_data = matched_func(
                            doi=doi, 
                            official_website_id=official_id, 
                            dataset_shortname=extracted_info.get("dataset_shortname"),
                            extracted_api_params=extracted_info.get("extracted_api_params", {})
                        )
                    else:
                        identifier = doi if doi else official_id
                        if identifier:
                            official_api_data = matched_func(identifier)
                        else:
                            raise ValueError("缺少 identifier (doi 或 official_id) 供手写函数使用")
                        
                    if "error" in official_api_data:
                        err_msg = f"API_ERROR: {official_api_data['error']}"
                        all_errors.append(err_msg)
                        print(f"      ⚠️ API 报错: {official_api_data['error']}")
                        import datetime
                        with open(API_FALLBACK_LOG_FILE, "a", encoding="utf-8") as f:
                            f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] DOI: {doi} | API: {api_name} | ERROR: {err_msg}\n")
                    else:
                        print(f"      ✅ 官网抓取调用完成 (使用 {api_name})")
                        success = True
                        break # 成功命中并获取数据，跳出循环
                except ValueError as e:
                    err_msg = f"MISSING_PARAMS: {str(e)}"
                    all_errors.append(err_msg)
                    print(f"      ⚠️ 参数不足: {e}")
                    import datetime
                    with open(API_FALLBACK_LOG_FILE, "a", encoding="utf-8") as f:
                        f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] DOI: {doi} | API: {api_name} | ERROR: {err_msg}\n")
                except Exception as e:
                    err_msg = f"SYSTEM_ERROR: {str(e)}"
                    all_errors.append(err_msg)
                    print(f"      ⚠️ 调用异常: {e}")
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

def process_target_datasets():
    app = build_agent()
    
    # 确保输出目录存在
    output_dir = OUTPUT_RESULTS_DIR
    os.makedirs(output_dir, exist_ok=True)
    
    log_file = os.path.join(output_dir, "batch_process.log")
    
    def log_msg(msg: str):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {msg}"
        print(line)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            
    log_msg(f"🚀 开始批量处理目标数据集，输入文件: {INPUT_DATASET_FILE}")
    
    if not os.path.exists(INPUT_DATASET_FILE):
        log_msg(f"❌ 找不到输入文件: {INPUT_DATASET_FILE}")
        return
        
    with open(INPUT_DATASET_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    header_line = ""
    # 去除表头并保存
    if len(lines) > 0 and "数据集ID" in lines[0]:
        header_line = lines[0]
        lines = lines[1:]
        
    # 限制处理数量
    lines = lines[:MAX_RECORDS_TO_PROCESS]
    
    for line in lines:
        line = line.strip()
        if not line: continue
        parts = line.split('\t')
        if len(parts) < 2: continue
        
        dataset_id = parts[0]
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
            log_msg(f"⏩ 数据集 ID: {dataset_id} 已满足跳过条件 (成功:{len(success_files)}个, 失败/崩溃:{len(error_files)}个)，跳过处理。")
            continue
            
        # 如果不跳过（即需要重跑），则自动删掉历史的错误或崩溃文件，保持目录干净
        if len(error_files) > 0:
            log_msg(f"♻️ 准备重新处理数据集 ID: {dataset_id}，正在清理 {len(error_files)} 个历史错误记录...")
            for ef in error_files:
                try:
                    os.remove(ef)
                except Exception as e:
                    pass
            
        log_msg(f"--------------------------------------------------")
        log_msg(f"⚡ 开始处理数据集 ID: {dataset_id} | 名称: {dataset_name}")
        
        test_input = f"【目标数据集描述】\n{line}\n请先搜搜这篇数据，并确认具体信息后再提取。"
        
        system_prompt = """你是一个资深的数据科学家。
你的任务是调查用户提供的数据集描述，你可以使用网页搜索(academic_web_search)和网页阅读工具(read_and_verify_url)收集信息。
【核心纪律】：请优先阅读数据集的官方介绍页。绝对避免反复阅读整篇长达数十页的期刊论文，这会导致上下文超限崩溃！你只需要粗略搜索版本名和DOI即可。
如果这是一个包含历年迭代版本的数据集，请穷尽搜索其历史版本的 DOI 和官网信息，把能找到的所有官方版本查清。
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
            # 运行 LangGraph，强制加上递归深度限制，防止大模型死循环
            final_state = app.invoke(initial_state, config={"recursion_limit": MAX_SEARCH_ITERATIONS})
            final_results = final_state.get("final_results", [])
            
            if not final_results:
                log_msg(f"⚠️ 提取失败: 未找到任何数据集版本")
                continue
                
            for idx, final_metadata in enumerate(final_results):
                input_summary = final_metadata.get("input_summary", {})
                
                # 优先使用 DOI 作为后缀，确保绝对唯一；如果没有则降级使用 website_id 或短名
                doi_str = input_summary.get("data_doi")
                website_id = input_summary.get("official_website_id")
                shortname = input_summary.get("dataset_shortname")
                version_name = input_summary.get("version_name")
                
                if doi_str and doi_str.strip():
                    raw_suffix = doi_str.strip()
                elif version_name and shortname:
                    raw_suffix = f"{shortname.strip()}_{version_name.strip()}"
                elif website_id and website_id.strip():
                    raw_suffix = website_id.strip()
                elif version_name and version_name.strip():
                    raw_suffix = f"version_{version_name.strip()}"
                elif shortname and shortname.strip():
                    raw_suffix = f"{shortname.strip()}_v{idx+1}"
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
                    log_msg(f"✅ 处理成功！已保存至 {success_file}")
                else:
                    error_file = os.path.join(output_dir, f"{dataset_id}-{suffix}_error.json")
                    with open(error_file, "w", encoding="utf-8") as f:
                        json.dump(final_metadata, f, ensure_ascii=False, indent=2)
                    
                    if is_missing_registry:
                        log_msg(f"⚠️ 未命中官网知识库 API，已保存至 {error_file}，并追加到 {MISSING_REGISTRY_FILE}")
                        missing_file = MISSING_REGISTRY_FILE
                        # 确保如果写入多个缺失版本，原始文本行也能被追加（这里统一记录该行）
                        # 如果文件不存在，写入表头
                        if not os.path.exists(missing_file) and header_line:
                            with open(missing_file, "w", encoding="utf-8") as f:
                                f.write(header_line.strip() + "\t内部版本标识\t提取到的版本号\t缺失的官网名称(提取值)\t提取的DOI\n")
                        # 实时追加
                        missing_publisher = input_summary.get("official_website") or "Unknown"
                        missing_doi = input_summary.get("data_doi") or "NULL"
                        extracted_version = input_summary.get("version_name") or "Unknown"
                        
                        with open(missing_file, "a", encoding="utf-8") as f:
                            f.write(f"{line}\t[{suffix}]\t{extracted_version}\t{missing_publisher}\t{missing_doi}\n")
                    else:
                        log_msg(f"⚠️ 官网API请求报错，已保存至 {error_file}")
                
        except Exception as e:
            error_msg = f"系统异常: {str(e)}\n{traceback.format_exc()}"
            log_msg(f"❌ 运行崩溃: {error_msg}")
            error_file = os.path.join(output_dir, f"{dataset_id}_crash.json")
            with open(error_file, "w", encoding="utf-8") as f:
                json.dump({"error_traceback": error_msg}, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    process_target_datasets()
