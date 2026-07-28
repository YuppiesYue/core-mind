"""
Auto Car Agent Service - Demo Client
=====================================
直接调用 API 接口，实时展示 Agent 回复结果。

用法:
    python demo_client.py                                # 默认: 双车对比（走 /chat 自定义协议）
    python demo_client.py "比亚迪汉和特斯拉Model 3哪个好"   # 自定义问题
    python demo_client.py --health                       # 仅测试连通性
    python demo_client.py --tools                        # 查看可用工具
    python demo_client.py --info                         # 查看 Agent 信息
    python demo_client.py --legacy                       # 走旧 /process 端点
    python demo_client.py --base-url http://x.x.x.x:8000 # 指定服务地址

依赖:
    pip install httpx rich
"""
import sys
import json
import argparse
import time

import httpx

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.markdown import Markdown
    from rich.live import Live
    from rich.text import Text

    RICH = True
except ImportError:
    RICH = False


# ──────────────────────────────────────────────
# 颜色 / 样式 (无 rich 时的降级方案)
# ──────────────────────────────────────────────
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"
    RED = "\033[31m"
    MAGENTA = "\033[35m"


def cprint(text, color="", end="\n"):
    """带颜色的 print"""
    if color:
        print(f"{color}{text}{Colors.RESET}", end=end, flush=True)
    else:
        print(text, end=end, flush=True)


# ──────────────────────────────────────────────
# API 调用
# ──────────────────────────────────────────────
class DemoClient:
    def __init__(self, base_url: str = "http://localhost:8000", timeout: float = 180.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def health(self) -> dict:
        """GET /health"""
        resp = httpx.get(f"{self.base_url}/health", timeout=10)
        resp.raise_for_status()
        return resp.json()

    def tools(self) -> dict:
        """GET /tools"""
        resp = httpx.get(f"{self.base_url}/tools", timeout=10)
        resp.raise_for_status()
        return resp.json()

    def agent_info(self) -> dict:
        """GET /agent-info"""
        resp = httpx.get(f"{self.base_url}/agent-info", timeout=10)
        resp.raise_for_status()
        return resp.json()

    def chat_stream(self, query: str):
        """POST /chat — 自定义 SSE 协议（stage: think/response/card）"""
        payload = {
            "messages": [
                {"role": "user", "content": query}
            ],
            "stream": True,
        }

        with httpx.stream(
            "POST",
            f"{self.base_url}/agent/chat",
            json=payload,
            timeout=self.timeout,
        ) as response:
            response.raise_for_status()
            buffer = ""
            for chunk in response.iter_text():
                buffer += chunk
                # SSE 格式: 每个事件以 \n\n 分隔
                while "\n\n" in buffer:
                    event_str, buffer = buffer.split("\n\n", 1)
                    for line in event_str.strip().split("\n"):
                        if line.startswith("data: "):
                            data_str = line[6:]
                            try:
                                event = json.loads(data_str)
                                yield event
                            except json.JSONDecodeError:
                                pass

    def query_stream(self, query: str, session_id: str = None):
        """POST /process — agentscope-runtime 标准 SSE（旧端点）"""
        import uuid

        payload = {
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": query}],
                }
            ],
            "stream": True,
            "session_id": session_id or f"demo-{uuid.uuid4().hex[:8]}",
        }

        with httpx.stream(
            "POST",
            f"{self.base_url}/process",
            json=payload,
            timeout=self.timeout,
        ) as response:
            response.raise_for_status()
            buffer = ""
            for chunk in response.iter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    event_str, buffer = buffer.split("\n\n", 1)
                    for line in event_str.strip().split("\n"):
                        if line.startswith("data: "):
                            data_str = line[6:]
                            try:
                                event = json.loads(data_str)
                                yield event
                            except json.JSONDecodeError:
                                pass


# ──────────────────────────────────────────────
# 自定义协议展示（/chat 端点）
# ──────────────────────────────────────────────
def display_chat_stream(client: DemoClient, query: str, use_rich: bool = False):
    """展示 /chat 自定义 SSE 协议"""
    if use_rich and RICH:
        _display_chat_rich(client, query)
    else:
        _display_chat_plain(client, query)


