import pandas as pd

# 配置项：是否按“是否有API”列过滤 (每种值取首行)
FILTER_BY_API = False

# 配置项：是否只提取指定的API（如果打开，则只取“是否有API”列中匹配以下列表的所有行）
FILTER_SPECIFIC_API = True
TARGET_API_LIST = ["是（open.canada.ca/CKAN元数据API；实体为FTP/直链）"]  # 在此处填入要过滤的特定 API 列表

def process_excel(input_path, output_path):
    # 读取excel文件
    df = pd.read_excel(input_path)
    
    # 新增过滤逻辑：只取指定的几个API对应的行
    if FILTER_SPECIFIC_API:
        if '是否有API' in df.columns:
            print(f"开启特定API过滤，目标API：{TARGET_API_LIST}")
            df = df[df['是否有API'].isin(TARGET_API_LIST)]
        else:
            print("Excel中没有 '是否有API' 这一列，无法提取指定的API！")
            
    # 原有的配置项过滤逻辑
    if FILTER_BY_API:
        if '是否有API' in df.columns:
            print("检测到 '是否有API' 列，提取每种值的首行...")
            # 根据“是否有API”去重，每种值只取第一行
            df = df.drop_duplicates(subset=['是否有API'], keep='first')
        else:
            print("Excel中没有 '是否有API' 这一列！")
    
    with open(output_path, 'w', encoding='utf-8') as f:
        # 第一行写入表头
        f.write("ID\t数据集名称\t数据集描述\t数据集url\n")
        
        for index, row in df.iterrows():
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
            
            # 拼接列的内容
            id_val = index + 1
            col_name = f"{name}"
            col_desc = f"英文描述:{desc_en}，中文描述:{desc_zh}"
            col_url = f"落地页url:{url};下载页url:{download_url}"
            
            # 写入当前行的数据，用 tab 分隔
            f.write(f"{id_val}\t{col_name}\t{col_desc}\t{col_url}\n")

if __name__ == '__main__':
    input_file = r'D:\地学\doi\数据清单\geophysics-Electrical and Electromagnetic Exploration Methods.xlsx'
    
    import os
    
    # 根据配置项动态生成输出文件名
    if FILTER_SPECIFIC_API:
        base_name = input_file.replace('.xlsx', '_specific')
        counter = 1
        output_file = f"{base_name}{counter}.txt"
        while os.path.exists(output_file):
            counter += 1
            output_file = f"{base_name}{counter}.txt"
    elif FILTER_BY_API:
        output_file = input_file.replace('.xlsx', '_simple.txt')
    else:
        output_file = input_file.replace('.xlsx', '.txt')
    
    print(f"正在处理: {input_file}")
    process_excel(input_file, output_file)
    print(f"处理完成，结果已保存至: {output_file}")
