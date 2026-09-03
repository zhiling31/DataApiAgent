# -*- coding: utf-8 -*-
import argparse
import copy
import datetime
import glob
import importlib
import json
import logging
import os
import re
import requests
import sys
import threading
import time
import traceback
import urllib3
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from curl_cffi import requests as cffi_requests
from dataset_extractor import extract_dataset_info
from dataset_extractor import tools
from fetch_datacite_metadata import fetch_from_datacite, fetch_from_crossref, fetch_with_retry
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.tools import tool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field
from typing import TypedDict, Annotated, List, Optional


# ==========================================
# 0. 全局配置与参数管理
# ==========================================

# -----------------
# 0.1 线程与并发控制
# -----------------
# 控制主处理流程的最大线程数（每个线程处理一条数据集记录）
MAX_WORKERS = 5
# 全局文件锁，用于保护多线程并发时对本地日志、缓存等文件的写入操作
global_file_lock = threading.Lock()
# 大模型并发请求信号量，限制向云端发送 POST 请求的最大并行数，防止触发 429 限流
llm_semaphore = threading.Semaphore(10)

# -----------------
# 0.2 文件路径配置
# -----------------
# 输入的原始数据集文件 (制表符分隔) Crustal ages_master-35个
INPUT_DATASET_FILE = r"D:\地学\doi\数据清单\test\Faults_master-26个_unique_website.txt"
# 运行结果(成功或报错的 JSON)的保存目录
OUTPUT_RESULTS_DIR = r"D:\地学\doi\数据清单\test\Faults_master-26个"
# 数据集缓存文件，用于记录已经成功提取过目标版本信息的数据集
dataset_info_cache_file = os.path.join(OUTPUT_RESULTS_DIR, "dataset_info_cache.json")
# 未命中任何已知官网知识库 API 的记录文件
MISSING_REGISTRY_FILE = os.path.join(OUTPUT_RESULTS_DIR, "missing_registry_datasets.txt")
# 多 API 尝试期间，中间抓取失败的备用日志
API_FALLBACK_LOG_FILE = os.path.join(OUTPUT_RESULTS_DIR, "api_fallback_errors.log")
# 官方注册机构 (doi.org, DataCite, Crossref) 调用出错的日志
REGISTRY_API_LOG_FILE = os.path.join(OUTPUT_RESULTS_DIR, "doi_registry_api_errors.log")

# -----------------
# 0.3 业务逻辑参数配置
# -----------------
# 每次批量测试的最大数量（如果指定了 --id 进行单测，此限制将被忽略）
MAX_RECORDS_TO_PROCESS = 35
# 是否启用数据集大模型提取信息的本地缓存
USE_DATASET_INFO_CACHE = True
# 续传模式: 
# "1": 只要有结果(成功或报错)即跳过该条目
# "2-1": 只要有报错结果(_error.json)，即删除报错文件并重新跑完整大模型检索流程
# "2-2": 只要有报错结果(_error.json)，提取原报错文件中的信息，跳过大模型检索，直接重新跑 API 获取流程
# "2-3": 只要有报错结果(_error.json)，提取原报错文件中的信息，但是重新交给大模型匹配目标 API 后抓取
RESUME_MODE = "1"
# 大模型搜索节点的最大循环思考次数 (默认 35，值过大会增加死循环和 Token 爆炸的风险)
MAX_SEARCH_ITERATIONS = 35
# 动态导入的具体抓取脚本模块路径，方便后续随官网更新而动态替换抓取脚本版本
INTEGRATED_FETCHER_MODULE = "code_result.fetch_top_dataset_integrated"

# 屏蔽 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# Logger Configuration
# ==========================================
os.makedirs(OUTPUT_RESULTS_DIR, exist_ok=True)
logger = logging.getLogger('DatasetAgent')
logger.setLevel(logging.INFO)
# Avoid adding handlers multiple times if module is reloaded
# Clear existing handlers (like the one added by dataset_extractor.py)
logger.handlers.clear()

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
IntegratedDataRepoFetcher = importlib.import_module(INTEGRATED_FETCHER_MODULE).IntegratedDataRepoFetcher


# Tools are now imported from dataset_extractor.py

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
        
    max_retries = 6
    for attempt in range(max_retries):
        try:
            with llm_semaphore:
                response = requests.post(url, headers=headers, json=payload, timeout=120, verify=False)
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