def _display_chat_plain(client: DemoClient, query: str):
    """纯终端输出 — 自定义协议"""
    cprint(f"\n{'='*60}", Colors.DIM)
    cprint(f"💬 Query: {query}", Colors.BOLD)
    cprint(f"{'='*60}\n", Colors.DIM)

    t0 = time.time()
    think_text = ""
    response_text = ""
    card_count = 0
    tool_names = []
    stage_count = {"think": 0, "response": 0, "card": 0, "tool_call": 0, "tool_response": 0}

    for event in client.chat_stream(query):
        stage = event.get("stage", "")
        content = event.get("content", [])

        stage_count[stage] = stage_count.get(stage, 0) + 1

        if stage == "think":
            # 思考阶段
            for block in content:
                msg = block.get("msg", "")
                if msg:
                    think_text += msg
                    cprint(msg, Colors.MAGENTA, end="")

        elif stage == "response":
            # 响应文本阶段
            for block in content:
                msg = block.get("msg", "")
                if msg:
                    response_text += msg
                    cprint(msg, end="")

        elif stage == "card":
            # 卡片阶段（整块 JSON）
            card_count += 1
            for block in content:
                card_data = block.get("msg", {})
                cprint(f"\n{'─'*40}", Colors.YELLOW)
                cprint(f"🎴 Card #{card_count}:", Colors.YELLOW)
                cprint(f"{'─'*40}", Colors.YELLOW)
                pretty = json.dumps(card_data, indent=2, ensure_ascii=False)
                if len(pretty) > 800:
                    cprint(pretty[:800], Colors.CYAN)
                    cprint(f"\n  ... ({len(pretty) - 800} more chars)", Colors.DIM)
                else:
                    cprint(pretty, Colors.CYAN)
                cprint(f"{'─'*40}\n", Colors.YELLOW)

        elif stage == "tool_call":
            # 工具调用阶段
            for block in content:
                tool_name = block.get("tool_name", "unknown")
                status = block.get("status", "")
                msg = block.get("msg", "")
                if status == "calling":
                    cprint(f"\n🔧 Calling: {tool_name}", Colors.CYAN)
                    tool_names.append(tool_name)
                elif status == "called":
                    # 参数预览（截断）
                    args_preview = msg
                    if len(args_preview) > 120:
                        args_preview = args_preview[:120] + "..."
                    cprint(f"\n   ↳ args: {args_preview}", Colors.DIM)

        elif stage == "tool_response":
            # 工具返回阶段
            for block in content:
                tool_name = block.get("tool_name", "unknown")
                status = block.get("status", "success")
                msg = block.get("msg", "")
                result_preview = msg
                if len(result_preview) > 200:
                    result_preview = result_preview[:200] + "..."
                icon = "✅" if status == "success" else "❌"
                cprint(f"\n   {icon} {tool_name} → {status} ({len(msg)} chars)", Colors.GREEN if status == "success" else Colors.RED)
                if result_preview:
                    cprint(f"   ↳ {result_preview}", Colors.DIM)

    elapsed = time.time() - t0
    cprint(f"\n\n{'='*60}", Colors.DIM)
    cprint("📊 Summary", Colors.BOLD)
    cprint(f"{'='*60}", Colors.DIM)
    cprint(f"  Time         : {elapsed:.1f}s", Colors.BLUE)
    cprint(f"  Think events : {stage_count.get('think', 0)}", Colors.BLUE)
    cprint(f"  Response len : {len(response_text)} chars", Colors.BLUE)
    cprint(f"  Cards        : {card_count}", Colors.BLUE)
    cprint(f"  Tool calls   : {len(tool_names)}", Colors.BLUE)
    if tool_names:
        for i, t in enumerate(tool_names, 1):
            cprint(f"    {i}. {t}", Colors.CYAN)
    if think_text:
        cprint(f"  Think len    : {len(think_text)} chars", Colors.BLUE)
    print()


