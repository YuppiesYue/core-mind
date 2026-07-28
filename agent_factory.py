"""
Auto Car Agent Service - Agent 工厂
负责创建配置好本地工具 + Skill 的 Agent 实例
"""
import logging
from agentscope.agent import Agent, ReActConfig
from agentscope.agent._config import ContextConfig
from agentscope.state import AgentState
from agentscope.permission import PermissionContext, PermissionMode
from agentscope.tool import Toolkit
try:
    from .config import AppConfig
    from .local_tool_loader import load_skill_local_tools
    from .model_factory import create_model
    from .prompt_loader import build_runtime_system_prompt
except ImportError:
    from config import AppConfig
    from local_tool_loader import load_skill_local_tools
    from model_factory import create_model
    from prompt_loader import build_runtime_system_prompt

logger = logging.getLogger(__name__)


def create_agent(cfg: AppConfig) -> Agent:
    """创建汽车顾问 Agent

    Args:
        cfg: 应用配置

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

    # 创建 Toolkit，注册本地工具和 Skill 目录
    toolkit = Toolkit(
        tools=local_tools or None,
        skills_or_loaders=cfg.skill_dirs,
    )

    # 设置权限模式为 BYPASS，自动允许所有工具调用
    # 服务端场景无法交互确认，默认 ASK 模式会导致工具调用等待外部确认。
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
    """完整的 Agent 构建流程：创建 Agent"""
    logger.info("🔧 Building Auto Car Agent...")

    agent = create_agent(cfg)
    logger.info(f"✅ Agent [{cfg.agent_name}] built successfully.")

    return agent
