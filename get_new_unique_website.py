import os
import json

def main():
    # --- 配置项 ---
    ENABLE_MULTI_DIR_MODE = True  # 如果开启，则使用下方的列表配置；否则使用单目录配置
    
    # 单目录配置（当 ENABLE_MULTI_DIR_MODE = False 时使用）
    single_json_dir = r"D:\地学\doi\数据清单\20260831-第三批数据集\Crustal ages_master-35个\data"
    single_txt_file = r"D:\地学\doi\数据清单\20260831-第三批数据集\Crustal ages_master-35个.txt"
    
    # 多目录配置（当 ENABLE_MULTI_DIR_MODE = True 时使用）
    # json_dirs 和 txt_files 必须一一对应，去重优先级由 json_dirs 里的顺序决定（前面的优先级高）
    multi_json_dirs = [
        r"D:\地学\doi\数据清单\20260831-第三批数据集\Faults_master-26个\data",
        r"D:\地学\doi\数据清单\20260831-第三批数据集\Crustal ages_master-35个\data",
    ]
    multi_txt_files = [
        r"D:\地学\doi\数据清单\20260831-第三批数据集\Faults_master-26个.txt",
        r"D:\地学\doi\数据清单\20260831-第三批数据集\Crustal ages_master-35个.txt",
    ]
    # ------------

    if ENABLE_MULTI_DIR_MODE:
        json_dirs = multi_json_dirs
        txt_files = multi_txt_files
        if len(json_dirs) != len(txt_files):
            print("错误: json_dirs 和 txt_files 列表长度必须一致（一一对应）。")
            return
    else:
        json_dirs = [single_json_dir]
        txt_files = [single_txt_file]
        
    for d, f in zip(json_dirs, txt_files):
        if not os.path.exists(d):
            print(f"错误: 目录 {d} 不存在。")
            return
        if not os.path.exists(f):
            print(f"错误: txt文件 {f} 不存在。")
            return
            
    unique_websites = {} # mapping: website -> (file_index, dataset_id)
    
    # 1. 按照 json_dirs 顺序遍历所有 _error.json 文件
    # 因为按顺序遍历，先找到的 website 会先加入 unique_websites，
    # 后面的相同 website 就会被忽略，自然实现了“前面的 json_dir 优先级高”的要求。
    for file_index, json_dir in enumerate(json_dirs):
        for filename in os.listdir(json_dir):
            if filename.endswith("_error.json"):
                filepath = os.path.join(json_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        
                    # 获取 input_summary.official_websites
                    input_summary = data.get("input_summary", {})
                    websites = input_summary.get("official_websites", [])
                    
                    if not isinstance(websites, list):
                        continue
                        
                    # 文件名按照-分隔取[0]作为数据集id
                    dataset_id = filename.split('-')[0]
                    
                    # 2. 去重并保留第一个出现的数据集ID
                    for website in websites:
                        if website not in unique_websites:
                            unique_websites[website] = (file_index, dataset_id)
                            
                except Exception as e:
                    print(f"处理 {filepath} 时出错: {e}")
                    
    print(f"共找到 {len(unique_websites)} 个唯一的 official_website。")
    
    # 分类 target_dataset_ids：按 file_index 归类
    # target_dataset_ids_by_index[file_index] = set_of_dataset_ids
    target_dataset_ids_by_index = {i: set() for i in range(len(json_dirs))}
    for website, (file_index, dataset_id) in unique_websites.items():
        target_dataset_ids_by_index[file_index].add(dataset_id)
        
    # 分类 unique_websites_by_index: 用于生成对应的 new_official_websites 文件
    # unique_websites_by_index[file_index] = list_of_tuples(dataset_id, website)
    unique_websites_by_index = {i: [] for i in range(len(json_dirs))}
    for website, (file_index, dataset_id) in unique_websites.items():
        unique_websites_by_index[file_index].append((dataset_id, website))
    
    # 3. 为每个 txt 文件执行过滤并输出
    for file_index, txt_file in enumerate(txt_files):
        target_dataset_ids = target_dataset_ids_by_index[file_index]
        
        base_name, ext = os.path.splitext(txt_file)
        output_txt_file = f"{base_name}_unique_website{ext}"
        
        match_count = 0
        with open(txt_file, 'r', encoding='utf-8') as f_in, open(output_txt_file, 'w', encoding='utf-8') as f_out:
            # 写入要求的表头
            f_out.write("ID\t数据集名称\t数据集描述\t数据集url\n")
            
            for line in f_in:
                line_strip = line.strip()
                if not line_strip:
                    continue
                    
                # 提取第一列 (支持制表符、逗号或空格分隔的txt格式)
                if '\t' in line_strip:
                    first_col = line_strip.split('\t')[0]
                elif ',' in line_strip:
                    first_col = line_strip.split(',')[0]
                else:
                    first_col = line_strip.split()[0]
                    
                # 如果该行的第一列(数据集ID)在我们收集的ID中，则写入新文件
                if first_col in target_dataset_ids:
                    f_out.write(line)
                    match_count += 1
                    
        print(f"[{txt_file}] 处理完成！新的文件已保存至: {output_txt_file}")
        print(f"共向新txt中写入了 {match_count} 行。")
        
        # 4. 写入 official_websites 及其对应的数据集ID
        website_output_file = f"{base_name}_new_official_websites{ext}"
        with open(website_output_file, 'w', encoding='utf-8') as f_out:
            for ds_id, website in unique_websites_by_index[file_index]:
                f_out.write(f"{ds_id}\t{website}\n")
                
        print(f"[{txt_file}] 官方网站及其对应的数据集ID已保存至: {website_output_file}\n")

if __name__ == "__main__":
    main()
