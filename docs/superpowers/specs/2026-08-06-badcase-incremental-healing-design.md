# Badcase 增量自愈逻辑设计方案

## 概述
本设计方案旨在为 `fetch_publisher_api.py` 引入一套优化的增量自修复（自愈）流程。我们的目标是让系统能够读取特定的 badcase（以 JSON 文件的形式保存在指定文件夹中），并利用更聚焦的约束条件以及明确的错误上下文重新运行 API 提取与大模型分析流程，从而修复之前的提取失败问题。

## 1. 命令行接口调整
- **新参数**：`--heal-dir` (类型: str)
- **行为逻辑**：如果提供了 `--heal-dir` 参数，脚本将会遍历该指定的文件夹，寻找所有的 `.json` 文件。这会替代默认的 `pd.read_csv(INPUT_DATASET_FILE)` 读取逻辑。原有通过 `--heal-file` 读取 CSV 的功能予以保留，以兼容旧版。

## 2. 解析与 ID 映射
- 对于 `--heal-dir` 文件夹下的每个 `.json` 文件：
  - 读取 JSON 数组，从中提取每个对象的 `input_summary` 字段。
  - **数据集 ID (`ds_id`)**：将去掉 `.json` 后缀的文件名直接作为 `ds_id`，从而无缝衔接现有系统中的断点续传缓存和进度追踪逻辑。
  - **提取的字段**：
    - `doi`
    - `dataset_url`
    - `doi_landing_page`
    - `dataset_name`
    - `target_api_name` (字符串列表)
    - `error_reason` (字符串)

## 3. 候选平台限制 (target_api_name)
- 在构建 `publisher_samples` 列表时，保留读取到的 `target_api_name`。
- 在 `identify_candidate_platforms`（识别候选平台）阶段，如果样本中包含了 `target_api_name`，脚本将会进行严格过滤：仅将名称（或归一化后的名称）出现在 `target_api_name` 中的平台作为候选平台。这可以确保大模型不会浪费 Token 去探索毫无关联的平台。

## 4. 注入错误上下文 (error_reason)
- 提取到的 `error_reason` 将被加入到样本字典中，并传递给 `CURRENT_DATASET_CONTEXT` 和 `initial_state`。
- 在 `integrated_dataset_agent.py`（定义了 Agent/LLM 提示词的地方）中，如果检测到状态（state）中存在 `error_reason`，则会在向大模型发送 Prompt 时触发如下追加提示：
  > "【历史 Badcase 修复任务】之前尝试提取该数据集信息时发生了如下错误/失败原因：{error_reason}。请特别留意并修改你的提取策略，以避免重蹈覆辙。"
- 这样做能给大模型提供明确的历史试错反馈，指导它生成更加健壮和针对性的 API 抓取策略。
