"""
Auto Car Agent Service - 测试客户端
测试 SSE 流式响应和普通端点

用法:
    python test_client.py                          # 默认测试 /chat 自定义协议
    python test_client.py "宝马5系和奥迪A6L哪个好"   # 自定义 query
    python test_client.py --legacy                  # 测试旧 /process 端点
"""
import sys
import json
import argparse
import httpx

BASE_URL = "http://localhost:8000"


def test_health():
    """测试健康检查"""
    print("=" * 50)
    print("🏥 Health Check")
    print("=" * 50)
    resp = httpx.get(f"{BASE_URL}/health")
    print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
    print()


def test_tools():
    """测试工具列表"""
    print("=" * 50)
    print("🔧 Available Tools")
    print("=" * 50)
    resp = httpx.get(f"{BASE_URL}/tools")
    data = resp.json()
    print(f"Total tools: {data['count']}")
    for tool in data["tools"]:
        print(f"  - {tool['name']}: {tool['description'][:60]}...")
    print()


def test_agent_info():
    """测试 Agent 信息"""
    print("=" * 50)
    print("🤖 Agent Info")
    print("=" * 50)
    resp = httpx.get(f"{BASE_URL}/agent-info")
    print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
    print()


def test_chat(query: str):
    """测试 /chat 自定义 SSE 协议"""
    print("=" * 50)
    print(f"💬 [/chat] Query: {query}")
    print("=" * 50)

    payload = {
        "query": query,
        "sessionId": "test-session-001",
        "userId": "test-user-001",
        "reqId": "test-req-001",
    }

    with httpx.stream(
        "POST",
        f"{BASE_URL}/agent/chat",
        json=payload,
        timeout=120.0,
    ) as response:
        print(f"Status: {response.status_code}")
        print(f"Content-Type: {response.headers.get('content-type')}")
        print("-" * 50)

        buffer = ""
        for chunk in response.iter_text():
            buffer += chunk
            while "\n\n" in buffer:
                event_str, buffer = buffer.split("\n\n", 1)
                for line in event_str.strip().split("\n"):
                    if line.startswith("data: "):
                        data_str = line[6:]
                        try:
                            data = json.loads(data_str)
                            stage = data.get("stage", "")
                            content = data.get("content", [])

                            if stage == "think":
                                for block in content:
                                    msg = block.get("msg", "")
                                    print(f"\033[35m{msg}\033[0m", end="", flush=True)

                            elif stage == "response":
                                for block in content:
                                    msg = block.get("msg", "")
                                    print(msg, end="", flush=True)

                            elif stage == "card":
                                for block in content:
                                    card = block.get("msg", {})
                                    print(f"\n\033[33m{'─'*40}\033[0m", flush=True)
                                    print(f"\033[33m🎴 Card:\033[0m", flush=True)
                                    pretty = json.dumps(card, indent=2, ensure_ascii=False)
                                    if len(pretty) > 500:
                                        print(f"\033[36m{pretty[:500]}...\033[0m", flush=True)
                                    else:
                                        print(f"\033[36m{pretty}\033[0m", flush=True)
                                    print(f"\033[33m{'─'*40}\033[0m\n", flush=True)

                        except json.JSONDecodeError:
                            pass

    print("\n")


def test_process(query: str):
    """测试 /process 旧端点（agentscope-runtime 标准 SSE）"""
    print("=" * 50)
    print(f"💬 [/process] Query: {query}")
    print("=" * 50)

    payload = {
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": query}
                ]
            }
        ],
        "stream": True,
        "session_id": "test-session-001",
    }

    with httpx.stream(
        "POST",
        f"{BASE_URL}/process",
        json=payload,
        timeout=120.0,
    ) as response:
        print(f"Status: {response.status_code}")
        print(f"Content-Type: {response.headers.get('content-type')}")
        print("-" * 50)

        buffer = ""
        for chunk in response.iter_text():
            buffer += chunk
            while "\n\n" in buffer:
                event_str, buffer = buffer.split("\n\n", 1)
                for line in event_str.strip().split("\n"):
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            print("\n[DONE]")
                            return
                        try:
                            data = json.loads(data_str)
                            if "content" in data:
                                for block in data["content"]:
                                    if block.get("type") == "text":
                                        print(block.get("text", ""), end="", flush=True)
                                    elif block.get("type") == "tool_use":
                                        print(f"\n🔧 Tool call: {block.get('name', '')}", flush=True)
                            elif "text" in data:
                                print(data["text"], end="", flush=True)
                            else:
                                print(f"\n[event] {json.dumps(data, ensure_ascii=False)[:200]}", flush=True)
                        except json.JSONDecodeError:
                            pass

    print("\n")


def main():
    parser = argparse.ArgumentParser(description="Auto Car Agent Test Client")
    parser.add_argument("query", nargs="?", default="帮我对比一下宝马5系和奥迪A6L",
                        help="查询内容")
    parser.add_argument("--legacy", action="store_true",
                        help="使用旧 /process 端点")
    args = parser.parse_args()

    print("🚗 Auto Car Agent Service - Test Client\n")

    # 基础端点测试
    try:
        test_health()
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        print("Make sure the service is running!")
        sys.exit(1)

    try:
        test_agent_info()
    except Exception as e:
        print(f"❌ Agent info failed: {e}")

    try:
        test_tools()
    except Exception as e:
        print(f"❌ Tools list failed: {e}")

    # 主查询测试
    if args.legacy:
        try:
            test_process(args.query)
        except Exception as e:
            print(f"❌ Query failed: {e}")
    else:
        try:
            test_chat(args.query)
        except Exception as e:
            print(f"❌ Chat query failed: {e}")

    print("\n✅ Tests completed!")


if __name__ == "__main__":
    main()
