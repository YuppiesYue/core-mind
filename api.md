# Core Mind API 接口文档

## 1. 文档说明

- 服务框架：`FastAPI + AgentScope Runtime`
- 默认端口：`8000`
- 默认本地联调地址：`http://localhost:8000`
- 配置项来源：`APP_HOST`、`APP_PORT` 等环境变量，代码默认值见 [config.py](/Users/liuzhiyue/PycharmProjects/core_mind/config.py)

说明：

- `app.py` 中显式定义的接口有：`/chat`、`/health`、`/tools`、`/agent-info`、`/config/refresh`
- `/process` 由 `AgentApp(endpoint_path="/process")` 提供，属于运行时标准端点
- 若实际部署域名或端口不同，请将文档中的 `http://localhost:8000` 替换为真实地址

## 2. 接口总览

| 方法 | 路径 | 用途 | 返回类型 |
| --- | --- | --- | --- |
| POST | `/chat` | 推荐联调主接口，自定义 SSE 流式协议 | `text/event-stream` |
| POST | `/process` | AgentScope Runtime 标准处理接口 | `text/event-stream` |
| GET | `/health` | 健康检查 | `application/json` |
| GET | `/tools` | 获取当前注册工具列表 | `application/json` |
| GET | `/agent-info` | 获取 Agent 信息和运行时配置 | `application/json` |
| POST | `/config/refresh` | 重新加载配置并重建 Agent | `application/json` |

## 3. 通用约定

### 3.1 Base URL

- 本地默认：`http://localhost:8000`

### 3.2 通用 Header

不同接口的 Header 要求如下：

| Header | 是否必填 | 说明 |
| --- | --- | --- |
| `Content-Type: application/json` | POST 接口必填 | 请求体为 JSON |
| `Accept: text/event-stream` | SSE 接口建议传 | 便于前端按流式响应处理 |

### 3.3 错误响应风格

当前代码中错误返回没有完全统一，主要分两类：

1. 简单错误：

```json
{
  "error": "错误信息"
}
```

2. 刷新配置接口错误：

```json
{
  "code": 1,
  "message": "CONFIG_REFRESH_FAILED: xxx"
}
```

## 4. 接口明细

## 4.1 POST /chat

### 接口概述

推荐前端联调时使用的主接口。该接口返回自定义 SSE 事件流，支持：

- 思考过程流式输出
- 最终回答流式输出
- 工具调用状态输出
- 卡片数据穿插输出
- 会话记忆读取与保存

### 接口信息

- 接口路径：`/chat`
- 接口描述：自定义 SSE 聊天接口
- 接口地址：`http://localhost:8000/chat`

### 请求参数

#### Header 参数

| 参数名 | 是否必填 | 示例值 | 说明 |
| --- | --- | --- | --- |
| `Content-Type` | 是 | `application/json` | 请求体类型 |
| `Accept` | 否 | `text/event-stream` | 建议传，表示期望流式响应 |

#### Body 参数

| 参数名 | 类型 | 是否必填 | 示例值 | 说明 |
| --- | --- | --- | --- | --- |
| `query` | string | 是 | `宝马5系和奥迪A6L对比` | 当前轮用户问题 |
| `sessionId` | string | 是 | `sess_17725219637_6b90pf01212yf1` | 会话 ID |
| `userId` | string | 是 | `175953208` | 用户 ID |
| `reqId` | string | 是 | `lzy123456` | 请求 ID，用于日志追踪 |

请求体必须是 JSON 对象，且以上 4 个字段都必须为非空字符串。

### 请求示例

```bash
curl -N -X POST 'http://localhost:8000/chat' \
  -H 'Content-Type: application/json' \
  -H 'Accept: text/event-stream' \
  -d '{
    "query": "宝马5系和奥迪A6L对比",
    "sessionId": "sess_17725219637_6b90pf01212yf1",
    "userId": "175953208",
    "reqId": "lzy123456"
  }'
```

```json
{
  "query": "宝马5系和奥迪A6L对比",
  "sessionId": "sess_17725219637_6b90pf01212yf1",
  "userId": "175953208",
  "reqId": "lzy123456"
}
```

### 响应格式

- 响应类型：`text/event-stream`
- 返回方式：SSE 流式返回

服务端会设置以下响应头：

