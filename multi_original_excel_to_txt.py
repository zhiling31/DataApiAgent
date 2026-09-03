import pandas as pd
import os

# 配置项：是否按“provider”列过滤 (每种值跨所有excel只取首行)
FILTER_BY_PROVIDER = True

# 配置项：是否只提取指定的provider（如果打开，则只取“provider”列中匹配以下列表的所有行）
FILTER_SPECIFIC_PROVIDER = False
TARGET_PROVIDER_LIST = ["EarthChem"]  # 在此处填入要过滤的特定 provider 列表

def process_multiple_excels(input_paths):
    all_dfs = []
    
    # 依次读取所有excel文件
    for path in input_paths:
        print(f"正在读取: {path}")
        df = pd.read_excel(path)
        df['_source_file'] = path
        df['_original_id'] = range(1, len(df) + 1)
        all_dfs.append(df)
        
    if not all_dfs:
        print("没有读取到任何数据！")
        return
        
    # 将所有excel的数据按顺序合并
    combined_df = pd.concat(all_dfs, ignore_index=True)
    
    # 过滤逻辑：只取指定的几个provider对应的行
    if FILTER_SPECIFIC_PROVIDER:
        if 'provider' in combined_df.columns:
            print(f"开启特定provider过滤，目标provider：{TARGET_PROVIDER_LIST}")
            combined_df = combined_df[combined_df['provider'].isin(TARGET_PROVIDER_LIST)]
        else:
            print("部分或全部Excel中没有 'provider' 这一列，无法提取指定的provider！")
            
    # 原有的配置项过滤逻辑 (跨所有excel，每种provider只取第一行)
    if FILTER_BY_PROVIDER:
        if 'provider' in combined_df.columns:
            print("检测到 'provider' 列，提取每种值的首行 (跨Excel文件)...")
            # 根据“provider”去重，每种值只取第一行，因为是按顺序 concat 的，所以保留的是最先出现的文件里的那条记录
            combined_df = combined_df.drop_duplicates(subset=['provider'], keep='first')
        else:
            print("部分或全部Excel中没有 'provider' 这一列！")
            
    # 重新生成一个整体的连续 ID
    combined_df.reset_index(drop=True, inplace=True)
    
    # 按照来源文件分别保存
    # 保证顺序使用 sort=False
    grouped = combined_df.groupby('_source_file', sort=False)
    
    saved_files = []
    
    for source_path, group_df in grouped:
        # 基于原本的 excel 文件名生成 txt 文件名
        base_name = os.path.splitext(source_path)[0]
        if FILTER_SPECIFIC_PROVIDER:
            out_path = f"{base_name}_specific.txt"
        elif FILTER_BY_PROVIDER:
            out_path = f"{base_name}_simple.txt"
        else:
            out_path = f"{base_name}.txt"
            
        with open(out_path, 'w', encoding='utf-8') as f:
            # 第一行写入表头
            f.write("ID\t数据集名称\t数据集描述\t数据集url\n")
            
            for index, row in group_df.iterrows():
                name = row.get('name', '')
                desc_en = row.get('desc_en', '')
                desc_zh = row.get('desc_zh', '')
                url = row.get('url', '')
                download_url = row.get('download_url', '')
                
                # 处理 NaN 值，替换为空字符串
                name = '' if pd.isna(name) else str(name).strip()
                desc_en = '' if pd.isna(desc_en) else str(desc_en).strip()
                desc_zh = '' if pd.isna(desc_zh) else str(desc_zh).strip()
                url = '' if pd.isna(url) else str(url).strip()
                download_url = '' if pd.isna(download_url) else str(download_url).strip()
                
                # ID按照在源数据集（对应的Excel）中的原始行号顺序
                id_val = row.get('_original_id', index + 1)
                col_name = f"{name}"
                col_desc = f"英文描述:{desc_en}，中文描述:{desc_zh}"
                col_url = f"落地页url:{url};下载页url:{download_url}"
                
                # 写入当前行的数据，用 tab 分隔
                f.write(f"{id_val}\t{col_name}\t{col_desc}\t{col_url}\n")
                
        saved_files.append(out_path)
        
    print(f"拆分处理完成，按源文件保存为:")
    for sf in saved_files:
        print(f"- {sf}")

if __name__ == '__main__':
    # 在此填入需要处理的多个Excel文件的绝对路径，排在前面的文件优先级更高（即会保留该文件的 provider 首行）
    input_files = [
        r'D:\地学\doi\数据清单\20260820-第二批数据集\Heat flow_master-31个.xlsx',
        r'D:\地学\doi\数据清单\20260820-第二批数据集\Gravity_master-27个.xlsx',
    ]
    
    # 过滤掉不存在的文件
    valid_input_files = [f for f in input_files if os.path.exists(f)]
    
    if not valid_input_files:
        print("未找到任何有效的输入文件！请检查路径。")
    else:
        print(f"即将处理 {len(valid_input_files)} 个文件...")
        process_multiple_excels(valid_input_files)
