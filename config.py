"""
Auto Car Agent Service - 配置管理
从环境变量读取配置，支持默认值。
"""
import os
from pathlib import Path
from dataclasses import dataclass, field

try:
    from .prompt_loader import load_agent_system_prompt
except ImportError:
    from prompt_loader import load_agent_system_prompt

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CAR_DATA_MCP_URL = "http://auto-car-agent.autohome.com.cn/data/mcp"
DEFAULT_CAR_CARD_MCP_URL = "http://auto-car-agent.autohome.com.cn/card/mcp"


def _default_skill_dirs() -> list[str]:
    """Return project skill directories that directly contain SKILL.md."""
    skills_root = PROJECT_ROOT / "skills"
    if not skills_root.exists():
        return []
    return [
        str(path.parent)
        for path in sorted(skills_root.rglob("SKILL.md"))
    ]


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


# 自动加载 .env 文件（如果存在）
try:
    from dotenv import load_dotenv
    _env_path = PROJECT_ROOT / ".env"
    if _env_path.exists():
        load_dotenv(_env_path, override=True)
except ImportError:
    pass


@dataclass
class MCPConfig:
    """单个 MCP 服务的配置

    支持两种传输模式：
    - stdio:  通过子进程 stdin/stdout 通信，不占端口（本地开发推荐）
    - http:   通过 HTTP 通信，需要独立部署 MCP server（生产环境推荐）
    """
    name: str
    url: str = ""                                    # http 模式用
    transport: str = "http"                         # "stdio" 或 "http"
    command: str = ""                                # stdio 模式用：启动命令
    args: list = field(default_factory=list)         # stdio 模式用：命令参数
    cwd: str = ""                                    # stdio 模式用：工作目录
    headers: dict = field(default_factory=dict)      # http 模式用
    timeout: float = 30.0                            # http 模式用
    execution_timeout: float = 300.0                  # 工具执行超时（秒），stdio/http 通用
    stateful: bool = True
@dataclass
class AppConfig:
    """应用全局配置"""

    # --- 服务配置 ---
    host: str = "0.0.0.0"
    port: int = 8000
    app_name: str = "Auto Car Agent"
    app_description: str = "基于 AgentScope 2.0 的汽车智能顾问 Agent 服务"

    # --- LLM 配置 ---
    llm_provider: str = "openai"           # dashscope / openai / deepseek
    llm_model: str = "qwen-max"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_stream: bool = True
    llm_enable_thinking: bool = True  # 是否开启模型 think（推理）模式
    llm_context_size: int = 131072

    # --- Agent 配置 ---
    agent_name: str = "芝士车管家"
    agent_system_prompt: str = field(default_factory=load_agent_system_prompt)
    agent_max_iters: int = 20

    # --- AgentScope 会话记忆配置 ---
    enable_session_memory: bool = False

    # --- MCP 服务列表 ---
    # 默认使用 http 模式（stateful），MCP server 需独立启动
    # stateful 模式下客户端建立持久 session，所有工具调用复用同一 session
    # 支持并发工具调用，与原始 auto_car_agent_service 保持一致
    # 可通过 MCP_TRANSPORT=stdio 切换为 stdio 模式（本地开发，不占端口）
    mcp_servers: list = field(default_factory=lambda: [
        MCPConfig(
            name="auto-car-data-mcp",
            transport="http",
            url=DEFAULT_CAR_DATA_MCP_URL,
        ),
        MCPConfig(
            name="auto-car-card-mcp",
            transport="http",
            url=DEFAULT_CAR_CARD_MCP_URL,
        ),
    ])
    # --- Skill 配置 ---
    skill_dirs: list = field(default_factory=_default_skill_dirs)

    @classmethod
    def from_env(cls) -> "AppConfig":
        """从环境变量构建配置，未设置的字段使用默认值"""
        cfg = cls()

        cfg.host = os.getenv("APP_HOST", cfg.host)
        cfg.port = int(os.getenv("APP_PORT", str(cfg.port)))

        cfg.llm_provider = os.getenv("LLM_PROVIDER", cfg.llm_provider)
        cfg.llm_model = os.getenv("LLM_MODEL", cfg.llm_model)
        cfg.llm_api_key = os.getenv("LLM_API_KEY", cfg.llm_api_key)
        cfg.llm_base_url = os.getenv("LLM_BASE_URL", cfg.llm_base_url)
        cfg.llm_stream = os.getenv("LLM_STREAM", "true").lower() == "true"
        cfg.llm_enable_thinking = os.getenv("LLM_ENABLE_THINKING", "true").lower() == "true"
        cfg.llm_context_size = int(os.getenv("LLM_CONTEXT_SIZE", str(cfg.llm_context_size)))

        cfg.agent_name = os.getenv("AGENT_NAME", cfg.agent_name)
        cfg.agent_max_iters = int(os.getenv("AGENT_MAX_ITERS", str(cfg.agent_max_iters)))
        cfg.enable_session_memory = _env_bool("AGENT_ENABLE_SESSION_MEMORY", cfg.enable_session_memory)

        # MCP 传输模式：http（默认）或 stdio
        mcp_transport = os.getenv("MCP_TRANSPORT", "http").strip().lower()
        mcp_stateful = os.getenv("MCP_STATEFUL", "true").lower() == "true"

        # stdio 模式下可自定义 python 命令路径
        mcp_python = os.getenv("MCP_PYTHON", "python").strip()

        # http 模式下可自定义 MCP server URL
        data_mcp_url = os.getenv("CAR_DATA_MCP_URL", DEFAULT_CAR_DATA_MCP_URL).strip()
        card_mcp_url = os.getenv("CAR_CARD_MCP_URL", DEFAULT_CAR_CARD_MCP_URL).strip()

        for mcp in cfg.mcp_servers:
            mcp.transport = mcp_transport
            mcp.stateful = mcp_stateful
            if mcp_transport == "stdio":
                mcp.command = mcp_python
            elif mcp_transport == "http":
                if mcp.name == "auto-car-data-mcp":
                    mcp.url = data_mcp_url or DEFAULT_CAR_DATA_MCP_URL
                elif mcp.name == "auto-car-card-mcp":
                    mcp.url = card_mcp_url or DEFAULT_CAR_CARD_MCP_URL

        return cfg