| Header | 值 |
| --- | --- |
| `Content-Type` | `text/event-stream` |
| `Cache-Control` | `no-cache` |
| `Connection` | `keep-alive` |
| `X-Accel-Buffering` | `no` |

每条 SSE 消息格式如下：

```text
data: {"stage":"响应阶段","content":[{"type":"数据类型","msg":"内容"}]}

```

流结束标记：

```text
data: [DONE]

```

### SSE 阶段说明

| stage | 含义 | content.type | 说明 |
| --- | --- | --- | --- |
| `think` | 思考过程 | `text` | 回答正式开始前的思考内容 |
| `think_delta` | 中间规划过程 | `text` | 工具调用前后的中间态文本 |
| `response` | 最终回复 | `text` | 展示给用户的正式回答 |
| `card` | 卡片数据 | `card` | 卡片 JSON 数据 |
| `tool_call` | 工具调用开始 | `text` | 包含工具名、状态等信息 |
| `tool_response` | 工具调用结果 | `text` | 包含工具结果摘要、耗时等信息 |

### 响应示例

```text
data: {"stage":"think","content":[{"type":"text","msg":"我先对比两款车的定位和核心参数。"}]}

data: {"stage":"tool_call","content":[{"type":"text","msg":"正在调用 car_intelligence_search","tool_name":"car_intelligence_search","tool_name_cn":"car_intelligence_search","status":"calling"}]}

data: {"stage":"tool_response","content":[{"type":"text","msg":"已查询到相关车型数据","tool_name":"car_intelligence_search","tool_name_cn":"car_intelligence_search","status":"completed","duration_ms":356,"execution_ms":240}]}

data: {"stage":"response","content":[{"type":"text","msg":"宝马5系和奥迪A6L都属于中大型豪华轿车。"}]}

data: {"stage":"card","content":[{"type":"card","msg":{"card_type":"car_series_compare_main_params_table","card_data":{"seriesA":"宝马5系","seriesB":"奥迪A6L"}}}]}

data: {"stage":"response","content":[{"type":"text","msg":"如果你更看重驾驶感受，可以优先考虑宝马5系。"}]}

data: [DONE]

```

### `tool_call` / `tool_response` 常见字段

#### `tool_call`

```json
{
  "stage": "tool_call",
  "content": [
    {
      "type": "text",
      "msg": "正在调用 car_intelligence_search",
      "tool_name": "car_intelligence_search",
      "tool_name_cn": "car_intelligence_search",
      "status": "calling"
    }
  ]
}
```

#### `tool_response`

```json
{
  "stage": "tool_response",
  "content": [
    {
      "type": "text",
      "msg": "已查询到相关车型数据",
      "tool_name": "car_intelligence_search",
      "tool_name_cn": "car_intelligence_search",
      "status": "completed",
      "duration_ms": 356,
      "execution_ms": 240
    }
  ]
}
```

说明：

- `duration_ms`：从发起工具调用到结果收尾的总耗时
- `execution_ms`：工具实际执行阶段耗时
- 若工具属于 skill 工具，可能额外返回 `skill_name`、`skill_name_cn`

### 卡片返回说明

`card` 事件的 `content[0]` 结构如下：

```json
{
  "type": "card",
  "msg": {
    "card_type": "car_series_compare_main_params_table",
    "card_data": {}
  }
}
```

说明：

- `card_type`：卡片类型
- `card_data`：卡片渲染数据，结构由具体业务卡片决定

### 业务行为说明

- 接口支持会话记忆
- 当配置了 `ENGINE_URL` 时，会优先调用外部接口拉取历史记忆
- 外部记忆拉取地址：`{ENGINE_URL}/engine/get/memory`
- 本轮结束后会异步保存记忆到：`{ENGINE_URL}/engine/save/memory`
- 若未配置 `ENGINE_URL`，则回退为进程内会话记忆

### 失败响应示例

#### 1. JSON 非法

```json
{
  "error": "Invalid JSON body"
}
```

#### 2. 缺少必填字段

```json
{
  "error": "Missing required fields: sessionId, userId, reqId"
}
```

#### 3. 字段类型或内容不合法

```json
{
  "error": "Field 'query' must be a non-empty string"
}
```

## 4.2 POST /process

### 接口概述

