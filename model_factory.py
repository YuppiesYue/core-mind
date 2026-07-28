"""
Auto Car Agent Service - LLM 模型工厂
根据配置创建对应的 ChatModel 和 Formatter
"""
from agentscope.model import (
    DashScopeChatModel,
    OpenAIChatModel,
    DeepSeekChatModel,
)
from agentscope.formatter import (
    DashScopeChatFormatter,
    OpenAIChatFormatter,
)
from agentscope.credential import (
    DashScopeCredential,
    OpenAICredential,
    DeepSeekCredential,
)
try:
    from .config import AppConfig
except ImportError:
    from config import AppConfig


def _thinking_disabled_extra_body() -> dict:
    return {
        "enable_thinking": False,
        "safety": {"input_level": "none"},
        "thinking": {"type": "disabled"},
    }


def create_model(cfg: AppConfig):
    """根据配置创建 LLM ChatModel 实例

    Returns:
        (model, formatter) 元组
    """
    provider = cfg.llm_provider.lower()

    if provider == "dashscope":
        credential = DashScopeCredential(api_key=cfg.llm_api_key)
        formatter = DashScopeChatFormatter()
        parameters = DashScopeChatModel.Parameters(
            thinking_enable=cfg.llm_enable_thinking,
        )
        model = DashScopeChatModel(
            credential=credential,
            model=cfg.llm_model,
            parameters=parameters,
            stream=cfg.llm_stream,
            context_size=cfg.llm_context_size,
            formatter=formatter,
        )
        return model, formatter

    elif provider == "openai":
        cred_kwargs = {"api_key": cfg.llm_api_key}
        if cfg.llm_base_url:
            cred_kwargs["base_url"] = cfg.llm_base_url
        credential = OpenAICredential(**cred_kwargs)
        formatter = OpenAIChatFormatter()
        extra_body = {}
        extra_body['reasoning_effort'] = "low"
        if not cfg.llm_enable_thinking:
            extra_body.update(_thinking_disabled_extra_body())
        model = OpenAIChatModel(
            credential=credential,
            model=cfg.llm_model,
            stream=cfg.llm_stream,
            context_size=cfg.llm_context_size,
            formatter=formatter,
            extra_body=extra_body if extra_body else None,
        )
        return model, formatter

    elif provider == "deepseek":
        cred_kwargs = {"api_key": cfg.llm_api_key}
        if cfg.llm_base_url:
            cred_kwargs["base_url"] = cfg.llm_base_url
        credential = DeepSeekCredential(**cred_kwargs)
        formatter = OpenAIChatFormatter()  # DeepSeek 兼容 OpenAI 格式
        parameters = DeepSeekChatModel.Parameters(
            thinking_enable=cfg.llm_enable_thinking,
        )
        model = DeepSeekChatModel(
            credential=credential,
            model=cfg.llm_model,
            parameters=parameters,
            stream=cfg.llm_stream,
            context_size=cfg.llm_context_size,
            formatter=formatter,
        )
        return model, formatter

    else:
        raise ValueError(
            f"Unsupported LLM provider: {provider}. "
            f"Supported: dashscope, openai, deepseek"
        )
