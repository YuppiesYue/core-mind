"""
Auto Car Agent Service - Agent 工厂
负责创建配置好 MCP 工具 + Skill 的 Agent 实例
"""
import logging
import os

from agentscope.agent import Agent, ReActConfig
from agentscope.agent._config import ContextConfig
from agentscope.state import AgentState
from agentscope.permission import PermissionContext, PermissionMode
from agentscope.tool import Toolkit
from agentscope.mcp import MCPClient, HttpMCPConfig, StdioMCPConfig

try:
    from .config import AppConfig, MCPConfig
    from .local_tool_loader import load_skill_local_tools
    from .model_factory import create_model
    from .prompt_loader import build_runtime_system_prompt
except ImportError:
    from config import AppConfig, MCPConfig
    from local_tool_loader import load_skill_local_tools
    from model_factory import create_model
    from prompt_loader import build_runtime_system_prompt

logger = logging.getLogger(__name__)


async def create_mcp_clients(mcp_configs: list[MCPConfig]) -> list[MCPClient]:
    """创建并连接所有 MCP 客户端"""
    clients = []
    for mc in mcp_configs:
        if mc.transport == "stdio":
            mcp_config = StdioMCPConfig(
                command=mc.command,
                args=mc.args or [],
                cwd=mc.cwd or None,
                env={"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
                encoding_error_handler="replace",
            )
        else:
            mcp_config = HttpMCPConfig(
                url=mc.url,
                headers=mc.headers if mc.headers else None,
                timeout=mc.timeout,
            )
        client = MCPClient(
            name=mc.name,
            mcp_config=mcp_config,
            is_stateful=mc.stateful,
        )
        try:
            await client.connect()
            tools = await client.list_tools()
            logger.info(
                f"✅ MCP [{mc.name}] connected: {len(tools)} tools available"
            )
            clients.append(client)
        except Exception as e:
            if mc.stateful:
                logger.warning(
                    f"⚠️  MCP [{mc.name}] stateful connection failed: {e}; "
                    "falling back to stateless mode"
                )
                fallback_client = MCPClient(
                    name=mc.name,
                    mcp_config=mcp_config,
                    is_stateful=False,
                )
                try:
                    tools = await fallback_client.list_tools()
                    logger.info(
                        f"✅ MCP [{mc.name}] connected in stateless mode: "
                        f"{len(tools)} tools available"
                    )
                    clients.append(fallback_client)
                    continue
                except Exception as fallback_error:
                    logger.error(
                        f"❌ MCP [{mc.name}] stateless fallback failed: "
                        f"{fallback_error}"
                    )
            else:
                logger.error(f"❌ MCP [{mc.name}] connection failed: {e}")
            # 不阻塞启动，跳过失败的 MCP
    return clients


async def close_mcp_clients(agent: Agent) -> None:
    """Close stateful MCP clients owned by the agent toolkit."""
    toolkit = getattr(agent, "toolkit", None)
    for group in getattr(toolkit, "tool_groups", []) or []:
        for client in getattr(group, "mcps", []) or []:
            if client.is_stateful and client.is_connected:
                try:
                    await client.close()
                except BaseException as exc:
                    logger.warning(
                        f"⚠️  MCP [{client.name}] close ignored: {exc}"
                    )


def create_agent(cfg: AppConfig, mcp_clients: list[MCPClient]) -> Agent:
    """创建汽车顾问 Agent

    Args:
        cfg: 应用配置
        mcp_clients: 已连接的 MCP 客户端列表

    Returns:
        配置好的 Agent 实例
    """
    model, formatter = create_model(cfg)
    base_prompt = str(cfg.agent_system_prompt or "")
    prompt = build_runtime_system_prompt(base_prompt)
    logger.info(
        "🧾 Config system prompt length: chars=%d lines=%d",
        len(prompt),
        prompt.count("\n") + 1 if prompt else 0,
    )

    local_tools = load_skill_local_tools(cfg.skill_dirs)
    if local_tools:
        logger.info("🔧 Local skill tools loaded: %d", len(local_tools))

    # 创建 Toolkit，注册所有 MCP 客户端和 Skill 目录
    toolkit = Toolkit(
        mcps=mcp_clients,
        tools=local_tools or None,
        skills_or_loaders=cfg.skill_dirs,
    )

    # 设置权限模式为 BYPASS，自动允许所有工具调用
    # 默认 DEFAULT 模式下每个 MCP 工具调用都需要用户确认（ASK），
    # 服务端场景无法交互确认，会导致：
    # "Agent is waiting for N tool calls ... but received no event"
    state = AgentState(
        permission_context=PermissionContext(
            mode=PermissionMode.BYPASS,
        ),
    )

    agent = Agent(
        name=cfg.agent_name,
        system_prompt=prompt,
        model=model,
        toolkit=toolkit,
        state=state,
        react_config=ReActConfig(max_iters=cfg.agent_max_iters),
        context_config=ContextConfig(tool_result_limit=5000),
    )
    # Request-scoped agents refresh only the time context.
    agent._auto_car_base_system_prompt = base_prompt
    final_prompt = str(getattr(agent, "_system_prompt", "") or "")
    logger.info(
        "🧾 Final Agent system prompt length: chars=%d lines=%d",
        len(final_prompt),
        final_prompt.count("\n") + 1 if final_prompt else 0,
    )
    if final_prompt:
        logger.info("🧾 Final Agent system prompt preview:\n%s", final_prompt)

    return agent


async def build_agent(cfg: AppConfig) -> Agent:
    """完整的 Agent 构建流程：连接 MCP → 创建 Agent"""
    logger.info("🔧 Building Auto Car Agent...")

    # 1. 连接 MCP 服务
    mcp_clients = await create_mcp_clients(cfg.mcp_servers)
    if not mcp_clients:
        logger.warning(
            "⚠️  No MCP servers connected! "
            "Agent will have limited capabilities."
        )

    # 2. 创建 Agent
    agent = create_agent(cfg, mcp_clients)
    logger.info(f"✅ Agent [{cfg.agent_name}] built successfully.")

    return agent
