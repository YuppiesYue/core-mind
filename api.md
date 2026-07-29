# Auto Car Agent Service — API 接口文档

> 基于 AgentScope 2.0 + agentscope-runtime 的汽车智能顾问 FastAPI 服务

## 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/chat` | **主端点** — 自定义 SSE 协议，基于 AgentScope 会话记忆续聊 |
| POST | `/process` | agentscope-runtime 标准 SSE 端点 |
| GET | `/health` | 健康检查 |
| GET | `/tools` | 列出本地可用工具 |
| GET | `/agent-info` | Agent 基本信息 |

基础 URL：`http://<host>:8000`

---

## POST /chat

**推荐使用的端点。** 自定义 SSE 流式输出，优先通过外部记忆接口恢复上下文；未配置外部记忆时回退到 AgentScope 2.0 内置会话记忆。

### 请求

```
Content-Type: application/json
```

#### 请求体

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `query` | string | ✅ | 用户原始问题，服务以此作为当前轮实际提问内容 |
| `sessionId` | string | ✅ | 会话 ID；用于获取外部上下文记忆，未配置外部记忆时也用于组成会话记忆 key |
| `userId` | string | ✅ | 用户 ID；用于获取外部上下文记忆，未配置外部记忆时也用于组成会话记忆 key |
| `reqId` | string | ✅ | 请求 ID；用于日志追踪 |

> **唯一支持协议：** `/chat` 只接受 camelCase 这一版请求体，`query`、`sessionId`、`userId`、`reqId` 都是必填。
>
> **会话记忆：** 默认优先调用 `ENGINE_URL + /engine/get/memory` 拉取历史问答作为当前轮上下文，超时为 5 秒；如果外部记忆不可用或获取失败，本轮对话仍继续。未配置 `ENGINE_URL` 时，服务回退到基于 `userId:sessionId` 的 AgentScope 2.0 进程内会话记忆。

#### 请求体示例

```json
{
  "query": "宝马5系和奥迪A6L对比",
  "sessionId": "sess_17725219637_6b90pf01212yf1",
  "userId": "175953208",
  "reqId": "lzy123456"
}
```

### 行为说明

- 调用方每次只传当前轮 `query`，不再传 `messages` 或外部记忆。
- 已配置 `ENGINE_URL` 时，服务会向 `POST {ENGINE_URL}/engine/get/memory` 请求历史问答，并将返回的 `query/answer` 对注入当前轮上下文。
- 外部记忆读取超时固定为 5 秒，失败只记日志，不影响主对话继续执行。
- 未配置 `ENGINE_URL` 时，服务内部仍使用 `userId:sessionId` 维护 AgentScope 会话状态。
- 不再处理入口层的预置 `entities` 注入。

### 响应

```
Content-Type: text/event-stream
```

#### SSE 协议

每个事件格式为：

```
data: {"stage": "<stage>", "content": [{"type": "<type>", "msg": "<content>"}]}\n\n
```

#### Stage 列表

| stage | 说明 | 流式 | content.type | content.msg |
|-------|------|:----:|-------------|-------------|
| `think` | LLM 思考过程（response 开始前） | ✅ | `text` | 思考文本片段 |
| `think_delta` | LLM 中间态规划文本（工具调用前的意图描述） | ✅ | `text` | 规划文本片段 |
| `response` | LLM 最终回复文本 | ✅ | `text` | 回复文本片段（已替换卡片占位符） |
| `card` | 卡片 JSON 数据 | ❌ | `card` | `{card_type, card_data}` 对象 |
| `tool_call` | 工具调用开始 | ❌ | `text` | `"正在调用 <tool_name>"` |
| `tool_response` | 工具调用结果 | ❌ | `text` | 工具返回结果（截断至 2000 字符） |

#### 典型事件流

```
data: {"stage": "think",        "content": [{"type": "text", "msg": "用户想对比..."}]}
data: {"stage": "tool_call",    "content": [{"type": "text", "msg": "正在调用 car_intelligence_search", "tool_name": "car_intelligence_search", "status": "calling"}]}
data: {"stage": "tool_response","content": [{"type": "text", "msg": "{...}", "tool_name": "car_intelligence_search", "status": "completed"}]}
data: {"stage": "think_delta",  "content": [{"type": "text", "msg": "数据到手，开始拉取参数表格——"}]}
data: {"stage": "tool_call",    "content": [{"type": "text", "msg": "正在调用 fetch_and_fill_card_bottom_pk", "tool_name": "fetch_and_fill_card_bottom_pk", "status": "calling"}]}
data: {"stage": "tool_response","content": [{"type": "text", "msg": "卡片已生成，等待占位符输出：bottom_pk", "tool_name": "fetch_and_fill_card_bottom_pk", "status": "completed"}]}
data: {"stage": "response",     "content": [{"type": "text", "msg": "宝马5系和奥迪A6L都是中大型豪华轿车..."}]}
data: {"stage": "response",     "content": [{"type": "text", "msg": "\n## 🔍 关键参数对比\n\n"}]}
data: {"stage": "card",         "content": [{"type": "card", "msg": {"card_type": "car_series_compare_main_params_table", "card_data": {...}}}]}
data: {"stage": "response",     "content": [{"type": "text", "msg": "从参数表可以看到..."}]}
data: {"stage": "card",         "content": [{"type": "card", "msg": {"card_type": "car_series_compare_main_review", "card_data": {...}}}]}
data: {"stage": "response",     "content": [{"type": "text", "msg": "综合来看，两车各有所长..."}]}
data: {"stage": "card",         "content": [{"type": "card", "msg": {"card_type": "car_series_compare_bottom_pk", "card_data": {...}}}]}
```

