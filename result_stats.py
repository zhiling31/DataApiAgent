import os
import json
import pandas as pd
import re

def clean_text(text):
    if not text:
        return ""
    cleaned = re.sub(r'[,，:：\-–—]', ' ', str(text))
    return re.sub(r'\s+', ' ', cleaned).strip()

# 20260831-第三批数据集\Faults_master-26个
target_dir = r"D:\地学\doi\数据清单\20260831-第三批数据集\Crustal ages_master-35个\data"
output_file = r"D:\地学\doi\数据清单\20260831-第三批数据集\Crustal ages_master-35个\agent_result_stats.xlsx"

total_count = 0
success_count = 0
error_count = 0
doi_found_count = 0
doi_not_found_count = 0

records = []

for filename in os.listdir(target_dir):
    if not filename.endswith(".json"):
        continue
    
    total_count += 1
    filepath = os.path.join(target_dir, filename)
    
    is_error = filename.endswith("error.json")
    if is_error:
        error_count += 1
    else:
        success_count += 1
        
    with open(filepath, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except Exception as e:
            print(f"Error reading {filename}: {e}")
            continue
            
    input_summary = data.get("input_summary", {})
    original_input = data.get("original_input", {})
    error_reason = data.get("error_reason", "")
    
    # Check for DOI
    doi = input_summary.get("doi")
    if not doi:
        doi = original_input.get("doi")
        
    if doi and str(doi).strip():
        doi_found_count += 1
    else:
        doi_not_found_count += 1
        
    api_matches = {}
    
    has_doi = bool(doi and str(doi).strip())
    metadata_sources = data.get("metadata_sources", {})
    
    doi_org_data = metadata_sources.get("doi_org", {}).get("data", {})
    title = doi_org_data.get("title", "")
    abstract = doi_org_data.get("abstract", "")
    original_dataset_name = original_input.get("dataset_name", "")

    if has_doi:
        if original_dataset_name and title:
            name_clean = clean_text(str(original_dataset_name).strip())
            title_clean = clean_text(str(title).strip())
            try:
                pattern = re.escape(name_clean).replace(r'\ ', r'\s+')
                match_obj = re.search(pattern, title_clean, re.IGNORECASE)
                api_matches["name是否在doi_title里"] = bool(match_obj)
                if match_obj:
                    start = max(0, match_obj.start() - 10)
                    end = min(len(title_clean), match_obj.end() + 10)
                    api_matches["name在doi_title里的匹配上下文"] = title_clean[start:end]
            except Exception:
                api_matches["name是否在doi_title里"] = False
        else:
            api_matches["name是否在doi_title里"] = None

    if not is_error:
        official_api = metadata_sources.get("official_api", "")
        if official_api:
            if isinstance(official_api, dict):
                api_list = [official_api]
            elif isinstance(official_api, list):
                api_list = official_api
            else:
                api_list = [official_api]
                
            for i, api_item in enumerate(api_list):
                if isinstance(api_item, (dict, list)):
                    api_str = json.dumps(api_item, ensure_ascii=False)
                else:
                    api_str = str(api_item)
                # Clean api_str using the new function
                clean_api_str = clean_text(api_str)
                
                if has_doi:
                    t_match = None
                    a_match = None
                    
                    if title:
                        title_clean = clean_text(str(title).strip())
                        try:
                            pattern = re.escape(title_clean).replace(r'\ ', r'\s+')
                            match_obj = re.search(pattern, clean_api_str, re.IGNORECASE)
                            t_match = bool(match_obj)
                            if match_obj:
                                start = max(0, match_obj.start() - 10)
                                end = min(len(clean_api_str), match_obj.end() + 10)
                                api_matches[f"api{i+1}title匹配上下文"] = clean_api_str[start:end]
                        except Exception:
                            t_match = False
                            
                    if abstract:
                        abstract_clean = clean_text(str(abstract).strip())
                        try:
                            pattern = re.escape(abstract_clean).replace(r'\ ', r'\s+')
                            a_match = bool(re.search(pattern, clean_api_str, re.IGNORECASE))
                        except Exception:
                            a_match = False
                            
                    api_matches[f"api{i+1}title是否正确"] = t_match
                    api_matches[f"api{i+1}abstract是否正确"] = a_match
                else:
                    n_match = None
                    if original_dataset_name:
                        name_clean = clean_text(str(original_dataset_name).strip())
                        try:
                            pattern = re.escape(name_clean).replace(r'\ ', r'\s+')
                            match_obj = re.search(pattern, clean_api_str, re.IGNORECASE)
                            n_match = bool(match_obj)
                            if match_obj:
                                start = max(0, match_obj.start() - 10)
                                end = min(len(clean_api_str), match_obj.end() + 10)
                                api_matches[f"api{i+1}name匹配上下文"] = clean_api_str[start:end]
                        except Exception:
                            n_match = False
                    api_matches[f"api{i+1}name是否正确"] = n_match
        
    # Flatten fields explicitly
    target_api = input_summary.get("target_api_name")
    if isinstance(target_api, list):
        target_api = ", ".join([str(x) for x in target_api])

    record = {
        "datasetID": filename.split('-')[0],
        "original_dataset_name": original_input.get("dataset_name"),
        "original_url": original_input.get("url"),
        "doi": input_summary.get("doi"),
        "dataset_url": input_summary.get("dataset_url"),
        "doi_landing_page": input_summary.get("doi_landing_page"),
        "dataset_name": input_summary.get("dataset_name"),
        "version": input_summary.get("version_name"),
        "official_website": input_summary.get("official_website"),
        "target_api": target_api,
        "error_reason": error_reason,
    }
    record.update(api_matches)
    
    records.append(record)

stats = [{
    "总数": total_count,
    "成功数": success_count,
    "失败数": error_count,
    "能找到DOI的文件数": doi_found_count,
    "找不到DOI的文件数": doi_not_found_count
}]

df_stats = pd.DataFrame(stats)
df_records = pd.DataFrame(records)

with pd.ExcelWriter(output_file) as writer:
    df_stats.to_excel(writer, sheet_name='统计信息', index=False)
    df_records.to_excel(writer, sheet_name='详细数据', index=False)
    
print(f"Successfully created {output_file}")
