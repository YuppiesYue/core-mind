"""
Auto Agent Service - 主入口
基于 AgentScope 2.0 + agentscope-runtime 的智能顾问 FastAPI 服务

启动方式:
    # 当前目录 python app.py

    # 或者从上一级目录 D:/projects/agent
    python -m agent_service.app

    # 或者设置环境变量
    LLM_API_KEY=sk-xxx LLM_MODEL=qwen-max python app.py

API 端点:
    POST /chat        - 自定义 SSE 协议（think/response/card 阶段流）
    POST /process     - 主处理端点（agentscope-runtime 标准 SSE）
    GET  /health      - 健康检查
    GET  /tools       - 列出可用工具
    GET  /agent-info  - Agent 信息
"""
import asyncio
import os
import json
import logging
import time
import base64
import uuid
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from agentscope.agent import Agent
from agentscope.message import Msg, TextBlock
from agentscope.state import AgentState
from agentscope_runtime.engine import AgentApp
from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest

try:
    from .config import AppConfig
    from .agent_factory import build_agent
    from .prompt_loader import build_runtime_system_prompt
    from .stream_parser import StreamCardParser, sse_event, _card_fingerprint
    from .tool_display_name_resolver import ToolDisplayNameResolver
except ImportError:
    from config import AppConfig
    from agent_factory import build_agent
    from prompt_loader import build_runtime_system_prompt
    from stream_parser import StreamCardParser, sse_event, _card_fingerprint
    from tool_display_name_resolver import ToolDisplayNameResolver

# ──────────────────────────────────────────────
# 日志
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("auto_car_agent")


# ──────────────────────────────────────────────
# 全局状态
# ──────────────────────────────────────────────
_agent: Agent | None = None
_config: AppConfig | None = None
_session_memory_states: dict[str, AgentState] = {}
_session_memory_locks: dict[str, asyncio.Lock] = {}
_tool_display_names = ToolDisplayNameResolver()
_MALFORMED_CARD_SUFFIX_RE = re.compile(
    r"(?<![\w{]):(?P<tag>[A-Za-z][A-Za-z0-9_-]*)\}\}",
)
_FINAL_END_TAG = "</final>"


def _strip_final_end_tags(delta: str, buffered_suffix: str = "") -> tuple[str, str]:
    """Remove ``</final>`` while retaining a possible split tag suffix."""
    text = (buffered_suffix or "") + (delta or "")
    cleaned = text.replace(_FINAL_END_TAG, "")
    max_suffix_len = min(len(cleaned), len(_FINAL_END_TAG) - 1)
    for suffix_len in range(max_suffix_len, 0, -1):
        suffix = cleaned[-suffix_len:]
        if _FINAL_END_TAG.startswith(suffix):
            return cleaned[:-suffix_len], suffix
    return cleaned, ""

# ──────────────────────────────────────────────
# Lazy init: 首次请求时构建 Agent
# ──────────────────────────────────────────────
_agent_lock = asyncio.Lock()


async def _ensure_agent() -> None:
    """首次请求时延迟构建 Agent（lazy init）。

    首次请求时才构建 Agent，避免启动阶段提前加载模型和工具。
    """
    global _agent, _config
    if _agent is not None:
        return
    async with _agent_lock:
        if _agent is not None:
            return
        if _config is None:
            _config = AppConfig.from_env()
        logger.info("🔧 Building Core Mind Agent (lazy init)...")
        _agent = await build_agent(_config)
        if _agent.toolkit:
            try:
                schemas = await _agent.toolkit.get_tool_schemas()
            except TypeError:
                schemas = _agent.toolkit.get_tool_schemas()
            _tool_display_names.update_tool_names_from_schemas(schemas)
            logger.info(f"📦 Registered tools: {len(schemas)}")
        try:
            skill_instructions = await _agent.toolkit.get_skill_instructions()
        except TypeError:
            skill_instructions = _agent.toolkit.get_skill_instructions()
        await _tool_display_names.refresh_skill_info(_agent.toolkit)
        if skill_instructions:
            logger.info("📚 Skills loaded")
        logger.info("✅ Agent built successfully (lazy init)")


# ──────────────────────────────────────────────
# Lifespan: 管理服务生命周期
# ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """服务启动时初始化 Agent，关闭时清理资源"""
    global _agent, _config

    logger.info("🚀 Core Mind Agent Service starting...")
    _config = AppConfig.from_env()

    if not _config.llm_api_key:
        logger.warning(
            "⚠️  LLM_API_KEY not set! "
            "Set via environment variable. Agent will fail on LLM calls."
        )

    # 构建 Agent（加载本地工具 + Skill）
    _agent = await build_agent(_config)

    # 打印已注册的工具
    if _agent.toolkit:
        try:
            schemas = await _agent.toolkit.get_tool_schemas()
        except TypeError:
            schemas = _agent.toolkit.get_tool_schemas()
        _tool_display_names.update_tool_names_from_schemas(schemas)
        logger.info(f"📦 Registered tools: {len(schemas)}")
        for s in schemas:
            name = s.get("function", {}).get("name", "unknown")
            logger.info(f"   - {name}")

    # Skill 指令
    try:
        skill_instructions = await _agent.toolkit.get_skill_instructions()
    except TypeError:
        skill_instructions = _agent.toolkit.get_skill_instructions()
    await _tool_display_names.refresh_skill_info(_agent.toolkit if _agent else None)
    if skill_instructions:
        logger.info("📚 Skills loaded:")
        logger.info(f"   {skill_instructions[:200]}...")

    logger.info(f"✅ Service ready at http://{_config.host}:{_config.port}")
    yield  # ──── Service is running ────
    logger.info("👋 Core Mind Agent Service shutting down...")


# ──────────────────────────────────────────────
# AgentApp 实例
# ──────────────────────────────────────────────
agent_app = AgentApp(
    app_name="Core Mind Agent",
    app_description="基于 AgentScope 2.0 的智能顾问 Agent 服务，支持BBA买车等",
    endpoint_path="/process",
    response_type="sse",
    stream=True,
    lifespan=lifespan,
)

# ──────────────────────────────────────────────
# 主查询处理逻辑（默认 /process 端点）
# ──────────────────────────────────────────────
@agent_app.query(framework="agentscope")
async def query_func(
    self,
    msgs,
    request: AgentRequest = None,
    **kwargs,
):
    """处理用户查询 — agentscope-runtime 标准格式"""
    global _agent

    if _agent is None:
        await _ensure_agent()

    if isinstance(msgs, list):
        user_msg = msgs[-1] if msgs else None
    else:
        user_msg = msgs

    logger.info(f"📨 Query received: {user_msg}")

    # 每次请求使用独立 AgentState，避免并发请求互相污染上下文。
    request_state = _create_fresh_agent_state()
    request_agent = _create_request_agent(request_state)
    request_agent.state.context.clear()
    request_agent.state.summary = ""

    text_parts: list[str] = []
    block_msg: Msg | None = None
    last_msg: Msg | None = None

    def _new_block_msg() -> Msg:
        m = Msg(name=request_agent.name, content=[{"type": "text", "text": ""}], role="assistant")
        m.content = [{"type": "text", "text": ""}]
        return m

    async for event in request_agent.reply_stream(user_msg):
        et = type(event).__name__

        if et == "TextBlockDeltaEvent":
            delta = getattr(event, "delta", "")
            if delta:
                if not text_parts:
                    block_msg = _new_block_msg()
                text_parts.append(delta)
                accumulated = "".join(text_parts)
                block_msg.content = [{"type": "text", "text": accumulated}]
                yield block_msg, False
                last_msg = block_msg

        elif et == "TextBlockEndEvent":
            text_parts = []
            block_msg = None

        elif et == "ReplyEndEvent":
            if text_parts:
                accumulated = "".join(text_parts)
                if block_msg is None:
                    block_msg = _new_block_msg()
                block_msg.content = [{"type": "text", "text": accumulated}]
                last_msg = block_msg
                text_parts = []
            if last_msg:
                yield last_msg, True
            return

    if text_parts:
        accumulated = "".join(text_parts)
        if block_msg is None:
            block_msg = _new_block_msg()
        block_msg.content = [{"type": "text", "text": accumulated}]
        last_msg = block_msg
    if last_msg:
        yield last_msg, True


