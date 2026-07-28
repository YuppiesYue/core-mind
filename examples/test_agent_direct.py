"""
直接测试 Agent（不经过 HTTP 服务），验证：
1. MCP 连接正常
2. LLM 调用正常
3. 工具执行正常（PermissionMode.BYPASS 生效）
4. reply_stream 事件流正常

用法:
    python test_agent_direct.py                          # 默认查询
    python test_agent_direct.py "比亚迪汉EV最新价格"      # 自定义查询
"""
import asyncio
import sys
import os
import logging

# 加载 .env
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("test_agent")


async def main():
    try:
        from .config import AppConfig
        from .agent_factory import build_agent
    except ImportError:
        from config import AppConfig
        from agent_factory import build_agent

    # 1. 构建 Agent
    cfg = AppConfig.from_env()
    logger.info(f"LLM: {cfg.llm_provider} / {cfg.llm_model}")
    logger.info(f"Base URL: {cfg.llm_base_url}")

    agent = await build_agent(cfg)

    # 2. 打印工具列表
    try:
        schemas = await agent.toolkit.get_tool_schemas()
    except TypeError:
        schemas = agent.toolkit.get_tool_schemas()
    logger.info(f"✅ {len(schemas)} tools registered")

    # 3. 验证权限模式
    from agentscope.permission import PermissionMode
    mode = agent.state.permission_context.mode
    logger.info(f"🔐 Permission mode: {mode}")
    assert mode == PermissionMode.BYPASS, f"Expected BYPASS, got {mode}"
    logger.info("✅ Permission mode is BYPASS (correct!)")

    # 4. 发送测试查询
    from agentscope.message import Msg, TextBlock
    query = sys.argv[1] if len(sys.argv) > 1 else "宝马3系和奔驰C级哪个性价比高"
    logger.info(f"💬 Query: {query}")

    user_msg = Msg(
        name="user",
        content=[TextBlock(type="text", text=query)],
        role="user",
    )

    # 5. 消费 reply_stream 事件
    text_parts = []
    tool_calls = []
    tool_results = []
    thinking_parts = []
    event_count = 0

    print("\n" + "=" * 60)
    print("🔄 Streaming events...")
    print("=" * 60 + "\n")

    try:
        async for event in agent.reply_stream(user_msg):
            event_count += 1
            etype = type(event).__name__

            # 文本增量
            if etype == "TextBlockDeltaEvent":
                delta = getattr(event, "delta", "")
                text_parts.append(delta)
                print(delta, end="", flush=True)

            # 思考增量
            elif etype == "ThinkingBlockDeltaEvent":
                delta = getattr(event, "delta", "")
                thinking_parts.append(delta)

            # 工具调用开始
            elif etype == "ToolCallStartEvent":
                name = getattr(event, "tool_call_name", "unknown")
                print(f"\n🔧 Calling: {name}", flush=True)
                tool_calls.append(name)

            # 工具结果文本
            elif etype == "ToolResultTextDeltaEvent":
                delta = getattr(event, "delta", "")
                if delta:
                    tool_results.append(delta[:200])

            # 工具结果结束
            elif etype == "ToolResultEndEvent":
                state = getattr(event, "state", "unknown")
                print(f"   ↳ Result state: {state}", flush=True)

            # 需要用户确认（BYPASS 模式下不应出现）
            elif etype == "RequireUserConfirmEvent":
                print(f"\n⚠️  RequireUserConfirmEvent received! BYPASS not working!", flush=True)

            # 超过最大迭代
            elif etype == "ExceedMaxItersEvent":
                print(f"\n⚠️  Exceeded max iterations!", flush=True)

            # 回复结束
            elif etype == "ReplyEndEvent":
                print(f"\n\n✅ Reply ended", flush=True)

            # 其他事件
            elif etype not in (
                "ReplyStartEvent", "TextBlockStartEvent", "TextBlockEndEvent",
                "ModelCallStartEvent", "ModelCallEndEvent",
                "ThinkingBlockStartEvent", "ThinkingBlockEndEvent",
                "ToolCallDeltaEvent", "ToolCallEndEvent",
                "ToolResultStartEvent",
            ):
                logger.debug(f"Unhandled event: {etype}")

    except Exception as e:
        print(f"\n\n❌ Error: {type(e).__name__}: {e}", flush=True)
        import traceback
        traceback.print_exc()

    # 6. 汇总
    full_text = "".join(text_parts)
    thinking_text = "".join(thinking_parts)

    print("\n" + "=" * 60)
    print("📊 Summary")
    print("=" * 60)
    print(f"  Events total : {event_count}")
    print(f"  Text length  : {len(full_text)} chars")
    print(f"  Tool calls   : {len(tool_calls)}")
    if tool_calls:
        for i, t in enumerate(tool_calls, 1):
            print(f"    {i}. {t}")
    if thinking_text:
        print(f"  Thinking     : {len(thinking_text)} chars")
    if tool_results:
        print(f"  Tool results : {len(tool_results)} chunks")
    print()

    if full_text:
        print("📝 Response:")
        print("-" * 60)
        print(full_text[:2000])
        if len(full_text) > 2000:
            print(f"... (truncated, total {len(full_text)} chars)")
        print()


if __name__ == "__main__":
    asyncio.run(main())