class TargetApiMatch(BaseModel):
    target_api_name: List[str] = Field(
        description= "【语义生态穿透匹配】：请利用你的图情专业知识，判断当前数据集的托管机构或系统简称是否属于上述列表中的某个机构。如果是，请把列表中的准确名称提取出来；如果毫无关联，再返回空列表 []。记住，不用强行越界匹配"
    )

def match_target_api_with_llm(dataset_info: dict, custom_request_llm_invoke) -> List[str]:
    """使用大模型根据提取的数据集信息匹配目标 API"""
    schema_str = json.dumps(TargetApiMatch.model_json_schema(), ensure_ascii=False, indent=2)
    
    # 兼容老缓存
    publisher_list = dataset_info.get("official_websites", [])
    if not publisher_list and "official_website" in dataset_info:
        val = dataset_info["official_website"]
        publisher_list = [val] if val else []

    prompt = f"""
【数据集托管平台匹配】：请利用你的图情专业知识，判断当前数据集的托管机构或系统简称是否属于可选官网列表中的某个机构。如果是，请把列表中的准确名称提取出来；如果找不到可匹配的官网，再返回空列表 []。记住，不用强行越界匹配

【数据集信息】
- 候选官网/托管平台列表: {publisher_list}

【可选官网列表】
{IntegratedDataRepoFetcher.get_api_schema_desc()}

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

def resolve_doi_to_url(doi: str) -> str:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"}
        res = cffi_requests.get(f"https://doi.org/{doi}", allow_redirects=True, timeout=30, headers=headers, impersonate="chrome110")
        return res.url
    except Exception as e:
        logger.error(f"  {doi} ⚠️ [DOI重定向] 解析失败: {e}")
        return ""

def fetch_metadata_node(state: dict):
    """根据提取到的信息，循环分别调用三个工具获取所有版本的元数据"""
    logger.info("⚡ [节点: 抓取] 开始从各大 API 获取元数据...")
    raw_extracted_datasets = state.get("extracted_datasets", [])
    
    # 提前解析 doi_landing_page
    extracted_datasets = []
    for ds in raw_extracted_datasets:
        doi = ds.get("doi")
        if doi:
            real_url = resolve_doi_to_url(doi)
            if real_url:
                ds["doi_landing_page"] = real_url
        extracted_datasets.append(ds)
    
    final_results = []
    
    for idx, extracted_info in enumerate(extracted_datasets):
        doi = extracted_info.get("doi")
        publisher_list = extracted_info.get("official_websites", [])
        if not publisher_list and "official_website" in extracted_info:
            publisher_list = [extracted_info["official_website"]]
            
        target_api = extracted_info.get("target_api_name")
        version_name = extracted_info.get("version_name")
        
        display_name = ""
        if version_name:
            display_name = f"版本 {version_name}"
            
        logger.info(f"\n   🔄 [版本 {idx+1}/{len(extracted_datasets)}] 开始抓取流程" + (f" ({display_name})" if display_name else "") + "...")
        logger.info(f"      - DOI: {doi}")
        logger.info(f"      - 候选官网: {publisher_list}")
        logger.info(f"      - 目标API: {target_api}")
        
        doi_org_data = {}
        datacite_crossref_data = {}
        official_api_data = {}
        success_api = None
        api_attempts = []
    
        # [1] 抓取 doi.org
        if doi:
            logger.info(f"   👉 [doi.org] 请求 DOI: {doi}")
            headers = {"Accept": "application/vnd.citationstyles.csl+json", "User-Agent": "DataLibrarianAgent/4.0"}
            res, err = fetch_with_retry(f"https://doi.org/{doi}", headers=headers, max_retries=3)
            if err:
                doi_org_data = {"error": err}
                with global_file_lock:
                    with open(REGISTRY_API_LOG_FILE, "a", encoding="utf-8") as f:
                        f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] DOI: {doi} | Registry: doi.org | ERROR: {err}\n")
            elif res and res.status_code == 200:
                try:
                    doi_org_data = {"source": "doi.org (CSL-JSON)", "data": res.json()}
                    logger.info("      ✅ 成功")
                except Exception as e:
                    doi_org_data = {"error": f"JSON解析错误: {e}"}
                    with global_file_lock:
                        with open(REGISTRY_API_LOG_FILE, "a", encoding="utf-8") as f:
                            f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] DOI: {doi} | Registry: doi.org | ERROR: JSON Parse Error {e}\n")
            else:
                status = res.status_code if res else "Unknown"
                doi_org_data = {"error": f"HTTP {status}"}
                with global_file_lock:
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
                    with global_file_lock:
                        with open(REGISTRY_API_LOG_FILE, "a", encoding="utf-8") as f:
                            f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] DOI: {doi} | Registry: DataCite | ERROR: {err}\n")
                meta2, err2 = fetch_from_crossref(doi)
                if meta2:
                    datacite_crossref_data = {"source": "Crossref", "data": meta2}
                    logger.info("      ✅ Crossref 成功")
                else:
                    datacite_crossref_data = {"error": f"DataCite error: {err} | Crossref error: {err2}"}
                    if err2:
                        with global_file_lock:
                            with open(REGISTRY_API_LOG_FILE, "a", encoding="utf-8") as f:
                                f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] DOI: {doi} | Registry: Crossref | ERROR: {err2}\n")


        target_apis = []
        if target_api:
            if isinstance(target_api, list):
                target_apis = target_api
            elif isinstance(target_api, str):
                target_apis = [target_api]

        if publisher_list and target_apis:
            logger.info(f"   👉 [官网 API] 智能匹配到插件列表: {target_apis} ...")
            fetcher = IntegratedDataRepoFetcher()
            route_map = fetcher.get_route_map()
        
            success = False
            for api_name in target_apis:
                logger.info(f"      👉 尝试 API: {api_name}")
                matched_func = route_map.get(api_name)
            
                if not matched_func:
                    err_msg = "[UNREGISTERED_UNKNOWN_PLATFORM] 未找到生成代码，平台未知"
                    logger.warning(f"      ⚠️ {err_msg}")
                    api_attempts.append({"api": api_name, "error": err_msg})
                    with global_file_lock:
                        with open(API_FALLBACK_LOG_FILE, "a", encoding="utf-8") as f:
                            f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] DOI: {doi} | API: {api_name} | ERROR: {err_msg}\n")
                    continue
                
                # 0ms Interception Logic
                is_reviewed = getattr(matched_func, "is_reviewed", False)
                if not is_reviewed:
                    err_msg = "[NO_REVIEWED_API] 平台API尚未人工审核，拒绝执行"
                    logger.warning(f"      ⚠️ {err_msg}")
                    api_attempts.append({"api": api_name, "error": err_msg})
                    with global_file_lock:
                        with open(API_FALLBACK_LOG_FILE, "a", encoding="utf-8") as f:
                            f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] DOI: {doi} | API: {api_name} | ERROR: {err_msg}\n")
                    continue

                has_api = getattr(matched_func, "has_api", True)
                if not has_api:
                    auditor_notes = getattr(matched_func, "auditor_notes", "无")
                    err_msg = f"[KNOWN_NO_API_PLATFORM] 审核备注: {auditor_notes}"
                    logger.warning(f"      ⚠️ {err_msg}")
                    api_attempts.append({"api": api_name, "error": err_msg})
                    with global_file_lock:
                        with open(API_FALLBACK_LOG_FILE, "a", encoding="utf-8") as f:
                            f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] DOI: {doi} | API: {api_name} | ERROR: {err_msg}\n")
                    continue
                
                try:
                    official_api_data = matched_func(**extracted_info)
                        
                    if "error" in official_api_data:
                        raw_error = official_api_data['error']
                        raw_error = re.sub(r'，[^，]*兜底.*', '', raw_error)
                        err_msg = f"[VERIFIED_API_EXEC_ERROR] {raw_error}"
                        api_attempts.append({"api": api_name, "error": err_msg})
                        logger.warning(f"      ⚠️ API 报错: {err_msg}")
                        with global_file_lock:
                            with open(API_FALLBACK_LOG_FILE, "a", encoding="utf-8") as f:
                                f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] DOI: {doi} | API: {api_name} | ERROR: {err_msg}\n")
                    else:
                        logger.info(f"      ✅ 官网抓取调用完成 (使用 {api_name})")
                        success_api = api_name
                        success = True
                        break # 成功命中并获取数据，跳出循环
                except ValueError as e:
                    err_msg = str(e)
                    api_attempts.append({"api": api_name, "error": err_msg})
                    logger.warning(f"      ⚠️ 参数不足: {err_msg}")
                    with global_file_lock:
                        with open(API_FALLBACK_LOG_FILE, "a", encoding="utf-8") as f:
                            f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] DOI: {doi} | API: {api_name} | ERROR: {err_msg}\n")
                except Exception as e:
                    err_msg = str(e)
                    api_attempts.append({"api": api_name, "error": err_msg})
                    logger.warning(f"      ⚠️ 调用异常: {err_msg}")
                    with global_file_lock:
                        with open(API_FALLBACK_LOG_FILE, "a", encoding="utf-8") as f:
                            f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] DOI: {doi} | API: {api_name} | ERROR: {err_msg}\n")
                
            if not success:
                official_api_data = {"error": " | ".join([f"{a['api']}:{a['error']}" for a in api_attempts])}
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
        if success_api:
            final_result["success_api"] = success_api
        if api_attempts:
            final_result["api_attempts"] = api_attempts
            
        final_results.append(final_result)
        
    return {"final_results": final_results}


# 5. 批量测试与日志输出
# ==========================================

if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

def process_target_datasets(target_id=None):
    
    # 确保输出目录存在
    output_dir = OUTPUT_RESULTS_DIR
    data_dir = os.path.join(output_dir, "data")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(data_dir, exist_ok=True)
    
    # 加载数据集信息缓存
    dataset_info_cache = {}
    if USE_DATASET_INFO_CACHE:
        if os.path.exists(dataset_info_cache_file):
            try:
                with open(dataset_info_cache_file, "r", encoding="utf-8") as cf:
                    dataset_info_cache = json.load(cf)
                logger.info(f"✅ 成功加载数据集信息缓存: {dataset_info_cache_file} (共 {len(dataset_info_cache)} 条)")
            except Exception as e:
                logger.warning(f"⚠️ 读取缓存文件失败，将不使用缓存: {e}")
        else:
            logger.warning(f"⚠️ 缓存文件不存在，将降级调用大模型提取: {dataset_info_cache_file}")

    log_file = os.path.join(output_dir, "batch_process.log")
    if not os.path.exists(INPUT_DATASET_FILE):
        logger.error(f"❌ 找不到输入文件: {INPUT_DATASET_FILE}")
        return
        
    with open(INPUT_DATASET_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    header_line = ""
    headers = []
    # 动态解析表头
    if len(lines) > 0:
        header_line = lines[0].strip()
        headers = header_line.split('\t')
        lines = lines[1:]
        
    # 限制处理数量 (如果是单测模式，则不截断)
    if not target_id:
        lines = lines[:MAX_RECORDS_TO_PROCESS]
    

    logger.info(f"🔥 开始多线程并发执行，最大并发数: {MAX_WORKERS}")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_single_dataset, line, idx_line, target_id, headers, data_dir, dataset_info_cache, header_line) for idx_line, line in enumerate(lines)]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                logger.error(f"线程执行异常: {e}")


def process_single_dataset(line, idx_line, target_id, headers, data_dir, dataset_info_cache, header_line):
    line = line.strip()
    if not line: return
    parts = line.split('\t')
    if not parts: return
    
    # 提取各个字段值，通过列名匹配或者索引降级
    row_dict = {h: (parts[i] if i < len(parts) else "") for i, h in enumerate(headers)}
    
    dataset_id = ""
    dataset_name = ""
    dataset_description = ""
    url = ""
    
    for h, v in row_dict.items():
        if "ID" in h.upper() or "标识" in h:
            if not dataset_id: dataset_id = v
        elif "名称" in h or "NAME" in h.upper():
            if not dataset_name: dataset_name = v
        elif "描述" in h or "DESCRIPTION" in h.upper():
            if not dataset_description: dataset_description = v
        elif "URL" in h.upper() or "链接" in h:
            if not url: url = v
            
    # Fallbacks
    if not dataset_id: dataset_id = parts[0] if len(parts) > 0 else str(idx_line + 1)
    if not dataset_name: dataset_name = parts[1] if len(parts) > 1 else ""
    if not dataset_description: dataset_description = parts[2] if len(parts) > 2 else ""
    if not url: url = parts[3] if len(parts) > 3 else ""
    
    # 如果指定了单测 ID，跳过其他数据
    if target_id and dataset_id != str(target_id):
        return

    # 构造格式化的输入给大模型
    formatted_line = "，".join([f"{h}:{v}" for h, v in zip(headers, parts) if h and v])
    logger.info(f"用户原始输入：{formatted_line}")
    
    # 断点续传逻辑更新：检查是否存在以该 dataset_id- 开头的 JSON 文件
    existing_files = glob.glob(os.path.join(data_dir, f"{dataset_id}-*.json"))
    success_files = [f for f in existing_files if not f.endswith("_error.json") and not f.endswith("_crash.json")]
    error_files = [f for f in existing_files if f.endswith("_error.json") or f.endswith("_crash.json")]
    
    should_skip = False
    if RESUME_MODE == "1":
        # 模式1：只要有结果（成功或报错或崩溃），即跳过
        if len(existing_files) > 0:
            should_skip = True
    elif RESUME_MODE in ["2-1", "2-2", "2-3"]:
        # 模式2：只要有报错或崩溃结果(_error.json / _crash.json)，就不跳过（需要重跑）；否则如果全是成功则跳过
        if len(success_files) > 0 and len(error_files) == 0:
            should_skip = True
            
    if should_skip:
        logger.info(f"⏩ 数据集 ID: {dataset_id} 已满足跳过条件 (成功:{len(success_files)}个, 失败/崩溃:{len(error_files)}个)，跳过处理。")
        return
        
    # 准备重跑前，预先处理 _error.json 等文件
    extracted_datasets_for_mode_2_2 = []
    is_mode_2_2_valid = False
    
    if len(error_files) > 0:
        if RESUME_MODE in ["2-2", "2-3"]:
            is_mode_2_2_valid = True
            for ef in error_files:
                if ef.endswith("_crash.json"):
                    logger.warning(f"⚠️ 发现 {ef} (系统崩溃日志)，无法使用模式 2-2 提取信息，将自动降级为完整的 2-1 重跑流程。")
                    is_mode_2_2_valid = False
                    break
                try:
                    with open(ef, "r", encoding="utf-8") as f:
                        err_data = json.load(f)
                        if "input_summary" in err_data:
                            extracted_datasets_for_mode_2_2.append(err_data["input_summary"])
                        else:
                            is_mode_2_2_valid = False
                            break
                except Exception as e:
                    logger.warning(f"⚠️ 读取 {ef} 失败: {e}，将自动降级为模式 2-1。")
                    is_mode_2_2_valid = False
                    break
        
        # 删除旧的报错或崩溃文件
        logger.info(f"♻️ 准备重新处理数据集 ID: {dataset_id}，正在清理 {len(error_files)} 个历史错误记录...")
        for ef in error_files:
            try:
                os.remove(ef)
            except Exception as e:
                pass
        
    logger.info(f"--------------------------------------------------")
    logger.info(f"⚡ 开始处理数据集 ID: {dataset_id} | 名称: {dataset_name}")
    
    test_input_dict = {
        "dataset_id": dataset_id,
        "dataset_name": dataset_name,
        "dataset_description": dataset_description,
        "url": url
    }
    
    try:
        if RESUME_MODE == "2-3" and is_mode_2_2_valid and len(extracted_datasets_for_mode_2_2) > 0:
            logger.info(f"🚀 [模式 2-3] 跳过大模型检索，基于 {len(extracted_datasets_for_mode_2_2)} 个原结果重新匹配目标 API 并抓取...")
            for ds in extracted_datasets_for_mode_2_2:
                if "target_api_name" in ds:
                    del ds["target_api_name"]
                ds["target_api_name"] = match_target_api_with_llm(ds, custom_request_llm_invoke)
            mock_state = {"extracted_datasets": extracted_datasets_for_mode_2_2}
            fetch_result = fetch_metadata_node(mock_state)
            final_results = fetch_result.get("final_results", [])
        elif RESUME_MODE == "2-2" and is_mode_2_2_valid and len(extracted_datasets_for_mode_2_2) > 0:
            logger.info(f"🚀 [模式 2-2] 跳过大模型检索，直接基于 {len(extracted_datasets_for_mode_2_2)} 个原结果信息重新触发 API 抓取...")
            mock_state = {"extracted_datasets": extracted_datasets_for_mode_2_2}
            fetch_result = fetch_metadata_node(mock_state)
            final_results = fetch_result.get("final_results", [])
        else:
            extracted_datasets = None
            
            # 检查缓存
            if USE_DATASET_INFO_CACHE and str(dataset_id) in dataset_info_cache:
                logger.info(f"🎯 从缓存中命中了数据集提取信息: {dataset_id}")
                extracted_datasets = copy.deepcopy(dataset_info_cache[str(dataset_id)])
            
            # 如果没命中缓存，则走大模型提取
            if not extracted_datasets:
                extracted_datasets = extract_dataset_info(test_input_dict, custom_request_llm_invoke)
                # 提取完成后立刻保存到缓存（受全局锁保护）
                if USE_DATASET_INFO_CACHE and extracted_datasets:
                    with global_file_lock:
                        # 存入缓存时剔除 target_api_name
                        cache_data = copy.deepcopy(extracted_datasets)
                        for ds in cache_data:
                            ds.pop("target_api_name", None)
                        dataset_info_cache[str(dataset_id)] = cache_data
                        try:
                            with open(dataset_info_cache_file, "w", encoding="utf-8") as f:
                                json.dump(dataset_info_cache, f, ensure_ascii=False, indent=2)
                        except Exception as e:
                            logger.error(f"⚠️ 缓存写入文件失败: {e}")
            
            for ds in extracted_datasets:
                if "target_api_name" not in ds:
                    ds["target_api_name"] = match_target_api_with_llm(ds, custom_request_llm_invoke)
            
            mock_state = {"extracted_datasets": extracted_datasets}
            fetch_result = fetch_metadata_node(mock_state)
            final_results = fetch_result.get("final_results", [])
        
        if not final_results:
            logger.warning(f"⚠️ 提取失败: 未找到任何数据集版本")
            return
            
        for idx, final_metadata in enumerate(final_results):
            # 注入初始输入的参数
            final_metadata["original_input"] = {
                "dataset_name": dataset_name,
                "dataset_description": dataset_description,
                "url": url
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
                success_file = os.path.join(data_dir, f"{dataset_id}-{suffix}.json")
                with open(success_file, "w", encoding="utf-8") as f:
                    json.dump(final_metadata, f, ensure_ascii=False, indent=2)
                logger.info(f"✅ 处理成功！已保存至 {success_file}")
            else:
                error_file = os.path.join(data_dir, f"{dataset_id}-{suffix}_error.json")
                
                # 在输出 JSON 中注入 error_reason 字段，便于直接查看失败原因
                error_reason = ""
                if not api_meta:
                    error_reason = "未找到对应的官网知识库 API"
                elif "error" in api_meta:
                    error_reason = str(api_meta.get("error", "")).split(" | ")[0] if api_meta.get("error") else ""
                if error_reason:
                    final_metadata["error_reason"] = error_reason
                    
                with open(error_file, "w", encoding="utf-8") as f:
                    json.dump(final_metadata, f, ensure_ascii=False, indent=2)
                
                if is_missing_registry:
                    logger.warning(f"⚠️ 未命中官网知识库 API，已保存至 {error_file}，并追加到 {MISSING_REGISTRY_FILE}")
                    missing_file = MISSING_REGISTRY_FILE
                    # 实时追加
                    missing_publisher = input_summary.get("official_website") or "Unknown"
                    missing_doi = input_summary.get("doi") or "NULL"
                    extracted_version = input_summary.get("version_name") or "Unknown"
                    
                    with global_file_lock:
                        # 确保如果写入多个缺失版本，原始文本行也能被追加（这里统一记录该行）
                        # 如果文件不存在，写入表头
                        if not os.path.exists(missing_file) and header_line:
                            with open(missing_file, "w", encoding="utf-8") as f:
                                f.write(header_line.strip() + "\t内部版本标识\t提取到的版本号\t缺失的官网名称(提取值)\t提取的DOI\n")
                        with open(missing_file, "a", encoding="utf-8") as f:
                            f.write(f"{line}\t[{suffix}]\t{extracted_version}\t{missing_publisher}\t{missing_doi}\n")
                else:
                    logger.warning(f"⚠️ 官网API请求报错，已保存至 {error_file}")
            
    except Exception as e:
        error_msg = f"系统异常: {str(e)}\n{traceback.format_exc()}"
        logger.error(f"❌ 运行崩溃: {error_msg}")
        error_file = os.path.join(data_dir, f"{dataset_id}_crash.json")
        with open(error_file, "w", encoding="utf-8") as f:
            json.dump({"error_traceback": error_msg}, f, ensure_ascii=False, indent=2)



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="批量处理数据集")
    parser.add_argument("--id", type=str, help="指定要单独测试的数据集ID", default=None)
    args = parser.parse_args()
    
    process_target_datasets(target_id=args.id)