def _display_chat_rich(client: DemoClient, query: str):
    """Rich 美化输出 — 自定义协议"""
    console = Console()

    console.print()
    console.rule(f"[bold cyan]💬 {query}")
    console.print()

    t0 = time.time()
    think_text = ""
    response_text = ""
    card_count = 0
    tool_names = []
    in_think = False

    console.print("[dim]⏳ Agent thinking...[/dim]")
    console.print()

    for event in client.chat_stream(query):
        stage = event.get("stage", "")
        content = event.get("content", [])

        if stage == "think":
            if not in_think:
                console.print("[bold magenta]🧠 Thinking:[/bold magenta]")
                in_think = True
            for block in content:
                msg = block.get("msg", "")
                if msg:
                    think_text += msg
                    console.print(f"[dim]{msg}[/dim]", end="", highlight=False)

        elif stage == "response":
            if in_think:
                console.print()
                in_think = False
            for block in content:
                msg = block.get("msg", "")
                if msg:
                    response_text += msg
                    console.print(msg, end="", highlight=False)

        elif stage == "card":
            if in_think:
                console.print()
                in_think = False
            card_count += 1
            for block in content:
                card_data = block.get("msg", {})
                console.print()
                console.rule(f"[bold yellow]🎴 Card #{card_count}")
                card_type = card_data.get("type", card_data.get("cardType", "unknown"))
                console.print(f"[yellow]Type: {card_type}[/yellow]")
                pretty = json.dumps(card_data, indent=2, ensure_ascii=False)
                if len(pretty) > 1000:
                    console.print(f"[cyan]{pretty[:1000]}[/cyan]")
                    console.print(f"[dim]... ({len(pretty) - 1000} more chars)[/dim]")
                else:
                    console.print(f"[cyan]{pretty}[/cyan]")
                console.print()

        elif stage == "tool_call":
            if in_think:
                console.print()
                in_think = False
            for block in content:
                tool_name = block.get("tool_name", "unknown")
                status = block.get("status", "")
                msg = block.get("msg", "")
                if status == "calling":
                    console.print(f"\n[bold cyan]🔧 Calling: {tool_name}[/bold cyan]")
                    tool_names.append(tool_name)
                elif status == "called":
                    args_preview = msg
                    if len(args_preview) > 120:
                        args_preview = args_preview[:120] + "..."
                    console.print(f"[dim]   ↳ args: {args_preview}[/dim]")

        elif stage == "tool_response":
            for block in content:
                tool_name = block.get("tool_name", "unknown")
                status = block.get("status", "success")
                msg = block.get("msg", "")
                result_preview = msg
                if len(result_preview) > 200:
                    result_preview = result_preview[:200] + "..."
                icon = "✅" if status == "success" else "❌"
                style = "green" if status == "success" else "red"
                console.print(f"[{style}]   {icon} {tool_name} → {status} ({len(msg)} chars)[/{style}]")
                if result_preview:
                    console.print(f"[dim]   ↳ {result_preview}[/dim]")

    elapsed = time.time() - t0

    # 汇总面板
    summary_lines = [
        f"Time         : {elapsed:.1f}s",
        f"Response len : {len(response_text)} chars",
        f"Cards        : {card_count}",
        f"Tool calls   : {len(tool_names)}",
    ]
    if tool_names:
        for i, t in enumerate(tool_names, 1):
            summary_lines.append(f"  {i}. {t}")
    if think_text:
        summary_lines.append(f"Think len    : {len(think_text)} chars")

    console.print()
    console.print(Panel("\n".join(summary_lines), title="[bold green]✅ Done", border_style="green"))
    console.print()


# ──────────────────────────────────────────────
# Legacy 协议展示（/process 端点）
# ──────────────────────────────────────────────
def parse_and_display(client: DemoClient, query: str, use_rich: bool = False):
    """解析 SSE 流式事件，实时展示结果（旧协议）"""
    if use_rich and RICH:
        _display_rich(client, query)
    else:
        _display_plain(client, query)


