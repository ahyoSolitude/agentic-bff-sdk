# 意图路由

> 对应源码：`agentic_bff_sdk/router.py`

## 设计思路

TopLevelRouter 是请求进入编排层后的第一个决策点。它需要回答一个问题：**用户想做什么？** 答案可能是明确的意图、需要澄清的歧义、或者完全无法识别。

路由采用**多级决策链**设计，按优先级依次尝试：

```
用户输入
  → 1. 优先匹配规则（关键词/正则，跳过 LLM）
  → 2. LLM 意图识别（返回候选列表 + 置信度）
  → 3. 歧义检测（前两名置信度差值 < ambiguity_range？）
  → 4. 置信度阈值（最高置信度 < threshold？）
  → 5. 兜底路由（无候选时的 fallback handler）
```

## 核心接口

```python
class TopLevelRouter(ABC):
    async def route(self, user_input, session_state, mode=GENERATE)
        -> IntentResult | ClarificationQuestion
    def register_priority_rule(self, rule: Dict) -> None
    def register_fallback_handler(self, handler) -> None
```

## DefaultTopLevelRouter

### 构造参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `llm` | BaseLanguageModel | LangChain LLM 实例 |
| `config` | SDKConfig | 配置（阈值、歧义范围等） |
| `intent_recognizer` | Callable | 可注入的自定义意图识别函数 |

### 优先匹配规则

```python
router.register_priority_rule({
    "pattern": r"余额",           # 正则或关键词
    "intent_type": "check_balance", # 匹配时返回的意图
    "priority": "high",            # 额外参数，会传入 IntentResult.parameters
})
```

规则按注册顺序匹配，首个命中即返回（置信度 1.0），不调用 LLM。仅在 `GENERATE` 模式下检查。

### 歧义检测

当前两个候选意图的置信度差值 < `intent_ambiguity_range`（默认 0.1）时，返回 `ClarificationQuestion` 让用户选择。

### RouterMode

- `GENERATE`：首次识别，走完整决策链
- `CONFIRM`：确认模式，跳过优先规则和歧义检测，直接返回最高置信度意图

## 扩展方向

- **自定义 intent_recognizer**：最常见的扩展点，替换 LLM 调用逻辑
- **多模型投票**：在 recognizer 中调用多个 LLM，取投票结果
- **意图缓存**：对相同输入缓存意图结果，减少 LLM 调用
- **完全自定义 Router**：继承 `TopLevelRouter` ABC，实现基于规则引擎的路由
