<p align="center">
  <img src="https://capsule-render.vercel.app/api?type=waving&height=220&color=0:0F172A,45:2563EB,100:06B6D4&text=Core%20Mind%20Agent%20Service&fontColor=FFFFFF&fontSize=42&fontAlignY=38&desc=AgentScope%202.0%20%2B%20agentscope-runtime%20智能顾问%20Agent%20服务&descAlignY=58&descSize=16" alt="Core Mind Agent Service" />
</p>

<p align="center">
  <a href="https://github.com/modelscope/agentscope"><img src="https://img.shields.io/badge/AgentScope-2.0.2-2563EB?style=for-the-badge" alt="AgentScope 2.0.2" /></a>
  <a href="https://github.com/modelscope/agentscope-runtime"><img src="https://img.shields.io/badge/agentscope--runtime-1.1.6-06B6D4?style=for-the-badge" alt="agentscope-runtime 1.1.6" /></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-AgentApp-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI AgentApp" /></a>
  <img src="https://img.shields.io/badge/SSE-Streaming-F59E0B?style=for-the-badge" alt="SSE Streaming" />
  <img src="https://img.shields.io/badge/LLM-DashScope%20%7C%20OpenAI%20%7C%20DeepSeek-111827?style=for-the-badge" alt="LLM Providers" />
</p>

<p align="center">
  基于 <strong>AgentScope 2.0</strong> 与 <strong>agentscope-runtime</strong> 构建的智能顾问 Agent 服务，提供端上协议兼容、SSE 流式输出、Skill 自动加载、会话记忆与运行时配置刷新能力。
</p>

---

## 目录

