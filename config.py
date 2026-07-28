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
    agent_name: str = "智能助手"
    agent_system_prompt: str = field(default_factory=load_agent_system_prompt)
    agent_max_iters: int = 20

    # --- AgentScope 会话记忆配置 ---
    enable_session_memory: bool = True

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

        return cfg
