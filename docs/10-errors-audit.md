# 错误处理与审计日志

> 对应源码：`agentic_bff_sdk/errors.py`、`agentic_bff_sdk/audit.py`

## 统一错误处理框架

### 设计思路

SDK 定义了一套完整的错误分类体系，每种错误都有明确的错误码、可恢复性标记和标准化的 ErrorResponse 转换。这使得上层调用方可以根据错误类型做出精确的处理决策。

### 错误码常量

| 前缀 | 类别 | 错误码 |
|------|------|--------|
| `REQ_` | 请求验证 | MISSING_SESSION_ID, MISSING_CHANNEL_ID, INVALID_FORMAT |
| `SESSION_` | 会话 | NOT_FOUND, EXPIRED |
| `ROUTE_` | 意图路由 | NO_INTENT, LOW_CONFIDENCE, AMBIGUOUS |
| `PLAN_` | 计划生成 | GENERATION_TIMEOUT, GENERATION_FAILED, INVALID_STRUCTURE |
| `DISPATCH_` | 调度 | CYCLE_DETECTED, STEP_TIMEOUT, STEP_FAILED |
| `DOMAIN_` | 领域调用 | NOT_REGISTERED, SERVICE_UNAVAILABLE, CALL_FAILED |
| `RULE_` | 规则引擎 | TIMEOUT, ERROR, NOT_CONFIGURED |
| `AGG_` | 聚合 | PARTIAL_RESULTS, TIMEOUT |
| `SYNTH_` | 综合 | QUALITY_LOW, LLM_FAILED |
| `SYS_` | 系统 | INTERNAL_ERROR, CONFIGURATION_ERROR |

### 异常层次

```
Exception
  └── SDKError (code, message, details, recoverable)
        ├── RequestValidationError  (recoverable=False)
        ├── SessionError            (recoverable=True)
        ├── RoutingError            (recoverable=False)
        ├── PlanningError           (recoverable=True)
        ├── DispatchError           (recoverable=False)
        ├── DomainError             (recoverable=True)
        ├── RuleEngineError         (recoverable=True)
        ├── AggregationError        (recoverable=True)
        ├── SynthesisError          (recoverable=True)
        └── SystemError             (recoverable=False)
```

### 错误传播策略

| 可恢复性 | 处理方式 | 示例 |
|---------|---------|------|
| 可恢复 | 重试或降级 | DomainError → 重试 3 次或返回缓存数据 |
| 不可恢复 | 立即返回 ErrorResponse | RequestValidationError → 返回错误码 |
| 部分失败 | 标记 partial 继续 | AggregationError → 用已有结果继续综合 |

### 工具函数

```python
# 转换为 ErrorResponse
resp = handle_sdk_error(error)

# 判断可恢复性
if is_recoverable(error):
    retry()
else:
    return error.to_error_response()

# 构造部分失败响应
resp = create_partial_failure_response(session_id, partial_content, missing_info)
```

### 扩展方向

- **错误码注册表**：支持业务方注册自定义错误码
- **错误统计**：按错误码聚合统计，接入监控系统
- **国际化**：错误消息支持多语言

---

## AuditLogger — 审计日志

### 设计思路

审计日志记录每次 DomainGateway 调用的摘要信息，用于合规审计和问题排查。通过 ABC 抽象，支持替换为任意日志后端。

### 核心接口

```python
class AuditLogger(ABC):
    async def log_invocation(self, domain, action, request_summary,
                              response_summary, success, duration_ms) -> None
```

### DefaultAuditLogger

使用 Python 标准 logging 模块：
- 成功调用 → `INFO` 级别
- 失败调用 → `WARNING` 级别
- 日志格式：`AUDIT | domain=fund action=query result=SUCCESS duration_ms=45.2 request=... response=...`

### 扩展方向

- **数据库审计**：实现 `DatabaseAuditLogger`，写入审计表
- **ELK 集成**：输出结构化 JSON 日志，接入 Elasticsearch
- **异步批量写入**：缓冲日志条目，批量写入以提高性能
