"""
流式文本解析器 — 处理文本中的 ```json...``` 代码块。

状态机:
  TEXT 模式  → 逐 token 推送 stage:"response"
  遇到 ```   → 进入 FENCE 模式，缓冲 JSON 内容
  遇到 ```   → 关闭 FENCE，尝试 JSON.parse
  卡片 JSON → 丢弃（卡片只能通过真实 card_type 占位符输出）
    其他内容 → 回退为 stage:"response"（原文）
  继续 TEXT 模式

说明：
  早期版本支持 LLM 直接输出卡片 JSON。当前已切换到严格占位符模式，
  任何 {card_type, card_data} / {card_type, card} 结构都不应从 response 文本中透出。
"""
import json


def sse_event(data: dict) -> str:
    """构造一条 SSE data 行"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _card_fingerprint(card: dict) -> str:
    """生成卡片指纹，用于去重"""
    ct = card.get("card_type") or card.get("cardType", "")
    cd = card.get("card_data") if "card_data" in card else card.get("cardData", {})
    card_key = card.get("card_key") or card.get("cardKey") or ""
    if not cd and isinstance(card.get("card"), dict):
        nested = card.get("card")
        cd = nested.get("card_data") if "card_data" in nested else nested.get("cardData", {})
        card_key = card_key or nested.get("card_key") or nested.get("cardKey") or ""
    series_hint = ""
    if isinstance(cd, dict):
        for key in ("compare_series", "series_list", "series"):
            val = cd.get(key)
            if val:
                series_hint = json.dumps(val, ensure_ascii=False, sort_keys=True)
                break
        if not series_hint:
            series_hint = json.dumps(cd, ensure_ascii=False, sort_keys=True, default=str)
    return f"{ct}::{card_key}::{series_hint}"


class StreamCardParser:
    """流式文本 → think/response/card 事件转换器"""

    def __init__(self, emitted_card_keys: set[str] | None = None):
        self._buf = ""
        self._in_fence = False
        self._fence_buf = ""
        self._fence_lang = ""
        self._emitted = emitted_card_keys if emitted_card_keys is not None else set()

    # ──────────────────── 公共接口 ────────────────────

    def feed(self, delta: str):
        """喂入一个文本增量，yield SSE 事件字符串"""
        if self._in_fence:
            self._fence_buf += delta
            yield from self._try_close_fence()
        else:
            self._buf += delta
            yield from self._try_open_fence()

    def flush(self):
        """冲刷所有残余内容（TextBlockEnd / ReplyEnd 时调用）"""
        if self._in_fence and self._fence_buf:
            lang = self._fence_lang
            yield sse_event({
                "stage": "response",
                "content": [{"type": "text", "msg": f"```{lang}\n{self._fence_buf}"}],
            })
            self._in_fence = False
            self._fence_buf = ""
            self._fence_lang = ""
        if self._buf:
            yield sse_event({
                "stage": "response",
                "content": [{"type": "text", "msg": self._buf}],
            })
            self._buf = ""

    # ──────────────────── 内部方法 ────────────────────

    def _try_open_fence(self):
        """在缓冲中查找 ``` 开头，进入围栏模式"""
        idx = self._buf.find("```")
        if idx < 0:
            if len(self._buf) > 2:
                safe = self._buf[:-2]
                self._buf = self._buf[-2:]
                if safe:
                    yield sse_event({
                        "stage": "response",
                        "content": [{"type": "text", "msg": safe}],
                    })
            return

        before = self._buf[:idx]
        if before:
            yield sse_event({
                "stage": "response",
                "content": [{"type": "text", "msg": before}],
            })

        self._buf = self._buf[idx:]
        rest = self._buf[3:]
        nl = rest.find("\n")
        if nl >= 0:
            self._fence_lang = rest[:nl].strip()
            self._in_fence = True
            self._fence_buf = rest[nl + 1:]
            self._buf = ""
            yield from self._try_close_fence()

    def _try_close_fence(self):
        """在围栏缓冲中查找 ``` 结尾，解析并推送"""
        close_idx = self._fence_buf.find("```")
        if close_idx < 0:
            return

        code_text = self._fence_buf[:close_idx].strip()
        remainder = self._fence_buf[close_idx + 3:]

        self._in_fence = False
        lang = self._fence_lang
        self._fence_lang = ""
        self._fence_buf = ""

        suppressed_card_json = False
        if lang == "json" and code_text:
            try:
                card = json.loads(code_text)
                if (
                    isinstance(card, dict)
                    and (
                        ("card_type" in card and "card_data" in card)
                        or ("cardType" in card and "cardData" in card)
                        or ("card_type" in card and "card" in card)
                        or ("cardType" in card and "card" in card)
                    )
                ):
                    self._emitted.add(_card_fingerprint(card))
                    suppressed_card_json = True
            except (json.JSONDecodeError, TypeError):
                pass

        if not suppressed_card_json and code_text:
            full = f"```{lang}\n{code_text}\n```" if lang else f"```\n{code_text}\n```"
            yield sse_event({
                "stage": "response",
                "content": [{"type": "text", "msg": full}],
            })

        self._buf += remainder.lstrip("\n")
        yield from self._try_open_fence()