def _display_plain(client: DemoClient, query: str):
    """纯终端输出（旧协议）"""
    cprint(f"\n{'='*60}", Colors.DIM)
    cprint(f"💬 Query: {query}", Colors.BOLD)
    cprint(f"{'='*60}\n", Colors.DIM)

    t0 = time.time()
    full_text = ""
    tool_calls = []
    reasoning_text = ""
    msg_count = 0
    current_type = None

    for event in client.query_stream(query):
        obj = event.get("object", "")
        etype = event.get("type", "")
        status = event.get("status", "")

        if obj == "agent_response":
            if status == "in_progress":
                cprint("⏳ Agent thinking...", Colors.DIM)
            elif status == "completed":
                elapsed = time.time() - t0
                cprint(f"\n\n✅ Done in {elapsed:.1f}s", Colors.GREEN)
                usage = event.get("usage", {})
                if usage:
                    inp = usage.get("input_tokens", usage.get("prompt_tokens", "?"))
                    out = usage.get("output_tokens", usage.get("completion_tokens", "?"))
                    cprint(f"   Tokens: input={inp}, output={out}", Colors.DIM)
            continue

        if obj == "message":
            current_type = etype
            if etype == "reasoning" and status == "in_progress":
                cprint("\n🧠 [Reasoning]\n", Colors.MAGENTA)
            elif etype == "message" and status == "in_progress":
                msg_count += 1
                if msg_count > 1:
                    cprint(f"\n{'─'*40}\n", Colors.DIM)
            continue

        if obj == "content" and etype == "text":
            text = event.get("text", "")
            if not text:
                continue
            if current_type == "reasoning":
                reasoning_text += text
                cprint(text, Colors.DIM, end="")
            else:
                full_text += text
                cprint(text, end="")
            continue

        if etype in ("plugin_call", "mcp_tool_call"):
            tool_name = event.get("name", "unknown")
            cprint(f"\n🔧 Tool call: {tool_name}", Colors.CYAN)
            tool_calls.append(tool_name)
            continue

        if etype in ("plugin_call_output", "mcp_tool_call_output"):
            content = event.get("content", "")
            if isinstance(content, list):
                content = str(content)
            preview = str(content)[:150]
            cprint(f"   ↳ {preview}...", Colors.DIM)
            continue

        if etype == "error" or status == "failed":
            err_msg = event.get("message", "") or event.get("error", "")
            cprint(f"\n❌ Error: {err_msg}", Colors.RED)

    cprint(f"\n\n{'='*60}", Colors.DIM)
    cprint("📊 Summary", Colors.BOLD)
    cprint(f"{'='*60}", Colors.DIM)
    cprint(f"  Text length : {len(full_text)} chars", Colors.BLUE)
    cprint(f"  Tool calls  : {len(tool_calls)}", Colors.BLUE)
    if tool_calls:
        for i, t in enumerate(tool_calls, 1):
            cprint(f"    {i}. {t}", Colors.CYAN)
    if reasoning_text:
        cprint(f"  Reasoning   : {len(reasoning_text)} chars", Colors.BLUE)
    print()


def _display_rich(client: DemoClient, query: str):
    """Rich 美化输出（旧协议）"""
    console = Console()

    console.print()
    console.rule(f"[bold cyan]💬 {query}")
    console.print()

    t0 = time.time()
    full_text = ""
    reasoning_text = ""
    tool_calls = []
    current_type = None

    console.print("[dim]⏳ Agent thinking...[/dim]")
    console.print()

    for event in client.query_stream(query):
        obj = event.get("object", "")
        etype = event.get("type", "")
        status = event.get("status", "")

        if obj == "agent_response":
            if status == "completed":
                elapsed = time.time() - t0
                usage = event.get("usage", {})
                inp = usage.get("input_tokens", usage.get("prompt_tokens", "?"))
                out = usage.get("output_tokens", usage.get("completion_tokens", "?"))
                console.print()
                console.rule("[bold green]✅ Done")
                console.print(
                    f"[dim]Time: {elapsed:.1f}s | "
                    f"Tokens: input={inp}, output={out}[/dim]"
                )
            continue

        if obj == "message":
            current_type = etype
            if etype == "reasoning" and status == "in_progress":
                console.print("[bold magenta]🧠 Reasoning Process:[/bold magenta]")
            elif etype == "message" and status == "in_progress":
                if full_text:
                    console.print()
                    console.print("[dim]" + "─" * 50 + "[/dim]")
                    console.print()
            continue

        if obj == "content" and etype == "text":
            text = event.get("text", "")
            if not text:
                continue
            if current_type == "reasoning":
                reasoning_text += text
                console.print(f"[dim]{text}[/dim]", end="", highlight=False)
            else:
                full_text += text
                console.print(text, end="", highlight=False)
            continue

        if etype in ("plugin_call", "mcp_tool_call"):
            tool_name = event.get("name", "unknown")
            tool_calls.append(tool_name)
            style = "dim cyan" if current_type == "reasoning" else "bold cyan"
            console.print(f"\n[{style}]🔧 {tool_name}[/{style}]", end="")
            continue

        if etype in ("plugin_call_output", "mcp_tool_call_output"):
            content = event.get("content", "")
            if isinstance(content, list):
                content = str(content)
            preview = str(content)[:120].replace("\n", " ")
            console.print(f" [dim]↳ {preview}...[/dim]")
            continue

        if etype == "error" or status == "failed":
            err_msg = event.get("message", "") or event.get("error", "")
            console.print(f"\n[bold red]❌ {err_msg}[/bold red]")

    summary_lines = [
        f"Text length : {len(full_text)} chars",
        f"Tool calls  : {len(tool_calls)}",
    ]
    if tool_calls:
        for i, t in enumerate(tool_calls, 1):
            summary_lines.append(f"  {i}. {t}")
    if reasoning_text:
        summary_lines.append(f"Reasoning   : {len(reasoning_text)} chars")

    console.print()
    console.print(Panel("\n".join(summary_lines), title="[bold green]✅ Done", border_style="green"))
    console.print()