# ══════════════════════════════════════════════════════════════
# 卡片占位符系统 — 工具返回时存储卡片，LLM 输出占位符时替换输出
# ══════════════════════════════════════════════════════════════

# ── 卡片工具识别 ──
# 工具名关键词仅用于历史兼容；真正判断以工具返回结构为准。
CARD_TOOL_KEYWORDS = (
    "fill_card",           # fill_card_bottom_pk, fill_card_feedback, ...
    "fetch_and_fill_card", # fetch_and_fill_card_bottom_pk, ...
)

CARD_DIV_PLACEHOLDER_RE = re.compile(
    r'<div\b[^>]*\bdata-card\s*=\s*(?P<quote>["\'])(?P<tag>[^"\']+)(?P=quote)[^>]*>'
    r'\s*</div\s*>',
    re.IGNORECASE,
)


def _is_card_tool(tool_name: str) -> bool:
    """判断工具名是否为卡片工具"""
    for kw in CARD_TOOL_KEYWORDS:
        if kw in tool_name:
            return True
    return False


def _first_body_value(body: dict, *keys: str) -> str:
    for key in keys:
        value = body.get(key)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return ""


def _normalize_request_meta_fields(body: dict) -> dict:
    """Accept both snake_case and camelCase request metadata fields."""
    if not isinstance(body, dict):
        return body

    field_pairs = (
        ("session_id", "sessionId"),
        ("user_id", "userId"),
        ("device_id", "deviceId"),
        ("req_id", "reqId"),
    )
    for snake_key, camel_key in field_pairs:
        value = _first_body_value(body, snake_key, camel_key)
        if not value:
            continue
        body.setdefault(snake_key, value)
        body.setdefault(camel_key, value)
    return body


def _session_memory_key(body: dict) -> tuple[str, bool]:
    user_id = _first_body_value(body, "user_id", "userId")
    session_id = _first_body_value(body, "session_id", "sessionId")
    generated = False
    if not user_id:
        user_id = "anonymous"
        generated = True
    if not session_id:
        session_id = uuid.uuid4().hex
        generated = True
    body.setdefault("user_id", user_id)
    body.setdefault("userId", user_id)
    body.setdefault("session_id", session_id)
    body.setdefault("sessionId", session_id)
    return f"{user_id}:{session_id}", generated


def _get_or_create_session_state(memory_key: str) -> AgentState:
    if memory_key in _session_memory_states:
        return _session_memory_states[memory_key]

    permission_context = _agent.state.permission_context.model_copy(deep=True)
    state = AgentState(
        session_id=memory_key,
        permission_context=permission_context,
    )
    _session_memory_states[memory_key] = state
    return state


def _get_session_memory_lock(memory_key: str) -> asyncio.Lock:
    lock = _session_memory_locks.get(memory_key)
    if lock is None:
        lock = asyncio.Lock()
        _session_memory_locks[memory_key] = lock
    return lock


def _create_request_agent(state: AgentState) -> Agent:
    """Create a per-request Agent that shares immutable runtime dependencies.

    AgentScope Agent stores conversation context on ``agent.state``. Reusing the
    global agent directly would make concurrent requests overwrite each other's
    state, so each request gets a fresh Agent wrapper with its own state while
    sharing model/toolkit configuration from the initialized base agent.
    """
    if _agent is None:
        raise RuntimeError("Agent not initialized")

    base_prompt = getattr(_agent, "_auto_car_base_system_prompt", None)
    if not isinstance(base_prompt, str):
        base_prompt = str(getattr(_agent, "_system_prompt", "") or "")

    return Agent(
        name=_agent.name,
        system_prompt=build_runtime_system_prompt(base_prompt),
        model=_agent.model,
        toolkit=_agent.toolkit,
        state=state,
        offloader=_agent.offloader,
        model_config=_agent.model_config,
        context_config=_agent.context_config,
        react_config=_agent.react_config,
    )


def _create_fresh_agent_state() -> AgentState:
    if _agent is None:
        raise RuntimeError("Agent not initialized")
    return AgentState(
        permission_context=_agent.state.permission_context.model_copy(deep=True),
    )


def _remove_ephemeral_context(state: AgentState, ephemeral_msgs: list[Msg]) -> None:
    if not ephemeral_msgs:
        return
    ephemeral_ids = {id(msg) for msg in ephemeral_msgs}
    state.context = [msg for msg in state.context if id(msg) not in ephemeral_ids]


def _json_loads_maybe(value) -> object | None:
    """Parse JSON if value is a JSON-looking string."""
    if not isinstance(value, str):
        return value

    text = value.strip()
    if not text:
        return None

    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except (json.JSONDecodeError, TypeError):
            return None

    return None


def _extract_text_from_content_block(block: dict) -> object | None:
    """Return the most likely payload from a tool content block."""
    for key in ("text", "json", "data", "value", "content", "msg"):
        if key in block:
            return block[key]
    return None


def _build_card_msg(card_type: str, card_data: dict, source: dict | None = None) -> dict:
    """Build the canonical card msg while keeping legacy fields compatible."""
    source = source or {}
    card_key = str(source.get("card_key", source.get("cardKey", "")) or "").strip()
    card_msg = {
        "cardData": card_data,
        "cardId": source.get("cardId", source.get("card_id", 7)),
        "cardIntent": str(source.get("cardIntent", source.get("card_intent", "")) or ""),
        "cardName": str(source.get("cardName", source.get("card_name", "")) or ""),
        "cardType": card_type,
        "contentType": str(source.get("contentType", source.get("content_type", "json")) or "json"),
        "displayType": str(source.get("displayType", source.get("display_type", "form")) or "form"),
        "playLoad": source.get("playLoad", source.get("payload", "")) or "",
        # Legacy fields for clients still reading the old protocol.
        "card_type": card_type,
        "card_data": card_data,
    }
    if card_key:
        card_msg["card_key"] = card_key
    return card_msg