这是 `AgentApp` 提供的标准处理接口，路径由 `endpoint_path="/process"` 指定。它更偏底层运行时协议，不像 `/chat` 那样做了自定义流式包装，因此前端联调优先建议用 `/chat`。

### 接口信息

- 接口路径：`/process`
- 接口描述：AgentScope Runtime 标准 SSE 处理接口
- 接口地址：`http://localhost:8000/process`

### 请求参数

#### Header 参数

| 参数名 | 是否必填 | 示例值 | 说明 |
| --- | --- | --- | --- |
| `Content-Type` | 是 | `application/json` | 请求体类型 |
| `Accept` | 否 | `text/event-stream` | 建议传 |

#### Body 参数

该接口由 runtime 标准协议处理，当前 `query_func()` 接收的是 `msgs` / `messages` 形式的输入。结合代码实现，联调时建议按下面格式传递：

| 参数名 | 类型 | 是否必填 | 说明 |
| --- | --- | --- | --- |
| `messages` | array | 是 | 对话消息列表 |
| `messages[].role` | string | 是 | 角色，通常为 `user` |
| `messages[].content` | string | 是 | 用户问题内容 |

### 请求示例

```bash
curl -N -X POST 'http://localhost:8000/process' \
  -H 'Content-Type: application/json' \
  -H 'Accept: text/event-stream' \
  -d '{
    "messages": [
      {
        "role": "user",
        "content": "宝马5系和奥迪A6L怎么选"
      }
    ]
  }'
```

```json
{
  "messages": [
    {
      "role": "user",
      "content": "宝马5系和奥迪A6L怎么选"
    }
  ]
}
```

### 响应格式

- 响应类型：`text/event-stream`
- 响应说明：标准 runtime SSE 流

当前 `query_func()` 的核心行为是持续产出文本消息块，块结构接近：

```json
{
  "name": "智能助手",
  "content": [
    {
      "type": "text",
      "text": "宝马5系和奥迪A6L都属于中大型豪华轿车。"
    }
  ],
  "role": "assistant"
}
```

说明：

- 该接口没有 `/chat` 那样的 `stage` 字段
- 该接口当前没有显式做自定义记忆注入文档约定
- 前端若只做业务联调，建议优先使用 `/chat`

## 4.3 GET /health

### 接口概述

用于检查服务是否存活，以及当前 Agent 和模型是否已加载。

### 接口信息

- 接口路径：`/health`
- 接口描述：健康检查
- 接口地址：`http://localhost:8000/health`

### 请求参数

#### Header 参数

无特殊要求。

#### Body 参数

无。

### 请求示例

```bash
curl 'http://localhost:8000/health'
```

### 响应格式

```json
{
  "status": "healthy",
  "agent": "智能助手",
  "llm_model": "qwen-max",
  "config_source": "env"
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `status` | string | 服务状态，正常为 `healthy` |
| `agent` | string \| null | 当前 Agent 名称 |
| `llm_model` | string \| null | 当前使用的模型名 |
| `config_source` | string | 配置来源，如 `env`、`env+remote` |

## 4.4 GET /tools

### 接口概述

返回当前 Agent 已注册的工具 schema，适合前端或调试方查看服务能力。

### 接口信息

- 接口路径：`/tools`
- 接口描述：获取已注册工具列表
- 接口地址：`http://localhost:8000/tools`

### 请求参数

#### Header 参数

无特殊要求。

#### Body 参数

无。

### 请求示例

```bash
curl 'http://localhost:8000/tools'
```

### 响应格式

```json
{
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "resolve_series_entities",
        "description": "解析车系实体",
        "parameters": {
          "type": "object",
          "properties": {}
        }
      }
    }
  ]
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `tools` | array | 工具 schema 列表 |

补充说明：

- 若 Agent 尚未初始化或未挂载 toolkit，则返回：

```json
{
  "tools": []
}
```

## 4.5 GET /agent-info

### 接口概述

返回当前 Agent 的基础信息和运行时配置摘要，适合联调时确认服务加载的是哪套模型和参数。

### 接口信息

- 接口路径：`/agent-info`
- 接口描述：获取 Agent 基本信息
- 接口地址：`http://localhost:8000/agent-info`

### 请求参数

#### Header 参数

无特殊要求。

#### Body 参数

无。

### 请求示例

```bash
curl 'http://localhost:8000/agent-info'
```

