"""Compatibility entrypoint for running the agent service directly.

The FastAPI/AgentApp application is defined in :mod:`agent_service.app`.
Keep this module thin so ``python main.py`` works from this directory, and
``python -m agent_service.main`` works from the parent directory.
"""

try:
    from .app import agent_app
    from .config import AppConfig
except ImportError:
    from app import agent_app
    from config import AppConfig


if __name__ == "__main__":
    import uvicorn

    cfg = AppConfig.from_env()
    uvicorn.run(
        agent_app,
        host=cfg.host,
        port=cfg.port,
        log_level="info",
    )