- [能力概览](#能力概览)
- [架构概览](#架构概览)
- [核心组件](#核心组件)
- [快速开始](#快速开始)
- [API 端点](#api-端点)
- [上下文记忆与运行时配置](#上下文记忆与运行时配置)
- [Skills](#skills)
- [技术栈](#技术栈)

## 能力概览

| 能力 | 说明 |
|------|------|
| 端上协议兼容 | API 格式与端上一致，支持 `think`、`tool_call`、`tool_response`、`response`、`card` 阶段 |
| 卡片输出 | 支持文卡文模式输出 |
| 会话记忆 | 支持基于 `userId + sessionId` 的 AgentScope 会话记忆，默认开启 AgentScope2 内置会话记忆 |
| Skill 加载 | 支持本地 Skills，并自动注册加载 `skills` 目录下工具 |
| ReAct 输出适配 | 适配端上 `think` + `response` 输出模式，解决 ReAct 架构下 `response` + `think` + `response` 混合输出问题 |

## 架构概览

```text
┌────────────────────────────────────────────────────────────┐
│                    FastAPI / AgentApp                       │
│        POST /chat   POST /process   GET /health             │
├────────────────────────────────────────────────────────────┤
│                    AgentScope Agent                         │
│                         ReAct                               │
│                                                            │
│   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   │
│   │     LLM      │   │   Toolkit    │   │    Skills    │   │
│   │ DashScope    │   │  本地工具     │   │  行业技能     │   │
│   │ OpenAI       │   │  自动注册     │   │  动态加载     │   │
│   │ DeepSeek     │   │              │   │              │   │
│   └──────────────┘   └──────────────┘   └──────────────┘   │
└────────────────────────────────────────────────────────────┘
```

## 核心组件

| 文件 | 职责 |
|------|------|
| `config.py` | 配置管理，从环境变量加载 |
| `model_factory.py` | LLM 模型工厂，支持 DashScope/OpenAI/DeepSeek |
| `agent_factory.py` | Agent 工厂，负责 Toolkit + Skill 加载 |
| `app.py` | FastAPI/AgentApp 主服务，包含所有端点 |
| `main.py` | 兼容启动入口，导入 `app.py` 中的 `agent_app` |
| `test_client.py` | 测试客户端 |

## 快速开始

### 1. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入你的 API Key
```

关键配置项：

| 配置项 | 说明 |
|--------|------|
| `LLM_API_KEY` | LLM API 密钥，必填 |
| `LLM_PROVIDER` | LLM 提供商，支持 `dashscope`、`openai`、`deepseek` |
| `LLM_MODEL` | 模型名称，例如 `qwen-max`、`gpt-4o` |

### 2. 启动服务

```bash
# 方式 1: 在当前目录直接运行
python app.py

# 兼容旧入口
python main.py

# 或者从上一级目录以包方式运行
cd ..
python -m agent_service.app
```

### 3. 测试服务

```bash
# 测试客户端
python test_client.py

# 自定义查询
python test_client.py "宝马5系和奥迪A6L哪个空间大"

# 基础端点
curl http://localhost:8000/health
curl http://localhost:8000/tools
curl http://localhost:8000/agent-info

# /chat SSE 测试
curl -N -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "query": "宝马5系和奥迪A6L哪个好",
    "sessionId": "sess_demo_001",
    "userId": "demo-user",
    "reqId": "demo-req-001"
  }'
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/chat` | 主端点，自定义 SSE 协议，支持 `think`、`tool_call`、`tool_response`、`response`、`card` 阶段 |
| POST | `/process` | agentscope-runtime 标准 SSE 端点 |
| POST | `/config/refresh` | 重新拉取运行时配置并重建 Agent |
| GET | `/health` | 健康检查 |
| GET | `/tools` | 列出可用工具 |
| GET | `/agent-info` | Agent 配置信息 |

### POST /chat 请求格式

```json
{
  "query": "宝马5系和奥迪A6L哪个好",
  "sessionId": "sess_17725219637_6b90pf01212yf1",
  "userId": "175953208",
  "reqId": "lzy123456"
}
```

### POST /process 请求格式

```json
{
  "input": [
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "宝马5系和奥迪A6L哪个好"}
      ]
    }
  ],
  "stream": true,
  "session_id": "optional-session-id",
  "user_id": "optional-user-id"
}
```

## 上下文记忆与运行时配置

### `/chat` 上下文记忆策略

| 场景 | 策略 |
|------|------|
| 配置了 `ENGINE_URL` | 优先调用 `POST {ENGINE_URL}/engine/get/memory` 拉取 `userId + sessionId` 对应的历史问答，读取超时 5 秒，失败不影响主对话 |
| 未配置 `ENGINE_URL` | 回退到进程内的 AgentScope 会话记忆 |

### 运行时配置策略

服务启动时会先读取 `env`，再尝试调用 `GET {ENGINE_URL}/engine/get/config` 拉取运行时配置。远程配置可覆盖以下字段：

| 配置字段 | 配置字段 | 配置字段 |
|----------|----------|----------|
| `agentName` | `agentMaxIters` | `agentEnableSessionMemory` |
| `llmProvider` | `llmModel` | `llmApiKey` |
| `llmBaseUrl` | `llmStream` | `llmEnableThinking` |
| `llmContextSize` | | |

当远程配置接口不可用时，服务会回退到本地 `env` 配置继续启动。后台修改 MySQL 配置后，可调用 `POST /config/refresh` 触发服务重新拉取配置、重建 Agent，并清理进程内会话缓存；之后的新请求会使用新配置。

## Skills

系统 prompt 中的 Skill 目录由 `agent_service/prompt_loader.py` 动态生成：

| 项目 | 说明 |
|------|------|
| 当前加载 | 当前仅加载 `skills/buy_car/SKILL.md` |
| Skill 声明 | 每个 Skill 在 `SKILL.md` front matter 中声明 `name`、`description`、`config` 等信息 |
| 新增方式 | 新增 Skill 时通常只需要新增对应目录和 `SKILL.md`，无需修改 `config.py` 的系统 prompt |

### buy_car_service（BBA 买车推荐助手）

当用户表达买车推荐需求时触发，通过多轮对话持续补充预算、品牌、车型三个必要条件：

1. 条件抽取：从用户输入中识别预算、品牌、车型
2. 状态维护：记住已确认条件，支持后续补充或覆盖修改
3. 推荐查询：条件新增或变化后调用 `mock_recommend_cars` 刷新推荐结果
4. 缺槽追问：缺少必要条件时优先追问预算、车型、品牌
5. 输出结果：以 Markdown 输出当前条件、推荐列表和下一步引导

## 技术栈

| 分类 | 技术 |
|------|------|
| Agent Framework | AgentScope 2.0.2 |
| Deployment Runtime | agentscope-runtime 1.1.6 |
| Web Framework | FastAPI via AgentApp |
| LLM | DashScope Qwen / OpenAI / DeepSeek |