def _find_card_in_obj(obj) -> tuple[str, dict, dict] | None:
    """Recursively find a card payload in old or wrapped MCP result formats."""
    obj = _json_loads_maybe(obj)

    if isinstance(obj, list):
        for item in obj:
            found = _find_card_in_obj(item)
            if found:
                return found
        return None

    if not isinstance(obj, dict):
        return None

    card_source = dict(obj)
    card_block = card_source.get("card")
    if isinstance(card_block, dict):
        merged_source = dict(card_source)
        merged_source.update(card_block)
        card_source = merged_source

    card_type = (
        card_source.get("card_type")
        or card_source.get("cardType")
        or card_source.get("type")
    )
    card_data = (
        card_source.get("card_data")
        if "card_data" in card_source
        else card_source.get("cardData")
    )
    if card_data is None and isinstance(card_block, dict):
        card_data = (
            card_block.get("card_data")
            if "card_data" in card_block
            else card_block.get("cardData")
        )
        if card_data is None and (
            obj.get("card_type") or obj.get("cardType")
        ):
            # 统一协议 {card_type, card} 中，card 可直接作为卡片数据，
            # 不要求再额外嵌套一层 cardData。
            card_data = card_block

    if isinstance(card_type, str) and card_type.strip() and card_data is not None:
        if isinstance(card_data, dict):
            return (card_type, card_data, _build_card_msg(card_type, card_data, card_source))
        parsed_card_data = _json_loads_maybe(card_data)
        if isinstance(parsed_card_data, dict):
            return (card_type, parsed_card_data, _build_card_msg(card_type, parsed_card_data, card_source))

    content = obj.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                payload = _extract_text_from_content_block(block)
                found = _find_card_in_obj(payload)
                if found:
                    return found
            else:
                found = _find_card_in_obj(block)
                if found:
                    return found

    # Newer MCP/tool wrappers may put structured payloads under one of these
    # keys. Keep this whitelist narrow enough to avoid walking arbitrary huge
    # card_data trees once a card has already been found.
    for key in (
        "structuredContent",
        "structured_content",
        "data",
        "result",
        "payload",
        "playLoad",
        "output",
        "metadata",
        "message",
        "msg",
    ):
        if key in obj:
            found = _find_card_in_obj(obj[key])
            if found:
                return found

    return None


def _extract_card_from_tool_result(result_text: str, result_data: list | None = None) -> tuple[str, dict, dict] | None:
    """从卡片工具的返回结果中提取 (card_type, card_data, card_msg)。

    兼容格式：
    - 旧格式：顶层 `{card_type, card_data}`
    - 旧格式变体：顶层 `{card_type, card}`
    - 新格式：`{stage: "card", content: [{type: "card", msg: {cardType, cardData}}]}`
    - MCP 包装：`{content: [{type: "text", text: "{...}"}]}`
    - 结构化包装：`structuredContent` / `data` / `result` 等字段中包含卡片
    - DataBlock：`application/json` data delta 中包含卡片 JSON
    """
    for payload in (result_text, *(result_data or [])):
        found = _find_card_in_obj(payload)
        if found:
            return found

    return None


def _decode_tool_data_payload(media_type: str, data: str | None, url: str | None):
    """Decode ToolResultDataDeltaEvent payloads that may contain JSON."""
    if data:
        try:
            decoded = base64.b64decode(data).decode("utf-8")
        except Exception:
            decoded = data
        parsed = _json_loads_maybe(decoded)
        return parsed if parsed is not None else decoded

    if url:
        return {"url": url, "media_type": media_type}

    return None


def _handle_text_with_placeholders(
    delta: str,
    parser: StreamCardParser,
    pending_cards: dict,
    placeholder_buf: str,
    emitted_card_tags: set[str],
) -> tuple:
    """处理文本增量：检测卡片占位符并替换为卡片。

    占位符匹配到时就地输出 card SSE，使卡片穿插在 response 文本中间。
    占位符前后的文本正常作为 response 输出。
    支持三种占位符：
    - {{card:car_series_compare_main_params_table}}
    - XML 风格兼容格式，例如 <card>car_series_compare_main_params_table</card>
    - 前端协议格式，例如 <div data-card="car_series_compare_main_params_table:1"></div>

    Args:
        delta: 文本增量
        parser: StreamCardParser 实例（处理 ```json``` 去重）
        pending_cards: 待输出的卡片
            {card_type: [{card_type, cardData/card_data, ...}, ...]}
        placeholder_buf: 上一轮残留文本（可能包含未完成的占位符）

    Returns:
        (sse_events: list[str], remaining_buf: str)
    """
    text = placeholder_buf + delta

    # 仅在本轮已生成该类型卡片时，修复被截断的 `:card_type}}` 占位符。
    def _recover_malformed_card_suffix(match: re.Match[str]) -> str:
        tag = match.group("tag")
        if tag not in pending_cards:
            return match.group(0)
        logger.warning(
            "🎴 [/chat] Recovered malformed card placeholder: %s",
            match.group(0),
        )
        return f"{{{{card:{tag}}}}}"

    text = _MALFORMED_CARD_SUFFIX_RE.sub(_recover_malformed_card_suffix, text)
    events = []
    search_start = 0

    # Debug: 当文本可能包含占位符时打日志
    if (
        "{{card:" in text
        or "{{" in text
        or "<card>" in text
        or "</card>" in text
        or "<div" in text
        or "data-card" in text
    ):
        logger.debug(
            f"🔍 [placeholder] buf={repr(placeholder_buf)} "
            f"delta={repr(delta)} text={repr(text)}"
        )

    while True:
        brace_pos = text.find("{{card:", search_start)
        angle_pos = text.find("<card>", search_start)
        div_match = CARD_DIV_PLACEHOLDER_RE.search(text, search_start)
        div_pos = div_match.start() if div_match else -1
        candidates = [pos for pos in (brace_pos, angle_pos, div_pos) if pos >= 0]
        if not candidates:
            break

        pos = min(candidates)
        is_brace = pos == brace_pos
        is_div = pos == div_pos

        if is_brace:
            close_pos = text.find("}}", pos + 7)
            tag_start = pos + 7
            tag_end = close_pos
            placeholder_end = close_pos + 2 if close_pos >= 0 else -1
        elif is_div:
            tag = div_match.group("tag").strip()
            close_pos = div_match.end()
            tag_start = tag_end = -1
            placeholder_end = close_pos
        else:
            close_pos = text.find("</card>", pos + len("<card>"))
            tag_start = pos + len("<card>")
            tag_end = close_pos
            placeholder_end = close_pos + len("</card>") if close_pos >= 0 else -1

        if close_pos < 0:
            # 占位符不完整，保留从占位符开始的文本给下一轮
            logger.debug(
                f"🔍 [placeholder] Incomplete at pos={pos}, "
                f"text={repr(text)}, will buffer"
            )
            break

        if not is_div:
            tag = text[tag_start:tag_end].strip()
        before = text[search_start:pos]
        logger.debug(
            f"🔍 [placeholder] Found tag={repr(tag)} "
            f"at pos={pos}, close_pos={close_pos}"
        )

        # 将占位符前的文本喂给 parser
        if before:
            for sse_str in parser.feed(before):
                events.append(sse_str)
            for sse_str in parser.flush():
                events.append(sse_str)

        # `{{card:type:key}}` 精确匹配同类型卡片池中的 card_key。未带 key 的
        # 占位符继续按队列顺序消费。旧 data-card="type:1" 若找不到 key，
        # 仍按历史“展示序号”语义回退为无 key 匹配。
        card_type = tag
        requested_card_key = ""
        if tag.count(":") == 1:
            possible_type, possible_key = tag.split(":", 1)
            if possible_type and possible_key:
                card_type = possible_type
                requested_card_key = possible_key

        card_queue = pending_cards.get(card_type)
        card_info = None
        matched_by_key = False
        if isinstance(card_queue, list):
            if requested_card_key:
                for index, candidate in enumerate(card_queue):
                    candidate_key = str(candidate.get("card_key", "") or "").strip()
                    if candidate_key == requested_card_key:
                        card_info = card_queue.pop(index)
                        matched_by_key = True
                        break

            if card_info is None and not requested_card_key:
                card_info = card_queue.pop(0) if card_queue else None

            # 仅旧 data-card 协议将数字后缀视为展示序号；大括号/XML
            # 格式携带 card_key 时必须精确匹配，避免错误展示其它同类卡片。
            if card_info is None and is_div and requested_card_key.isdigit():
                card_info = card_queue.pop(0) if card_queue else None

            if not card_queue:
                pending_cards.pop(card_type, None)
        elif isinstance(card_queue, dict):
            candidate_key = str(card_queue.get("card_key", "") or "").strip()
            if not requested_card_key or candidate_key == requested_card_key:
                # 兼容仍以单张卡片字典调用该函数的历史调用方。
                card_info = pending_cards.pop(card_type, None)
                matched_by_key = bool(requested_card_key)
            elif is_div and requested_card_key.isdigit():
                # 兼容 data-card="type:1" 的展示序号。
                card_info = pending_cards.pop(card_type, None)

        emitted_tag = (
            f"{card_type}:{requested_card_key}"
            if matched_by_key
            else card_type
        )

        if card_info is not None:
            emitted_card_tags.add(emitted_tag)
            events.append(sse_event({
                "stage": "card",
                "content": [{"type": "card", "msg": card_info}],
            }))
            logger.info(
                "🎴 [/chat] Card emitted via placeholder: "
                f"placeholder={tag}, card_type={card_type}, "
                f"card_key={requested_card_key if matched_by_key else ''}"
            )
        else:
            # 未匹配的占位符不直接透给用户，避免裸露 {{card:...}}。
            # 正常情况下，模型应在对应卡片工具成功后再输出占位符。
            if emitted_tag in emitted_card_tags:
                logger.info(
                    f"🎴 [/chat] Duplicate placeholder skipped after card emitted: {tag}"
                )
            else:
                logger.warning(
                    f"🎴 [/chat] Placeholder skipped, no card stored: {tag}; "
                    f"pending={list(pending_cards.keys())}"
                )

        search_start = placeholder_end

    # 保留所有已知占位符前缀，避免跨 delta 时将半截 HTML 输出到 response。
    remaining = text[search_start:]
    safe_len = max(0, len(remaining) - 64)
    partial_positions = (
        remaining.rfind("{{"),
        remaining.rfind("<card"),
        remaining.rfind("<div"),
        remaining.rfind("data-card"),
    )
    partial_positions = [pos for pos in partial_positions if pos >= 0]
    if partial_positions:
        safe_len = min(safe_len, min(partial_positions))
    if safe_len > 0:
        safe = remaining[:safe_len]
        for sse_str in parser.feed(safe):
            events.append(sse_str)
        remaining = remaining[safe_len:]

    if remaining:
        logger.debug(
            f"🔍 [placeholder] remaining={repr(remaining)} "
            f"(len={len(remaining)})"
        )

    return events, remaining


