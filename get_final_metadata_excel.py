import pandas as pd
import os

def main():
    # 文件路径
    file1_path = r"D:\地学\doi\数据清单\20260831-第三批数据集\Crustal ages_master-35个.csv"
    file2_path = r"D:\地学\doi\数据清单\20260831-第三批数据集\Crustal ages_master-35个\agent_result_stats.xlsx"
    
    # 提取原文件目录作为输出目录，生成新的文件名
    output_dir = os.path.dirname(file1_path)
    base_name = os.path.splitext(os.path.basename(file1_path))[0]
    output_path = os.path.join(output_dir, f"{base_name}_metadata.xlsx")

    print(f"正在读取文件: {os.path.basename(file1_path)}")
    try:
        if file1_path.lower().endswith('.csv'):
            try:
                df1 = pd.read_csv(file1_path, encoding='utf-8')
            except UnicodeDecodeError:
                df1 = pd.read_csv(file1_path, encoding='gbk')
        else:
            df1 = pd.read_excel(file1_path)
    except FileNotFoundError:
        print(f"错误: 找不到文件 {file1_path}")
        return

    # 1. 在首列加一列，即序号：1、2、3、4...
    print("正在第一列添加 '序号'...")
    # 如果已经有序号列则先删除，避免冲突
    if '序号' in df1.columns:
        df1 = df1.drop(columns=['序号'])
    df1.insert(0, '序号', range(1, len(df1) + 1))

    print(f"正在读取文件 (第二个 sheet): {os.path.basename(file2_path)}")
    try:
        # 2. 读取 agent_result_stats.xlsx 的第二个 sheet（索引为 1）
        df2 = pd.read_excel(file2_path, sheet_name=1)
    except FileNotFoundError:
        print(f"错误: 找不到文件 {file2_path}")
        return
    except IndexError:
        print("错误: 该文件似乎没有第二个 sheet。")
        return

    # 检查所需的列是否存在
    if 'datasetID' not in df2.columns or 'doi' not in df2.columns:
        print(f"错误: 在第二个 sheet 中找不到 'datasetID' 或 'doi' 列。包含的列有：{df2.columns.tolist()}")
        return

    # 提取需要的两列
    df2_subset = df2[['datasetID', 'doi']].copy()
    
    # 去重，防止 stats 中有重复的 datasetID 导致 df1 的行数膨胀
    df2_subset = df2_subset.drop_duplicates(subset=['datasetID'])

    import json
    
    def process_dataset_json(dataset_id, directory):
        # find json file starting with {dataset_id}- and ending with .json
        # also exact match {dataset_id}.json if any
        json_data = {}
        found = False
        dataset_id_str = str(dataset_id)
        if os.path.exists(directory):
            # 同时也检查子文件夹 data
            search_dirs = [directory, os.path.join(directory, "data")]
            for s_dir in search_dirs:
                if not os.path.exists(s_dir):
                    continue
                for filename in os.listdir(s_dir):
                    if filename.startswith(f"{dataset_id_str}-") and filename.endswith(".json"):
                        filepath = os.path.join(s_dir, filename)
                        try:
                            with open(filepath, 'r', encoding='utf-8') as f:
                                json_data = json.load(f)
                                found = True
                                break
                        except Exception as e:
                            print(f"读取 {filepath} 时出错: {e}")
                    elif filename == f"{dataset_id_str}.json":
                        filepath = os.path.join(s_dir, filename)
                        try:
                            with open(filepath, 'r', encoding='utf-8') as f:
                                json_data = json.load(f)
                                found = True
                                break
                        except Exception as e:
                            print(f"读取 {filepath} 时出错: {e}")
                if found:
                    break
                        
        
        # Default values
        official_api_exists = "否"
        metadata_collected = "否"
        
        if found and "metadata_sources" in json_data:
            metadata_sources = json_data.get("metadata_sources", {})
            official_api = metadata_sources.get("official_api", {})
            doi_org = metadata_sources.get("doi_org", {})
            datacite_crossref = metadata_sources.get("datacite_crossref", {})
            
            # 1. 是否存在官网原生API
            if isinstance(official_api, (dict, list)) and not official_api:
                official_api_exists = "否"
            elif isinstance(official_api, dict):
                if "error" in official_api:
                    official_api_exists = "否"
                elif "source" in official_api:
                    official_api_exists = "是"
                    
            # 2. 元数据是否已采集
            # doi_org不为空或datacite_crossref不为空（且不包含error）或official_api的值不为空并且不包含error的key并且包含source的key
            if doi_org and isinstance(doi_org, dict) and "error" not in doi_org:
                metadata_collected = "是"
            elif datacite_crossref and isinstance(datacite_crossref, dict) and "error" not in datacite_crossref:
                metadata_collected = "是"
            elif official_api and isinstance(official_api, dict) and "error" not in official_api and "source" in official_api:
                metadata_collected = "是"
                
        return pd.Series([official_api_exists, metadata_collected])

    print("正在从 JSON 文件中提取是否存在官网原生API和元数据是否已采集...")
    df2_dir = os.path.dirname(file2_path)
    df2_subset[['是否存在官网原生API', '元数据是否已采集']] = df2_subset['datasetID'].apply(
        lambda x: process_dataset_json(x, df2_dir)
    )

    print("正在根据序号一一对应合并列...")
    # 3. 将第二个 sheet 的对应列根据序号加到原表的后面
    # 采用 left merge 保留 df1 的所有行
    merged_df = pd.merge(df1, df2_subset, left_on='序号', right_on='datasetID', how='left')

    # 删除合并后带来的多余列 datasetID
    if 'datasetID' in merged_df.columns:
        merged_df = merged_df.drop(columns=['datasetID'])

    print(f"正在保存新的 Excel 文件至:\n{output_path}")
    # 4. 重新生成新的 excel
    merged_df.to_excel(output_path, index=False)
    
    print("执行完成！")

if __name__ == "__main__":
    main()