# ──────────────────────────────────────────────
# CLI 入口
# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Auto Car Agent Demo Client")
    parser.add_argument("query", nargs="?", default="帮我对比一下宝马5系和奥迪A6L",
                        help="查询内容")
    parser.add_argument("--base-url", default="http://localhost:8000",
                        help="服务地址")
    parser.add_argument("--timeout", type=float, default=180.0,
                        help="请求超时（秒）")
    parser.add_argument("--health", action="store_true",
                        help="仅测试健康检查")
    parser.add_argument("--tools", action="store_true",
                        help="查看可用工具")
    parser.add_argument("--info", action="store_true",
                        help="查看 Agent 信息")
    parser.add_argument("--legacy", action="store_true",
                        help="使用旧 /process 端点（agentscope-runtime 格式）")
    parser.add_argument("--rich", action="store_true", default=False,
                        help="使用 Rich 美化输出")

    args = parser.parse_args()

    client = DemoClient(base_url=args.base_url, timeout=args.timeout)

    cprint("🚗 Auto Car Agent Service - Demo Client\n", Colors.BOLD)

    # 基础端点测试
    if args.health:
        try:
            data = client.health()
            print(json.dumps(data, indent=2, ensure_ascii=False))
        except Exception as e:
            cprint(f"❌ Health check failed: {e}", Colors.RED)
        return

    if args.tools:
        try:
            data = client.tools()
            print(f"Total tools: {data['count']}")
            for tool in data["tools"]:
                print(f"  - {tool['name']}: {tool['description'][:80]}...")
        except Exception as e:
            cprint(f"❌ Tools list failed: {e}", Colors.RED)
        return

    if args.info:
        try:
            data = client.agent_info()
            print(json.dumps(data, indent=2, ensure_ascii=False))
        except Exception as e:
            cprint(f"❌ Agent info failed: {e}", Colors.RED)
        return

    # 先测试连通性
    try:
        health = client.health()
        cprint(f"✅ Server: {health.get('agent', '?')} | Model: {health.get('llm_model', '?')}\n", Colors.GREEN)
    except Exception as e:
        cprint(f"❌ Cannot connect to server: {e}", Colors.RED)
        cprint("Make sure the service is running!", Colors.RED)
        sys.exit(1)

    # 查询
    if args.legacy:
        cprint(f"📡 Using /process endpoint (legacy format)\n", Colors.YELLOW)
        parse_and_display(client, args.query, use_rich=args.rich)
    else:
        cprint(f"📡 Using /agent/chat endpoint (custom SSE protocol)\n", Colors.GREEN)
        display_chat_stream(client, args.query, use_rich=args.rich)


if __name__ == "__main__":
    main()