# ══════════════════════════════════════════════════════════════
# 自定义 /chat 端点 — 自定义 SSE 协议
# ══════════════════════════════════════════════════════════════
@agent_app.post("/chat")
async def chat_endpoint(request: Request):
    """
    自定义 SSE 流式端点 — 输出 stage: think / response / card 格式

    请求体（新版）:
        {
            "final_query": "改写后的用户问题（含完整车系信息）",
            "query": "用户原始问题",
            "memory": {
                "details": [
                    {"query": "...", "answer": "...", "summary": "..."},
                    ...
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
                },
                {
                    "entity_id": "series_18",
                    "entity_type": "series",
                    "series_id": "18",
                    "series_name": "奥迪A6L",
                    "display_name": "奥迪A6L",
                    "specs": []
                }
            ],
            "long_term_memory": {
                "mainFacts": [
                    {"memory": "...", "factTypeName": "..."},
                    ...
                ]
            }
        }

    请求体（兼容旧版）:
        {
            "messages": [{"role": "user", "content": "你好"}],
            "stream": true
        }

    SSE 输出:
        data: {"stage": "think",    "content": [{"type": "text", "msg": "..."}]}
        data: {"stage": "response", "content": [{"type": "text", "msg": "..."}]}
        data: {"stage": "card",     "content": [{"type": "card", "msg": {...}}]}
        data: [DONE]
    """
    global _agent

    request_received_at = time.perf_counter()
    if _agent is None:
        await _ensure_agent()
    if not _tool_display_names.has_tool_names:
        await _tool_display_names.refresh_tool_names(_agent.toolkit if _agent else None)
    if not _tool_display_names.has_skill_info:
        await _tool_display_names.refresh_skill_info(_agent.toolkit if _agent else None)

    # 解析请求体
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid JSON body"},
        )
    body = _normalize_request_meta_fields(body)

    # ── 提取用户消息和记忆信息 ──
    final_query = body.get("final_query", "")
    query = body.get("query", "")
    memory = body.get("memory", {})
    long_term_memory = body.get("long_term_memory", {})
    entities = body.get("entities", [])

    # 优先使用 final_query（外部已做 query rewriting，补全了车系信息）
    # 兼容旧的 messages 格式
    content = final_query or query
    if not content:
        messages = body.get("messages", [])
        if not messages:
            messages = body.get("input", [])
        if messages:
            last_msg_data = messages[-1]
            content = last_msg_data.get("content", "")
            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict):
                        text_parts.append(block.get("text", block.get("msg", "")))
                    else:
                        text_parts.append(str(block))
                content = "\n".join(text_parts)

    if not content:
        return JSONResponse(
            status_code=400,
            content={"error": "No query provided (need final_query, query, or messages)"},
        )

    cfg = _config or AppConfig.from_env()
    session_memory_enabled = bool(cfg.enable_session_memory)
    session_memory_key = ""
    generated_session_memory_key = False
    if session_memory_enabled:
        session_memory_key, generated_session_memory_key = _session_memory_key(body)
    session_memory_active = bool(session_memory_enabled and session_memory_key)
    log_req_id = _first_body_value(body, "req_id", "reqId")
    log_session_id = _first_body_value(body, "session_id", "sessionId")
    log_user_id = _first_body_value(body, "user_id", "userId")
    MAX_HISTORY_ROUNDS = 3

    session_lock: asyncio.Lock | None = None
    session_lock_released = True
    if session_memory_active:
        session_lock = _get_session_memory_lock(session_memory_key)
        await session_lock.acquire()
        session_lock_released = False

    def _release_session_lock() -> None:
        nonlocal session_lock_released
        if session_lock is not None and not session_lock_released:
            session_lock.release()
            session_lock_released = True

    request_state: AgentState | None = None
    request_agent: Agent | None = None
    ephemeral_msgs: list[Msg] = []

    try:
        if session_memory_active:
            request_state = _get_or_create_session_state(session_memory_key)
            logger.info(
                "🧠 [/chat] AgentScope 会话记忆已启用 key=%s generated=%s context_msgs=%d summary=%s",
                session_memory_key,
                generated_session_memory_key,
                len(request_state.context),
                bool(request_state.summary),
            )
        else:
            request_state = _create_fresh_agent_state()
            request_state.context.clear()
            request_state.summary = ""

        request_agent = _create_request_agent(request_state)
        existing_context_msgs = len(request_state.context)

        # ── 注入最近 3 轮外部历史对话 ──
        # AgentScope 会话记忆关闭：每轮按外部 memory 注入。
        # AgentScope 会话记忆开启：仅在该 session 首次出现且状态为空时，用外部 memory 初始化一次。
        history_msgs = []
        should_inject_external_history = (not session_memory_active) or (
            session_memory_active and existing_context_msgs == 0
        )
        if should_inject_external_history:
            details = memory.get("details", []) if memory else []
            valid_details = []
            for detail in reversed(details):
                q = detail.get("query", "")
                a = detail.get("answer", "")
                s = detail.get("summary", "")
                if not q or not (a or s):
                    continue
                valid_details.append(detail)
                if len(valid_details) >= MAX_HISTORY_ROUNDS:
                    break

            for detail in reversed(valid_details):
                q = detail.get("query", "")
                response_text = detail.get("summary") or detail.get("answer", "")
                history_msgs.append(
                    Msg(name="user", content=[TextBlock(text=q)], role="user")
                )
                history_msgs.append(
                    Msg(name="assistant", content=[TextBlock(text=response_text)], role="assistant")
                )

            for msg in history_msgs:
                request_state.context.append(msg)
            if session_memory_active and history_msgs:
                logger.info(
                    "🧠 [/chat] 外部 memory 已初始化到 AgentScope 会话 key=%s rounds=%d",
                    session_memory_key,
                    len(history_msgs) // 2,
                )

        if history_msgs or (session_memory_active and existing_context_msgs > 0):
            current_turn_constraint = (
                "【当前轮回答约束】\n"
                f"当前用户问题是本轮唯一要回答的问题：{content}\n"
                "历史对话只用于补充省略指代和偏好背景。\n"
                "如果当前问题出现新的车型/车名/车系，明确与历史对话无关时，"
                "不得沿用历史里的推荐任务、预算、车型集合或上一轮结论。"
            )
            constraint_msg = Msg(
                name="system",
                content=[TextBlock(text=current_turn_constraint)],
                role="system",
            )
            request_state.context.append(constraint_msg)
            ephemeral_msgs.append(constraint_msg)

        # ── 注入预置 entities（跳过实体识别调用） ──
        if isinstance(entities, list) and entities:
            valid_entities = [item for item in entities if isinstance(item, dict)]
            if valid_entities:
                hint = (
                    "【预置 entities】\n"
                    "外部系统已完成实体识别，entities 如下：\n"
                    + json.dumps(valid_entities, ensure_ascii=False)
                    + "\n\n请直接使用以上原始 entities，"
                    "跳过 vehicle_entity_recognition 调用；如果命中汽车对比 Skill，"
                    "必须按 entities 数量在 Skill 内部路由：2 个实体走双车卡片流程，"
                    "超过 2 个实体走多车 Markdown 流程。"
                )
                hint_msg = Msg(name="system", content=[TextBlock(text=hint)], role="system")
                request_state.context.append(hint_msg)
                ephemeral_msgs.append(hint_msg)
                logger.info(
                    "📌 [/chat] 预置 entities: count=%d names=%s",
                    len(valid_entities),
                    ", ".join(
                        str(
                            item.get("display_name")
                            or item.get("group_name")
                            or item.get("spec_name")
                            or item.get("series_name")
                            or item.get("name")
                            or ""
                        )
                        for item in valid_entities
                    ),
                )

        # ── 注入长期记忆（用户偏好 + 场景） ──
        memory_prefix = ""
        if long_term_memory:
            parts = []
            for fact in long_term_memory.get("mainFacts", []):
                fact_type = fact.get("factTypeName", "")
                memory_text = fact.get("memory", "")
                if fact_type and memory_text:
                    parts.append(f"[{fact_type}] {memory_text}")
            
            if parts:
                memory_prefix = "【用户偏好】\n" + "\n".join(parts) + "\n\n"

        # ── 构造当前用户消息 ──
        user_content = memory_prefix + content if memory_prefix else content
        user_msg = Msg(name="user", content=[TextBlock(text=user_content)], role="user")
        
        logger.info(
            "📨 [/chat] Query: %s... (external_history=%d rounds, session_memory=%s)",
            content[:100],
            len(history_msgs) // 2,
            session_memory_active,
        )
        logger.info(
            "⏱️ [/chat] request prepared req_id=%s elapsed=%.3fs "
            "history_rounds=%d entities=%d",
            log_req_id,
            time.perf_counter() - request_received_at,
            len(history_msgs) // 2,
            len(entities) if isinstance(entities, list) else 0,
        )
    except Exception:
        _release_session_lock()
        raise

    async def _event_generator_unlocked():
        """生成自定义 SSE 事件流

        卡片输出流程（占位符模式）:
          1. 卡片工具返回 → 解析 JSON → 存入 pending_cards[tag]
          2. LLM 文本中输出 {{card:tag}} → 检测占位符 → 从 pending_cards 取出 → 就地输出 card SSE
          3. LLM 漏掉占位符 → 不输出该卡片，只记录日志

        自定义 SSE 协议 stage 列表:
          - think         : LLM 思考过程（流式）
          - response      : LLM 回复文本（流式，占位符被替换为卡片）
          - card          : 卡片 JSON（整块，仅由占位符触发）
          - tool_call     : 工具调用（工具名 + 参数）
          - tool_response : 工具返回结果摘要；卡片工具不透出完整 JSON
        """
        # ── 去重集合（StreamCardParser 和占位符系统共享） ──
        emitted_card_keys: set[str] = set()
        parser = StreamCardParser(emitted_card_keys=emitted_card_keys)

        # ── 待输出卡片（工具返回时存储，占位符匹配时按生成顺序取出） ──
        # card_type → canonical card msg queue
        pending_cards: dict[str, list[dict]] = {}
        emitted_card_tags: set[str] = set()

        # ── 占位符缓冲区（跨 chunk 拼接不完整的 {{card:...}}） ──
        placeholder_buf: str = ""

        # ── 最终回答协议标签（跨 chunk 检测） ──
        # 主路径：模型输出 <final> 后，后续文本立即作为 response 流式输出。
        # 兜底：如果整轮都没有 <final>，仍走原 text_buf_events 缓冲逻辑。
        FINAL_TAG = "<final>"
        final_tag_buf: str = ""
        final_end_tag_buf: str = ""

        # ── 标志位：response 文本开始后，后续 think 事件标记为 think_delta ──
        response_started: bool = False
        final_response_mode: bool = False

        # ── 文本 stage 决策缓冲 ──
        # 多轮 agent 循环中，LLM 每轮产生的规划文本（"数据到手，拉取参数表格——"）
        # 不应作为 response 输出，而应作为 think_delta。
        # 但流式输出时无法预知 TextBlock 后面是 ToolCall（中间态）还是 ReplyEnd（最终回复），
        # 所以先缓冲文本，等下一个非文本事件到来时再决定 stage。
        # - ToolCallStartEvent → 缓冲文本是中间态规划 → flush 为 think_delta
        # - ReplyEndEvent → 缓冲文本是最终回复 → flush 为 response
        text_buf_events: list[str] = []   # 缓冲的 SSE 事件字符串（stage 待改写）
        text_buf_raw: str = ""            # 缓冲的原始文本（用于日志）

        def _flush_text_buf(target_stage: str):
            """将缓冲区文本以指定 stage flush 出去。

            缓冲的 SSE 事件原本 stage 是 "response"，
            如果 target_stage 不是 "response"（比如 "think_delta"），
            需要改写 stage 字段。
            """
            nonlocal text_buf_events, text_buf_raw, response_started
            if not text_buf_events:
                return

            if target_stage == "response":
                response_started = True

            logger.info(
                f"📝 [/chat] Flushing text buffer as {target_stage} "
                f"({len(text_buf_events)} events, {len(text_buf_raw)} chars)"
            )

            for sse_str in text_buf_events:
                if target_stage == "response":
                    # 原始 SSE 已经是 response stage，直接 yield
                    yield sse_str
                else:
                    # 需要改写 stage（think_delta）
                    try:
                        # SSE 格式: "data: {json}\n\n"
                        prefix = "data: "
                        if sse_str.startswith(prefix):
                            json_str = sse_str[len(prefix):].rstrip("\n")
                            obj = json.loads(json_str)
                            obj["stage"] = target_stage
                            yield f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"
                        else:
                            yield sse_str  # 非标准格式，原样输出
                    except (json.JSONDecodeError, KeyError):
                        yield sse_str

            text_buf_events.clear()
            text_buf_raw = ""

        def _is_card_sse(sse_str: str) -> bool:
            return '"stage": "card"' in sse_str or '"stage":"card"' in sse_str

        def _feed_text_to_response_parser(text: str) -> list[str]:
            """Feed confirmed final response text into placeholder/card parser."""
            nonlocal placeholder_buf
            if not text:
                return []
            events, placeholder_buf = _handle_text_with_placeholders(
                text, parser, pending_cards, placeholder_buf, emitted_card_tags,
            )
            return events

        def _feed_text_to_fallback_buffer(text: str) -> list[str]:
            """Feed pre-final text into the legacy stage-decision buffer."""
            return _feed_text_to_response_parser(text)

        def _split_by_final_tag(delta: str) -> tuple[str, str, bool]:
            """Split incoming text by <final>, preserving a short suffix.

            Returns:
                (fallback_text, final_text_after_tag, found_final_tag)
            """
            nonlocal final_tag_buf
            text = final_tag_buf + delta
            tag_pos = text.find(FINAL_TAG)
            if tag_pos >= 0:
                fallback_text = text[:tag_pos]
                final_text = text[tag_pos + len(FINAL_TAG):]
                final_tag_buf = ""
                return fallback_text, final_text, True

            keep = len(FINAL_TAG) - 1
            safe_len = max(0, len(text) - keep)
            fallback_text = text[:safe_len]
            final_tag_buf = text[safe_len:]
            return fallback_text, "", False

        def _drain_final_tag_buf_to_fallback() -> list[str]:
            """Flush text held only for possible <final> detection."""
            nonlocal final_tag_buf, text_buf_raw
            if not final_tag_buf:
                return []
            text = final_tag_buf
            final_tag_buf = ""
            text_buf_raw += text
            return _feed_text_to_fallback_buffer(text)

        def _feed_final_response_text(delta: str) -> list[str]:
            """Stream final response text after <final> until ReplyEnd."""
            nonlocal final_end_tag_buf
            visible_text, final_end_tag_buf = _strip_final_end_tags(
                delta,
                final_end_tag_buf,
            )
            return _feed_text_to_response_parser(visible_text)

        def _drain_final_response_tail() -> list[str]:
            """Flush final response tail buffers at TextBlockEnd/ReplyEnd."""
            nonlocal final_end_tag_buf
            # A remaining suffix is necessarily a partial ``</final>`` marker.
            # Drop it instead of exposing protocol text to the user.
            final_end_tag_buf = ""
            return _drain_text_tail_events()

        def _drain_text_tail_events() -> list[str]:
            """Flush placeholder and parser tail buffers into response SSE events."""
            nonlocal placeholder_buf
            events: list[str] = []

            if placeholder_buf:
                parsed_events, placeholder_buf = _handle_text_with_placeholders(
                    "",
                    parser,
                    pending_cards,
                    placeholder_buf,
                    emitted_card_tags,
                )
                events.extend(parsed_events)
                if placeholder_buf:
                    for sse_str in parser.feed(placeholder_buf):
                        events.append(sse_str)
                placeholder_buf = ""

            for sse_str in parser.flush():
                events.append(sse_str)

            return events

        # ── 工具调用状态跟踪 ──
        # tool_call_id → {"name": str, "args": str, "result": str, "data": list}
        tool_states: dict[str, dict] = {}
        stream_started_at = time.perf_counter()
        reply_stream_entered_at: float | None = None
        model_call_started_at: float | None = None
        first_token_at: float | None = None
        first_event_logged = False
        first_token_logged = False
        first_tool_call_logged = False

        # ── 原始 response 输出日志 ──
        # 只记录最终 response 原文，包含 <final> 标签和未替换成真实卡片前的占位符。
        raw_response_parts: list[str] = []

        # 工具结果最大字符数（超过截断，避免 SSE 爆炸）
        MAX_RESULT_LEN = 2000
        logger.info(
            "⏱️ [/chat] stream generator entered req_id=%s elapsed=%.3fs",
            log_req_id,
            stream_started_at - request_received_at,
        )
        reply_stream_entered_at = time.perf_counter()
        async for event in request_agent.reply_stream(user_msg):
            et = type(event).__name__
            now = time.perf_counter()
            if not first_event_logged:
                first_event_logged = True
                logger.info(
                    "⏱️ [/chat] first agent event req_id=%s event=%s "
                    "since_request=%.3fs since_stream=%.3fs",
                    log_req_id,
                    et,
                    now - request_received_at,
                    now - stream_started_at,
                )

            if et == "ModelCallStartEvent":
                model_call_started_at = now
                logger.info(
                    "⏱️ [/chat] model call start req_id=%s "
                    "since_request=%.3fs since_reply_stream=%.3fs",
                    log_req_id,
                    now - request_received_at,
                    now - (reply_stream_entered_at or stream_started_at),
                )
                continue

            if et == "ModelCallEndEvent":
                duration = (
                    now - model_call_started_at
                    if model_call_started_at is not None
                    else -1.0
                )
                logger.info(
                    "⏱️ [/chat] model call end req_id=%s duration=%.3fs "
                    "since_request=%.3fs",
                    log_req_id,
                    duration,
                    now - request_received_at,
                )
                continue

            # ════════════ 思考阶段 ════════════

            if et == "ThinkingBlockDeltaEvent":
                delta = getattr(event, "delta", "")
                if delta:
                    if not first_token_logged:
                        first_token_logged = True
                        first_token_at = now
                        logger.info(
                            "⏱️ [/chat] first token req_id=%s event=%s "
                            "since_request=%.3fs since_model_start=%.3fs",
                            log_req_id,
                            et,
                            now - request_received_at,
                            (
                                now - model_call_started_at
                                if model_call_started_at is not None
                                else -1.0
                            ),
                        )
                    stage = "think" if not response_started else "think_delta"
                    yield sse_event({
                        "stage": stage,
                        "content": [{"type": "text", "msg": delta}],
                    })

            elif et == "ThinkingBlockEndEvent":
                pass  # 思考结束

            # ════════════ 文本回复阶段（含占位符检测） ════════════

            elif et == "TextBlockDeltaEvent":
                delta = getattr(event, "delta", "")
                if delta:
                    if not first_token_logged:
                        first_token_logged = True
                        first_token_at = now
                        logger.info(
                            "⏱️ [/chat] first token req_id=%s event=%s "
                            "since_request=%.3fs since_model_start=%.3fs",
                            log_req_id,
                            et,
                            now - request_received_at,
                            (
                                now - model_call_started_at
                                if model_call_started_at is not None
                                else -1.0
                            ),
                        )
                    if final_response_mode:
                        raw_response_parts.append(delta)
                        for sse_str in _feed_final_response_text(delta):
                            yield sse_str
                    else:
                        fallback_text, final_text, found_final_tag = _split_by_final_tag(delta)

                        if found_final_tag:
                            if fallback_text.strip() or text_buf_raw.strip() or text_buf_events:
                                logger.info(
                                    "📝 [/chat] <final> detected; discarding "
                                    "pre-final text buffer (%d events, %d chars, "
                                    "current_prefix=%d chars)",
                                    len(text_buf_events),
                                    len(text_buf_raw),
                                    len(fallback_text),
                                )

                            # Drop any pre-final text/parser tail so planning text
                            # cannot leak into response once the explicit protocol
                            # marker has been honored.
                            text_buf_events.clear()
                            text_buf_raw = ""
                            placeholder_buf = ""
                            parser = StreamCardParser(emitted_card_keys=emitted_card_keys)
                            final_response_mode = True
                            response_started = True
                            raw_response_parts.clear()
                            raw_response_parts.append(FINAL_TAG + final_text)
                            logger.info(
                                "📝 [/chat] <final> detected; final response "
                                "streaming enabled req_id=%s session_id=%s user_id=%s",
                                log_req_id,
                                log_session_id,
                                log_user_id,
                            )

                            for sse_str in _feed_final_response_text(final_text):
                                yield sse_str
                        elif fallback_text:
                            # Legacy fallback path: keep buffering text until a
                            # later ToolCallStartEvent or ReplyEndEvent decides
                            # whether this was planning text or final response.
                            events = _feed_text_to_fallback_buffer(fallback_text)
                            text_buf_raw += fallback_text

                            # Backward-compatible shortcut: old prompts may
                            # place card placeholders without <final>. Preserve
                            # the previous behavior and stream once a card is
                            # emitted.
                            if any(_is_card_sse(s) for s in events):
                                final_response_mode = True
                                response_started = True
                                raw_response_parts.clear()
                                raw_response_parts.append(text_buf_raw)
                                for sse_str in text_buf_events:
                                    yield sse_str
                                text_buf_events.clear()
                                text_buf_raw = ""
                                for sse_str in events:
                                    yield sse_str
                            else:
                                text_buf_events.extend(events)

            elif et == "TextBlockEndEvent":
                if not final_response_mode:
                    text_buf_events.extend(_drain_final_tag_buf_to_fallback())

                # parser 残余刷入缓冲区（不立即 yield，除非已进入 final 模式）
                flushed_events = (
                    _drain_final_response_tail()
                    if final_response_mode
                    else _drain_text_tail_events()
                )
                if final_response_mode:
                    for sse_str in flushed_events:
                        yield sse_str
                else:
                    text_buf_events.extend(flushed_events)

            # ════════════ 工具调用阶段 ════════════

            elif et == "ToolCallStartEvent":
                if final_response_mode:
                    logger.warning(
                        "📝 [/chat] Tool call requested after <final>; "
                        "model violated final-response protocol "
                        "req_id=%s session_id=%s user_id=%s tool=%s",
                        log_req_id,
                        log_session_id,
                        log_user_id,
                        getattr(event, "tool_call_name", "unknown"),
                    )
                else:
                    text_buf_events.extend(_drain_final_tag_buf_to_fallback())

                # 缓冲文本是中间态规划文本 → flush 为 think_delta
                for sse_str in _flush_text_buf("think_delta"):
                    yield sse_str

                tc_id = getattr(event, "tool_call_id", "")
                tc_name = getattr(event, "tool_call_name", "unknown")
                if not first_tool_call_logged:
                    first_tool_call_logged = True
                    logger.info(
                        "⏱️ [/chat] first tool call req_id=%s tool=%s "
                        "since_request=%.3fs since_first_token=%.3fs",
                        log_req_id,
                        tc_name,
                        now - request_received_at,
                        (
                            now - first_token_at
                            if first_token_at is not None
                            else -1.0
                        ),
                    )
                tc_name_cn = _tool_display_names.tool_name_cn(tc_name)
                tool_states[tc_id] = {
                    "name": tc_name,
                    "name_cn": tc_name_cn,
                    "args": "",
                    "result": "",
                    "data": [],
                    "started_at": time.perf_counter(),
                    "result_started_at": None,
                }
                logger.info(f"🔧 [/chat] Tool call start: {tc_name}")
                yield sse_event({
                    "stage": "tool_call",
                    "content": [{
                        "type": "text",
                        "msg": f"正在调用 {tc_name}",
                        "tool_name": tc_name,
                        "tool_name_cn": tc_name_cn,
                        "status": "calling",
                    }],
                })

            elif et == "ToolCallDeltaEvent":
                tc_id = getattr(event, "tool_call_id", "")
                delta = getattr(event, "delta", "")
                if tc_id in tool_states and delta:
                    tool_states[tc_id]["args"] += delta

            elif et == "ToolCallEndEvent":
                tc_id = getattr(event, "tool_call_id", "")
                if tc_id in tool_states:
                    if _tool_display_names.is_skill_tool(tool_states[tc_id]["name"]):
                        skill_name = _tool_display_names.extract_skill_name_from_args(
                            tool_states[tc_id]["args"]
                        )
                        if skill_name:
                            tool_states[tc_id]["skill_name"] = skill_name
                    logger.info(
                        f"🔧 [/chat] Tool call args end: "
                        f"{tool_states[tc_id]['name']}"
                    )

            # ════════════ 工具结果阶段 ════════════

            elif et == "ToolResultStartEvent":
                tc_id = getattr(event, "tool_call_id", "")
                if tc_id in tool_states:
                    tool_states[tc_id]["result_started_at"] = time.perf_counter()
                    logger.info(
                        f"🔧 [/chat] Tool execution start: "
                        f"{tool_states[tc_id]['name']}"
                    )

            elif et == "ToolResultTextDeltaEvent":
                tc_id = getattr(event, "tool_call_id", "")
                delta = getattr(event, "delta", "")
                if tc_id in tool_states and delta:
                    tool_states[tc_id]["result"] += delta

            elif et == "ToolResultDataDeltaEvent":
                tc_id = getattr(event, "tool_call_id", "")
                if tc_id in tool_states:
                    payload = _decode_tool_data_payload(
                        getattr(event, "media_type", ""),
                        getattr(event, "data", None),
                        getattr(event, "url", None),
                    )
                    if payload is not None:
                        tool_states[tc_id]["data"].append(payload)

            elif et == "ToolResultEndEvent":
                tc_id = getattr(event, "tool_call_id", "")
                if tc_id not in tool_states:
                    continue

                tc_name = tool_states[tc_id]["name"]
                tc_name_cn = (
                    tool_states[tc_id].get("name_cn")
                    or _tool_display_names.tool_name_cn(tc_name)
                )
                skill_name = (
                    tool_states[tc_id].get("skill_name")
                    or _tool_display_names.extract_skill_name_from_args(
                        tool_states[tc_id]["args"]
                    )
                )
                skill_info = (
                    _tool_display_names.skill_info(skill_name)
                    if _tool_display_names.is_skill_tool(tc_name)
                    else {}
                )
                result_text = tool_states[tc_id]["result"]
                result_data = tool_states[tc_id].get("data", [])
                started_at = tool_states[tc_id].get("started_at")
                result_started_at = tool_states[tc_id].get("result_started_at")
                now = time.perf_counter()
                duration_ms = int((now - started_at) * 1000) if started_at else None
                execution_ms = (
                    int((now - result_started_at) * 1000)
                    if result_started_at
                    else None
                )
                card_info = _extract_card_from_tool_result(result_text, result_data)
                is_card_tool = _is_card_tool(tc_name) or card_info is not None
                is_skill_tool = _tool_display_names.is_skill_tool(tc_name)
                card_tool_status = ""

                # ── 卡片工具：提取卡片数据存入 pending_cards ──
                if card_info:
                    card_type, card_data, card_msg = card_info
                    tag = str(card_type or "").strip()
                    if tag:
                        fp = _card_fingerprint(card_msg)

                        if fp not in emitted_card_keys:
                            pending_cards.setdefault(tag, []).append(card_msg)
                            emitted_card_keys.add(fp)
                            logger.info(
                                f"🎴 [/chat] Card stored from tool: "
                                f"{tc_name} → tag={tag}, "
                                f"type={card_type}"
                            )
                            card_tool_status = f"卡片已生成，等待占位符输出：{tag}"
                        else:
                            logger.info(
                                f"🎴 [/chat] Card deduplicated: "
                                f"{tc_name} → tag={tag}"
                            )
                            card_tool_status = f"卡片已去重：{tag}"
                    else:
                        logger.warning(
                            f"🎴 [/chat] Unknown card_type: {card_type}"
                        )
                        card_tool_status = f"卡片类型未映射，已跳过：{card_type}"
                elif is_card_tool:
                    logger.warning(
                        f"🎴 [/chat] Failed to extract card from: "
                        f"{tc_name} (result len={len(result_text)})"
                    )
                    card_tool_status = "卡片工具已完成，但未解析到可展示卡片"

                # ── 输出工具结果摘要 ──
                if is_card_tool:
                    result_summary = card_tool_status or "卡片工具已完成"
                elif is_skill_tool:
                    result_summary = (
                        f"Skill 指令已加载：{skill_name}"
                        if skill_name
                        else "Skill 指令已加载"
                    )
                else:
                    result_summary = result_text[:MAX_RESULT_LEN]
                    if len(result_text) > MAX_RESULT_LEN:
                        result_summary += "..."

                logger.info(
                    f"🔧 [/chat] Tool execution end: {tc_name} "
                    f"duration_ms={duration_ms} execution_ms={execution_ms}"
                )

                content_item = {
                    "type": "text",
                    "msg": result_summary,
                    "tool_name": tc_name,
                    "tool_name_cn": tc_name_cn,
                    "status": "completed",
                    "duration_ms": duration_ms,
                    "execution_ms": execution_ms,
                }
                if skill_info:
                    content_item.update({
                        "skill_name": skill_info.get("skill_name", skill_name),
                        "skill_name_cn": skill_info.get("skill_name_cn", skill_name),
                    })

                yield sse_event({
                    "stage": "tool_response",
                    "content": [content_item],
                })

            # ════════════ 其他事件 ════════════

            elif et == "ReplyStartEvent":
                pass

            elif et == "ReplyEndEvent":
                if not final_response_mode:
                    text_buf_events.extend(_drain_final_tag_buf_to_fallback())

                # Some providers may close the reply without a TextBlockEndEvent.
                # Always drain the placeholder/parser tail before deciding stage.
                flushed_events = (
                    _drain_final_response_tail()
                    if final_response_mode
                    else _drain_text_tail_events()
                )
                if final_response_mode:
                    for sse_str in flushed_events:
                        yield sse_str
                else:
                    text_buf_events.extend(flushed_events)

                # ── 缓冲文本是最终回复 → flush 为 response ──
                if not final_response_mode:
                    raw_response_parts.clear()
                    raw_response_parts.append(text_buf_raw)
                    for sse_str in _flush_text_buf("response"):
                        yield sse_str

                if raw_response_parts:
                    raw_response_text = "".join(raw_response_parts)
                    logger.info(
                        "🧾 [/chat] Raw response before final-tag stripping/"
                        "card replacement req_id=%s session_id=%s user_id=%s "
                        "(%d chars):\n%s",
                        log_req_id,
                        log_session_id,
                        log_user_id,
                        len(raw_response_text),
                        raw_response_text,
                    )

                # ── 严格占位符模式：未被占位符匹配的卡片不自动输出 ──
                if pending_cards:
                    pending_card_count = sum(len(cards) for cards in pending_cards.values())
                    logger.warning(
                        f"🎴 [/chat] {pending_card_count} unmatched cards "
                        f"discarded at ReplyEnd: {list(pending_cards.keys())}"
                    )
                    pending_cards.clear()

            elif et == "ThinkingBlockStartEvent":
                pass  # 新一轮思考开始，response_started 保持不重置

            # 其他未处理的事件类型
            elif et not in (
                "ReplyStartEvent", "ModelCallStartEvent", "ModelCallEndEvent",
                "TextBlockStartEvent",
                "ToolResultStartEvent", "DataBlockStartEvent",
                "DataBlockDeltaEvent", "DataBlockEndEvent",
                "HintBlockEvent", "ExceedMaxItersEvent",
            ):
                logger.debug(f"🔍 [/chat] Unhandled event: {et}")

        yield "data: [DONE]\n\n"

    async def event_generator():
        try:
            async for item in _event_generator_unlocked():
                yield item
        finally:
            _remove_ephemeral_context(request_state, ephemeral_msgs)
            if session_memory_active:
                logger.info(
                    "🧠 [/chat] AgentScope 会话记忆已保存 key=%s context_msgs=%d summary=%s",
                    session_memory_key,
                    len(request_state.context),
                    bool(request_state.summary),
                )
            _release_session_lock()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ──────────────────────────────────────────────