#### 卡片输出机制

卡片通过 **占位符** 穿插在回复文本中输出，而非集中到最后：

1. Agent 调用卡片工具 → 返回结果 → 服务解析 `{card_type, card_data}` 存入缓冲区
2. LLM 在回复文本中输出 `{{card:TAG}}` → 服务检测占位符 → 就地输出 `card` stage 事件
3. LLM 漏写占位符 → 服务丢弃未匹配卡片，只记录日志，不自动输出到末尾

**占位符列表：**

| 占位符 | 卡片类型 |
|--------|---------|
| `{{card:bottom_pk}}` | 底卡（价格 + 图片） |
| `{{card:params}}` | 核心参数表格 |
| `{{card:review}}` | 车主评价 |
| `{{card:suggest}}` | 选购建议结论 |
| `{{card:feedback}}` | 反馈选项 |

### 错误响应

| HTTP 状态码 | 场景 | body |
|:-----------:|------|------|
| 400 | JSON 解析失败 | `{"error": "Invalid JSON body"}` |
| 400 | 缺少必填字段或字段格式不合法 | 例如 `{"error": "Missing required fields: sessionId, userId, reqId"}` |
| 503 | Agent 未初始化 | `{"error": "Agent not initialized"}` |

---

## POST /process

agentscope-runtime 标准处理端点。简化版，**不支持**记忆注入和预置车系。

### 请求

agentscope-runtime 标准格式，由框架自动处理。

```json
{
  "messages": [
    {"role": "user", "content": "宝马5系和奥迪A6L怎么选"}
  ]
}
```

### 响应

agentscope-runtime 标准 SSE 格式。

---

## GET /health

健康检查端点。

### 响应

```json
{
  "status": "healthy",
  "agent": "Auto Car Agent"
}
```

---

## GET /tools

列出 Agent 已注册的本地可用工具。

### 响应

```json
{
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "resolve_series_entities",
        "description": "...",
        "parameters": { ... }
      }
    }
  ]
}
```

---

## GET /agent-info

Agent 基本信息。

### 响应

```json
{
  "name": "Auto Car Agent",
  "description": "基于 AgentScope 2.0 的汽车智能顾问 Agent 服务，支持双车对比、车型查询、智能推荐等"
}
```

---

## 调用示例

### cURL

```bash
curl -N -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "query": "宝马5系和奥迪A6L怎么选",
    "sessionId": "sess_demo_001",
    "userId": "demo-user",
    "reqId": "demo-req-001"
  }'
```

### Python (requests + SSE 解析)

```python
import requests
import json

url = "http://localhost:8000/chat"
payload = {
    "query": "宝马5系和奥迪A6L怎么选",
    "sessionId": "sess_demo_001",
    "userId": "demo-user",
    "reqId": "demo-req-001"
}

response = requests.post(url, json=payload, stream=True)

for line in response.iter_lines(decode_unicode=True):
    if line.startswith("data: "):
        event = json.loads(line[6:])
        stage = event["stage"]
        content = event["content"][0]

        if stage == "think":
            print(f"[思考] {content['msg']}", end="")
        elif stage == "think_delta":
            print(f"[规划] {content['msg']}", end="")
        elif stage == "response":
            print(f"{content['msg']}", end="")
        elif stage == "card":
            card = content["msg"]
            print(f"\n🎴 [卡片: {card['card_type']}]")
        elif stage == "tool_call":
            print(f"\n🔧 {content.get('tool_name', '')} ...")
        elif stage == "tool_response":
            print(f"  ✅ {content.get('tool_name', '')} done")
```


---

## 内部处理流程

```
请求进入
  │
  ├─ 1. 校验请求体 → query / sessionId / userId / reqId
  ├─ 2. 读取或创建 userId:sessionId 对应的 AgentScope 会话状态
  ├─ 3. 构造当前轮 user_msg
  │
  └─ 4. reply_stream → SSE 事件流
       ├─ ThinkingBlock  → think / think_delta
       ├─ TextBlock      → 缓冲 → ToolCall? think_delta : response
       ├─ ToolCall       → tool_call → tool_response
       │   └─ 卡片工具    → 解析 card_data → 存入 pending_cards
       ├─ {{card:TAG}}   → 匹配 pending_cards → card stage
       └─ ReplyEnd       → flush 缓冲 + 丢弃未匹配卡片
```

---

## 配置项

通过环境变量配置：

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `LLM_API_KEY` | — | LLM API 密钥（必填） |
| `LLM_MODEL` | `qwen-max` | 模型名称 |
| `LLM_BASE_URL` | `https://gateway.corpautohome.com/v1` | LLM 网关地址 |
| `AGENT_ENABLE_SESSION_MEMORY` | `true` | 是否启用 AgentScope 2.0 会话记忆；开启后按 `userId:sessionId` 复用上下文 |
| `APP_HOST` | `0.0.0.0` | 服务监听地址 |
| `APP_PORT` | `8000` | 服务端口 |

---
