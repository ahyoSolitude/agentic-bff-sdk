# 结果聚合与响应生成

> 对应源码：`agentic_bff_sdk/aggregator.py`、`agentic_bff_sdk/synthesizer.py`、`agentic_bff_sdk/card_generator.py`

这三个组件构成 Agentic BFF 下层，负责将多个领域的执行结果转化为用户可理解的响应。

---

## FanInAggregator — 结果聚合

### 设计思路

Async Fan-In 模式：多个并发步骤的结果汇聚到一个点。Aggregator 判断结果的完整性——是全部到齐还是部分缺失。

### 核心接口

```python
class FanInAggregator:
    async def aggregate(self, step_results, expected_steps, wait_timeout_seconds=60.0)
        -> AggregatedResult
    async def aggregate_with_timeout(self, result_futures, expected_steps, wait_timeout_seconds)
        -> AggregatedResult
```

### 完整性判断

| 条件 | is_partial | missing_steps |
|------|-----------|---------------|
| 所有 expected_steps 都有结果 | False | [] |
| 部分 expected_steps 缺失 | True | 缺失的 step_id 列表 |

注意：**FAILED 和 TIMEOUT 的步骤仍算"有结果"**，不计入 missing。只有完全没有 StepResult 的步骤才算 missing。

### 扩展方向

- **加权聚合**：根据步骤重要性加权
- **流式聚合**：结果到达一个推送一个，不等全部完成

---

## Synthesizer — 综合决策

### 设计思路

Synthesizer 将聚合后的多领域结果通过 LLM 生成一段连贯的自然语言响应。核心创新是**交叉 LLM 回路**：如果生成的响应质量不达标，自动重试并附带上次响应作为改进参考。

### 核心接口

```python
class Synthesizer(ABC):
    async def synthesize(self, aggregated, session_state, quality_threshold=0.7)
        -> SynthesisResult
```

### DefaultSynthesizer 实现要点

**质量评分**（0.0 ~ 1.0）基于：
- 响应是否非空（+0.3）
- 响应长度（+0.1 ~ +0.2）
- 是否覆盖已完成步骤（+0.1 ~ +0.3）
- 是否整合规则引擎数据（+0.1）
- 部分结果惩罚（-0.1）

**交叉 LLM 回路**：
```
生成响应 → 评分
  → 达标？返回
  → 不达标？构建重试 prompt（含上次响应 + 评分）→ 重新生成
  → 最多重试 max_cross_llm_loops 次
```

**规则引擎整合**：自动从 StepResult 中提取 `rule_engine_output` 字段，注入到 prompt 和 `structured_data` 中。

**可注入 synthesis_fn**：`DefaultSynthesizer(synthesis_fn=my_fn)` 可替代 LLM 调用，方便测试。

### 扩展方向

- **多模型评分**：用独立的评分模型替代规则评分
- **RAG 增强**：在 prompt 中注入检索到的知识库内容
- **流式输出**：支持 SSE 流式返回综合结果

---

## CardGenerator — 富媒体卡片

### 设计思路

CardGenerator 将 SynthesisResult 转换为前端可直接渲染的富媒体卡片。核心能力是**渠道适配**：根据目标渠道支持的卡片类型自动过滤。

### 核心接口

```python
class CardGenerator(ABC):
    async def generate(self, synthesis, channel_capabilities) -> CardOutput
```

### 卡片类型

| CardType | 触发条件 | 内容 |
|----------|---------|------|
| TEXT | 始终生成 | 文本响应 |
| TABLE | structured_data 非空 | 结构化数据表格 |
| CHART | structured_data 含 chart_data | 图表数据 |
| ACTION_BUTTON | 有 confirmation_actions 且不需确认 | 操作按钮 |
| CONFIRMATION | requires_confirmation=True | 确认交互卡片（含确认/取消按钮） |

### 渠道适配

```python
# Web 渠道：支持所有类型
output = await gen.generate(synthesis, {"supported_card_types": list(CardType)})

# SMS 渠道：仅支持文本
output = await gen.generate(synthesis, {"supported_card_types": [CardType.TEXT]})

# 未指定：不过滤，返回所有卡片
output = await gen.generate(synthesis, {})
```

### JSON Schema 验证

```python
from agentic_bff_sdk.card_generator import validate_card_output_schema
is_valid = validate_card_output_schema(card_output)  # True/False
```

### 扩展方向

- **自定义卡片类型**：扩展 CardType 枚举，添加 VIDEO、AUDIO 等
- **模板引擎**：用 Jinja2 模板渲染卡片内容
- **Markdown 输出**：为终端/CLI 渠道生成 Markdown 格式