# 健康检查 & 辅助端点
# ──────────────────────────────────────────────
@agent_app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "healthy",
        "agent": _agent.name if _agent else None,
    }


@agent_app.get("/tools")
async def list_tools():
    """列出所有可用工具"""
    if _agent is None or not _agent.toolkit:
        return {"tools": []}
    try:
        schemas = await _agent.toolkit.get_tool_schemas()
    except TypeError:
        schemas = _agent.toolkit.get_tool_schemas()
    return {"tools": schemas}


@agent_app.get("/agent-info")
async def agent_info():
    """Agent 信息"""
    if _agent is None:
        return JSONResponse(
            status_code=503,
            content={"error": "Agent not initialized"},
        )
    return {
        "name": _agent.name,
        "description": _config.agent_description if _config else "",
    }


# ──────────────────────────────────────────────
# 启动入口
# ──────────────────────────────────────────────
if __name__ == "__main__":
    """独立运行入口。

    两种方式：
        1. 从当前目录:     python app.py
        2. 从上一级目录:   python -m agent_service.app
        3. 兼容旧入口:     python main.py
    """
    import uvicorn
    import sys as _sys
    from pathlib import Path as _Path

    # 确保项目根目录在 sys.path 中（支持模块方式运行）
    _project_root = _Path(__file__).resolve().parent.parent
    if str(_project_root) not in _sys.path:
        _sys.path.insert(0, str(_project_root))

    cfg = AppConfig.from_env()
    uvicorn.run(
        agent_app,
        host=cfg.host,
        port=cfg.port,
        log_level="info",
    )
