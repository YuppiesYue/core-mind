# 🚗 Auto Car Agent Service

基于 **AgentScope 2.0** + **agentscope-runtime** 构建的汽车智能顾问 Agent 服务。

## 架构概览

```
┌─────────────────────────────────────────────────┐
│                 FastAPI (AgentApp)               │
│  POST /chat  POST /process  GET /health          │
├─────────────────────────────────────────────────┤
│              AgentScope Agent (ReAct)            │
│  ┌──────────┐  ┌────────────┐  ┌────────────┐  │
│  │ LLM      │  │ Toolkit    │  │ Skills     │  │
│  │ (DashScope│  │ (本地工具) │  │ (汽车对比) │  │
│  │  /OpenAI) │  │            │  │            │  │
│  └──────────┘  └─────┬──────┘  └────────────┘  │
└─────────────────────────────────────────────────┘
```

## 当前已支持能力

- 已支持 API 能力，格式与端上一致，包含 `think`、`tool_call`、`tool_response`、`response`、`card`
- 已支持卡片输出（文卡文模式）
- 已支持输入变量以及记忆外部注入
- 已支持本地 Skills 以及 `skills` 目录下工具自动注册加载
- 适配端上 `think` + `response` 输出模式，解决 ReAct 架构下 `response` + `think` + `response` 混合输出问题
- 支持切换记忆能力，AgentScope2 内置或外部传入

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
- `LLM_API_KEY`: LLM API 密钥（必填）
- `LLM_PROVIDER`: LLM 提供商（dashscope/openai/deepseek）
- `LLM_MODEL`: 模型名称（如 qwen-max, gpt-4o）

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

### 3. 测试

```bash
# 测试客户端
python test_client.py

# 自定义查询
python test_client.py "宝马5系和奥迪A6L哪个空间大"

# curl 测试
curl http://localhost:8000/health
curl http://localhost:8000/tools
curl http://localhost:8000/agent-info

curl -N -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"query":"宝马5系和奥迪A6L哪个好"}'
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/chat` | 主端点，自定义 SSE 协议，支持 `think`、`tool_call`、`tool_response`、`response`、`card` 阶段 |
| POST | `/process` | agentscope-runtime 标准 SSE 端点 |
| GET | `/health` | 健康检查 |
| GET | `/tools` | 列出可用工具 |
| GET | `/agent-info` | Agent 配置信息 |

### POST /chat 请求格式

```json
{
  "query": "宝马5系和奥迪A6L哪个好",
  "final_query": "宝马5系和奥迪A6L哪个好",
  "memory": {
    "details": [
      {"query": "上一轮问题", "answer": "上一轮回答", "summary": "上一轮摘要"}
    ],
    "summary": {"content": "会话级摘要"}
  },
  "entities": [
    {
      "entity_id": "series_65",
      "entity_type": "series",
      "series_id": "65",
      "series_name": "宝马5系",
      "display_name": "宝马5系",
      "specs": []
    }
  ],
  "session_id": "optional-session-id",
  "user_id": "optional-user-id"
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

## Skills

系统 prompt 中的 Skill 目录由 `agent_service/prompt_loader.py` 动态生成：

- 每个 Skill 在 `SKILL.md` front matter 中声明 `name`、`type`、`description`、`version`
- `type: entrypoint` 表示可被用户问题直接命中的入口 Skill
- `type: internal` 表示只供入口 Skill 内部加载，不作为用户意图入口
- 新增 Skill 时通常只需要新增对应目录和 `SKILL.md`，无需修改 `config.py` 的系统 prompt

### car-compare-router（汽车对比入口路由）
当用户明确表达汽车对比意图时触发，先识别实体再路由：
1. 实体识别 → 获取 entities
2. 路由判断 → 2 个实体走双车对比流程，2 个以上实体走多车对比流程
3. 数据采集 → 按子流程调用可用工具
4. 输出结果 → 双车为 Markdown 结论 + 卡片占位符，多车当前为 Markdown

### select-car-recommend（泛选车推荐）
当用户没有固定候选车、希望按预算/能源/级别/用途/偏好筛选或推荐车型时触发：
1. 约束抽取 → 识别预算、能源、级别、座位数、用途、偏好维度等
2. 候选发现 → 通过可用工具获取候选车
3. 证据补充 → 按用户关注点调用参数、销量、口碑、保值、优惠、实测等原子工具
4. 输出结果 → 当前版本输出 Markdown 推荐列表，不输出双车对比卡片占位符

### single-car-query（单车查询）
当用户围绕一个明确汽车对象提问时触发，对象可以是车系、车型、配置版本、年款或上下文已指代的单一候选：
1. 对象确认 → 使用预置 entities 或 `vehicle_entity_recognition` 确认单一汽车对象
2. 子意图识别 → 区分综合评价、参数、价格、销量、榜单名次、口碑、版本推荐、竞品等
3. 证据补充 → 按子意图调用可用原子工具
4. 输出结果 → 当前版本输出 Markdown，不输出双车对比卡片占位符

## 技术栈

- **Agent Framework**: AgentScope 2.0.2
- **Deployment Runtime**: agentscope-runtime 1.1.6
- **Web Framework**: FastAPI (via AgentApp)
- **LLM**: DashScope (Qwen) / OpenAI / DeepSeek
