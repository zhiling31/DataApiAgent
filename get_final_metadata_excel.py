import pandas as pd
import os

def main():
    # 文件路径
    file1_path = r"D:\地学\doi\数据清单\geophysics-Electrical and Electromagnetic Exploration Methods.xlsx"
    file2_path = r"D:\地学\doi\数据清单\geophysics-Electrical and Electromagnetic Exploration Methods\agent_result_stats.xlsx"
    
    # 提取原文件目录作为输出目录，生成新的文件名
    output_dir = os.path.dirname(file1_path)
    output_path = os.path.join(output_dir, "geophysics-Electrical and Electromagnetic Exploration Methods_with_doi.xlsx")

    print(f"正在读取文件: {os.path.basename(file1_path)}")
    try:
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
    df2_subset = df2[['datasetID', 'doi']]
    
    # 去重，防止 stats 中有重复的 datasetID 导致 df1 的行数膨胀
    df2_subset = df2_subset.drop_duplicates(subset=['datasetID'])

    print("正在根据序号一一对应合并 'doi' 列...")
    # 3. 将第二个 sheet 的 doi 根据序号加到原表的后面
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
