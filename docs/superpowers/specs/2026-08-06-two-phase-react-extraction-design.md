# 设计规范：用于数据集提取的双阶段 ReAct 架构 (Two-Phase ReAct)

## 1. 问题背景
当前的数据集提取流程采用的是单一的“先全面搜索，再统一提取”的方法。其中，`research_and_verify_node` (检索节点) 会进行一次常规的网络搜索，但它并不知道自己的最终目的是要找出所有历史版本。这导致它经常“浅尝辄止”，过早停止搜索。随后进入 `extract_node` (提取节点) 时，由于上下文信息不完整，且提取任务的指令过于宽泛（“一次性提取所有版本的所有细节”），大模型往往会遗漏版本或丢失 DOI。对于像 NTAD 这种包含众多子数据集的集合型项目，这个问题尤为严重。

## 2. 解决方案：双阶段 ReAct 图架构
我们将重构 LangGraph 架构，将整个提取流程彻底拆分为两个独立的检索循环：
1. **阶段一：版本发现 (Version Discovery)**：大模型专注于在全网广泛搜索，目的根据用户的输入判断：如果用户明确指定了某个版本，则只找该特定版本；否则，列出该数据集所有存在的主版本/标准版本/历史主快照。**注意：不需要列出子数据集或衍生图层，只关注数据集的主体版本迭代。**
2. **阶段二：深度挖掘 (Deep Dive Extraction)**：针对阶段一找到的每一个主版本，大模型将被分配一个独立的搜索环境，专门且只为了找出该特定版本的 DOI 和元数据。

## 3. 状态模型 (State Schema) 更新
我们需要在 `integrated_dataset_agent.py` 中更新 `AgentState`，以支持这种嵌套循环的机制。
```python
class AgentState(TypedDict):
    # 阶段一 (发现阶段) 的状态
    messages: Annotated[List, lambda x, y: x + y] # 用于第一阶段版本发现的消息历史
    discovered_versions: List[dict]               # 由 discovery_extractor 填充的版本列表

    # 阶段二 (深度挖掘阶段) 的状态
    current_version_idx: int                      # 指向当前正在挖掘的版本的索引
    version_messages: List                        # 专属于当前挖掘版本的独立消息历史 (移除 append 归约器，方便每次清空)

    # 最终输出状态
    extracted_datasets: List[dict]                # 最终提取出的 DatasetInfo 列表
    final_results: List[dict]                     # 经过 API 验证后的最终结果
```

## 4. 图节点与边 (Graph Nodes & Edges) 设计
LangGraph 工作流将被重构为以下结构：

### 4.1 阶段一：版本发现 (Phase 1: Discovery)
- **`discovery_researcher`**: ReAct 检索节点。使用全局 `messages`。其 Prompt 明确指示大模型：“如果用户指定了版本，只找该版本；否则，寻找数据集的所有历史主干版本/主快照。严禁寻找细分的子数据集！”
- **`discovery_tools`**: 执行搜索工具的节点。
- **流程边**: `discovery_researcher` 与 `discovery_tools` 循环互动。搜集完毕后，跳转至 `discovery_extractor`。
- **`discovery_extractor`**: 调用大模型，将 `messages` 解析为 JSON 格式的 `DiscoveredVersionList`。输出的列表中不仅包含 `version_name` 和 `hint_url`，还会增加一个 `context_info` 字段用于传递给下一阶段的重要背景信息。将结果存入 `state["discovered_versions"]`，初始化 `current_version_idx = 0`，并清空 `version_messages`。随后跳转至 `deep_dive_router`。

### 4.2 阶段二：深度挖掘循环 (Phase 2: Deep Dive Loop)
- **`deep_dive_router`** (条件路由节点): 
  - 如果 `current_version_idx < len(discovered_versions)`，说明还有版本没挖完，跳转至 `version_researcher`。
  - 否则，所有版本挖掘完毕，跳转至原有的 `fetch_metadata_node` (注意：此节点本身不进行全网搜索，而是利用前两个阶段提取出的结构化参数，精准调用 Zenodo/ROSAP 等官方知识库的结构化 API 来获取标准元数据)。
- **`version_researcher`**: 针对单一版本的 ReAct 检索节点。使用独立的 `version_messages`。会在 Prompt 中动态注入当前目标版本的名称和线索，指示大模型：“像狙击手一样，为你当前唯一的目标寻找 DOI 和元数据。”
- **`version_tools`**: 执行挖掘工具的节点。
- **流程边**: `version_researcher` 与 `version_tools` 循环互动。搜集完毕后，跳转至 `version_extractor`。
- **`version_extractor`**: 调用大模型，根据专属的 `version_messages` 提取出单一的 `DatasetInfo` JSON 数据。将其追加到 `extracted_datasets` 数组中。然后 `current_version_idx` 加 1，并**彻底清空** `version_messages`。最后回到 `deep_dive_router` 继续循环。

## 5. Pydantic 数据模型调整
- 修改 `DiscoveredVersion` 模型，加入更多辅助信息：
  ```python
  class DiscoveredVersion(BaseModel):
      version_name: str
      hint_url: Optional[str]
      context_info: Optional[str] = Field(description="该版本在检索过程中发现的任何有用上下文或识别特征")
  ```
- 保留现有的 `DatasetInfo` 和 `DatasetExtractionList`，但 `version_extractor` 每次只需要直接输出一个 `DatasetInfo` 对象。

## 6. 自我审查与注意事项
- **清除 `version_messages` 的技术难点**：在 LangGraph 中，如果 `version_messages` 使用了 `Annotated[List, lambda x, y: x + y]` 的追加器 (reducer)，直接清空它会比较麻烦（可能需要发送特殊的 `RemoveMessage` 指令）。
- **优化方案**：为了实现彻底的上下文隔离且便于操作，我们将 `version_messages` 的类型直接声明为普通的 `List`（不带 append 归约器）。这样每次进入新循环时，可以直接覆写该状态，确保上一个版本的搜索记录绝不会污染下一个版本。

## 7. 实施迁移步骤
1. 删除旧的、会导致大模型分心的 `research_and_verify_node`, `should_continue` 和 `extract_node`。
2. 编写全新的节点代码：`discovery_researcher`, `discovery_extractor`, `version_researcher`, `version_extractor`。
3. 更新 `build_agent()` 函数，将全新的双阶段循环流注册进 LangGraph 中。
