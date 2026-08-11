import pandas as pd
import requests
import json
import time
import os

def fetch_with_retry(url, headers=None, max_retries=3):
    """通用的带智能重试的请求封装"""
    for attempt in range(max_retries):
        try:
            res = requests.get(url, headers=headers, timeout=15)
            
            # 【绝不重试的错误】：如果是 404 (没找到) 或 400 (请求错误)
            # 说明这串 DOI 在这个平台根本不存在，重试 100 次也没用，直接返回。
            if res.status_code in [404, 400]:
                return res, None
                
            # 如果是 5xx 服务端错误 (如 500, 502, 503)，说明是对方服务器临时卡死，触发重试
            if res.status_code >= 500:
                raise requests.exceptions.HTTPError(f"服务端临时故障 HTTP {res.status_code}")
                
            return res, None
            
        except requests.exceptions.RequestException as e:
            # 捕获所有网络底层的闪断、超时、SSL 挂断 (包括之前的 SSLEOFError)
            if attempt < max_retries - 1:
                sleep_time = (attempt + 1) * 3 # 第一次休息3秒，第二次休息6秒，避免激怒防火墙
                print(f"      [警告] 网络闪断或被拦截，等待 {sleep_time} 秒后启动第 {attempt+1} 次重拨抢救...")
                time.sleep(sleep_time)
            else:
                return None, f"尝试了 {max_retries} 次依然失败，报错: {type(e).__name__}"

def fetch_from_datacite(doi):
    res, err = fetch_with_retry(f'https://api.datacite.org/dois/{doi}')
    if err: return None, err
    if res.status_code == 200:
        return res.json().get('data', {}), None
    return None, f"DataCite 返回 HTTP {res.status_code}"

def fetch_from_crossref(doi):
    headers = {"User-Agent": "DataLibrarianAgent/2.0 (mailto:admin@example.com)"}
    res, err = fetch_with_retry(f'https://api.crossref.org/works/{doi}', headers=headers)
    if err: return None, err
    if res.status_code == 200:
        return res.json().get('message', {}), None
    return None, f"Crossref 返回 HTTP {res.status_code}"