### 响应格式

```json
{
  "name": "智能助手",
  "description": "基于 AgentScope 2.0 的智能顾问 Agent 服务",
  "runtimeConfig": {
    "agentName": "智能助手",
    "agentMaxIters": 20,
    "agentEnableSessionMemory": true,
    "llmProvider": "openai",
    "llmModel": "qwen-max",
    "llmApiKeyMasked": "",
    "llmBaseUrl": "",
    "llmStream": true,
    "llmEnableThinking": true,
    "llmContextSize": 131072,
    "engineUrl": ""
  }
}
```

### 失败响应

当 Agent 尚未初始化时，返回：

```json
{
  "error": "Agent not initialized"
}
```

HTTP 状态码：`503`

## 4.6 POST /config/refresh

### 接口概述

主动刷新运行时配置并重建 Agent。适合后台更新远程配置后，通知当前服务重新加载。

### 接口信息

- 接口路径：`/config/refresh`
- 接口描述：刷新配置并重建 Agent
- 接口地址：`http://localhost:8000/config/refresh`

### 请求参数

#### Header 参数

| 参数名 | 是否必填 | 示例值 | 说明 |
| --- | --- | --- | --- |
| `Content-Type` | 否 | `application/json` | 可传可不传，该接口无请求体 |

#### Body 参数

无。

### 请求示例

```bash
curl -X POST 'http://localhost:8000/config/refresh'
```

### 响应格式

#### 成功响应

```json
{
  "code": 0,
  "message": "SUCCESS",
  "data": {
    "reason": "manual_refresh",
    "configSource": "env+remote",
    "remoteApplied": true,
    "remoteUrl": "http://example.com/engine/get/config",
    "appliedFields": [
      "agent_name",
      "llm_model"
    ],
    "runtimeConfig": {
      "agentName": "智能助手",
      "agentMaxIters": 20,
      "agentEnableSessionMemory": true,
      "llmProvider": "openai",
      "llmModel": "qwen-max",
      "llmApiKeyMasked": "sk-****",
      "llmBaseUrl": "",
      "llmStream": true,
      "llmEnableThinking": true,
      "llmContextSize": 131072,
      "engineUrl": "http://example.com"
    },
    "registeredToolCount": 3,
    "clearedSessionStates": 2
  }
}
```

#### 成功响应字段说明

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `code` | number | `0` 表示成功 |
| `message` | string | 成功消息，固定为 `SUCCESS` |
| `data.reason` | string | 触发原因，当前为 `manual_refresh` |
| `data.configSource` | string | 配置来源 |
| `data.remoteApplied` | boolean | 是否成功应用远程配置 |
| `data.remoteUrl` | string | 远程配置拉取地址 |
| `data.appliedFields` | array | 被远程配置覆盖的字段名 |
| `data.runtimeConfig` | object | 当前运行时配置摘要 |
| `data.registeredToolCount` | number | 当前注册工具数量 |
| `data.clearedSessionStates` | number | 本次清理的会话状态数量 |

#### 失败响应

```json
{
  "code": 1,
  "message": "CONFIG_REFRESH_FAILED: xxx"
}
```

HTTP 状态码：`502`

## 5. 联调建议

### 推荐优先使用 `/chat`

原因：

- 返回结构对前端更友好
- 有明确的 `stage` 字段
- 支持工具状态、卡片、回答文本混合流式输出
- 更符合当前业务问答场景

### 前端处理 `/chat` 的建议

前端可以按如下思路处理 SSE：

1. 监听每一条 `data: ...`
2. 若收到 `[DONE]`，结束本轮流
3. 否则解析 JSON，并根据 `stage` 分发渲染
4. `response` 追加到聊天正文
5. `card` 交给卡片组件渲染
6. `tool_call` 和 `tool_response` 可选择显示或仅用于调试

### 最小联调请求示例

```json
{
  "query": "给我对比一下宝马5系和奥迪A6L",
  "sessionId": "test-session-001",
  "userId": "test-user-001",
  "reqId": "test-req-001"
}
```

## 6. 文档对应代码

- 主文件：[app.py](/Users/liuzhiyue/PycharmProjects/core_mind/app.py)
- 配置文件：[config.py](/Users/liuzhiyue/PycharmProjects/core_mind/config.py)

