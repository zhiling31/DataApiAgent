import re

with open('integrated_dataset_agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('v_ctx = target.get("context_info", "")', 'v_ctx = target.get("context_info", "")\n    \n    original_input = getattr(state["messages"][1], "content", "") if len(state["messages"]) > 1 else "Unknown Dataset"')

content = content.replace('【目标版本】：{v_name}', '【所属数据集上下文 / 原始请求】：\n{original_input}\n\n【当前专注的特定版本】：{v_name}')

content = content.replace('请利用工具搜索这个版本。只关注它', '请利用工具搜索当前深挖的这个版本。结合【所属数据集上下文】和【当前专注的特定版本】，构造准确的搜索关键词（例如：数据集名称 + 版本名称 + DOI）。\n只关注它')

with open('integrated_dataset_agent.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Patch applied successfully.")