def fetch_all_metadata():
    excel_path = 'final_merged_dois.xlsx'
    success_file = 'meta_results/full_metadata_new.json'
    error_file = 'meta_results/error.json'
    
    print(f"正在读取 {excel_path}...")
    try:
        df = pd.read_excel(excel_path)
    except Exception as e:
        print(f"读取 Excel 文件失败: {e}")
        return

    # ==========================
    # 断点续传逻辑 (加载已成功的 DOI)
    # ==========================
    success_data = []
    successful_dois = set()
    
    if os.path.exists(success_file):
        try:
            with open(success_file, 'r', encoding='utf-8') as f:
                success_data = json.load(f)
                for item in success_data:
                    if 'doi' in item and 'datanet_id' in item:
                        # 用元组存储组合键，全部转为字符串以防类型不匹配
                        successful_dois.add((str(item['datanet_id']), str(item['doi'])))
            print(f"\n✅ 【断点续传激活】：检测到本地已有 {len(successful_dois)} 个提取成功的 DOI，本次将直接跳过它们！\n")
        except Exception as e:
            print(f"⚠️ 无法读取 {success_file}，将重新开始...")

    error_data = []
    total_processed_this_run = 0

    print('开始根据 DOI 类型进行精准 API 分发提取...')

    def clean_id(val):
        val_str = str(val)
        return val_str[:-2] if val_str.endswith('.0') else val_str

    for index, row in df.iterrows():
        datanet_id = clean_id(row.get('datanet_id', ''))
        ddename = str(row.get('ddename', ''))
        
        def process_dois(doi_str, known_type):
            nonlocal total_processed_this_run
            if pd.isna(doi_str) or not str(doi_str).strip() or str(doi_str) == 'nan':
                return
                
            dois_to_process = [d.strip() for d in str(doi_str).split(';')]
            for d in dois_to_process:
                if not d: continue
                
                # 【断点续传核心】：如果这个 DOI 已经在之前的 JSON 里了，直接飞过
                if (str(datanet_id), d) in successful_dois:
                    print(f"⏭️  跳过已成功记录 (ID: {datanet_id} | DOI: {d})")
                    continue
                
                total_processed_this_run += 1
                print(f"🔄 正在处理第 {total_processed_this_run} 条新 DOI: {d} ({known_type})...")
                
                metadata = None
                error_msg = None
                source_api = None
                
                try:
                    if known_type == 'data_repositories':
                        # 已知是数据本体：优先尝试 DataCite，如果失败（如 404）则尝试 Crossref 兜底
                        metadata, error_msg = fetch_from_datacite(d)
                        source_api = 'DataCite'
                        if not metadata:
                            print(f"      [分流] DataCite 失败 ({error_msg})，正前往 Crossref 兜底查档...")
                            metadata, error_msg2 = fetch_from_crossref(d)
                            source_api = 'Crossref' if metadata else 'Both Failed'
                            if not metadata:
                                error_msg = f"{error_msg} | {error_msg2}"
                        
                    elif known_type == 'benchmark_papers':
                        metadata, error_msg = fetch_from_crossref(d)
                        source_api = 'Crossref'
                        
                    else:
                        metadata, error_msg = fetch_from_datacite(d)
                        source_api = 'DataCite'
                        if not metadata:
                            metadata, error_msg2 = fetch_from_crossref(d)
                            source_api = 'Crossref' if metadata else 'Both Failed'
                            if not metadata:
                                error_msg = f"{error_msg} | {error_msg2}"
                                
                    if metadata:
                        success_data.append({
                            'datanet_id': datanet_id,
                            'ddename': ddename,
                            'doi_type': known_type,
                            'source_api': source_api,
                            'doi': d,
                            'metadata': metadata
                        })
                        # 加入成功集合，防止后续重复处理
                        successful_dois.add((str(datanet_id), d))
                        
                        # 每成功一条就实时存盘一次，防止程序意外中断白跑
                        with open(success_file, 'w', encoding='utf-8') as f:
                            json.dump(success_data, f, ensure_ascii=False, indent=2)
                    else:
                        error_data.append({
                            'datanet_id': datanet_id,
                            'ddename': ddename,
                            'doi_type': known_type,
                            'doi': d,
                            'error': error_msg
                        })
                except Exception as e:
                    error_data.append({
                        'datanet_id': datanet_id,
                        'ddename': ddename,
                        'doi_type': known_type,
                        'doi': d,
                        'error': f'未知代码异常: {str(e)}'
                    })
                
                # 常规休眠，避免限流
                time.sleep(0.3)

        process_dois(row.get('data_repositories_doi'), 'data_repositories')
        process_dois(row.get('benchmark_papers_doi'), 'benchmark_papers')

    # 最后再保存一下完整的 error.json
    with open(error_file, 'w', encoding='utf-8') as f:
        json.dump(error_data, f, ensure_ascii=False, indent=2)

    # ==========================
    # 打印最终统计结论
    # ==========================
    data_success = sum(1 for item in success_data if item['doi_type'] == 'data_repositories')
    lit_success = sum(1 for item in success_data if item['doi_type'] == 'benchmark_papers')

    print("-" * 50)
    print("📊 增量抓取任务总结报告")
    print("-" * 50)
    print(f"🔍 本次实际发起网络请求的新 DOI: {total_processed_this_run} 条")
    print(f"✅ 本地总计成功收集档案: {len(success_data)} 条 (已保存至 {success_file})")
    print(f"   ➤ 包含 数据本体 (Data): {data_success} 条")
    print(f"   ➤ 包含 标杆论文 (Literature): {lit_success} 条")
    print(f"❌ 遗留的顽固失败记录: {len(error_data)} 条 (已隔离至 {error_file})")
    print("-" * 50)

if __name__ == '__main__':
    fetch_all_metadata()
