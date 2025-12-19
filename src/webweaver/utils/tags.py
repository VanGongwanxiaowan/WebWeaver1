"""Tag and tool_call parsing utilities.

本模块参考了 ``docs/标签处理逻辑`` 中的解析思路，提供一个轻量级、
可复用的标签 / JSON 提取工具，用于 Planner / Writer 等 Agent 的
标签解析和容错处理。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from webweaver.logging import get_logger

logger = get_logger(__name__)


_TAG_BLOCK_TEMPLATE = r"<{name}>(?P<body>.*?)</{name}>"


def find_tag_block(text: str, tag_name: str) -> Optional[str]:
    """在文本中查找第一个 `<tag_name>...</tag_name>` 区块并返回内部内容。

    匹配是大小写不敏感的，并且使用 ``re.DOTALL`` 支持跨行。
    如果没有找到完整标签，返回 ``None``。
    """

    if not text:
        return None

    pattern = _TAG_BLOCK_TEMPLATE.format(name=re.escape(tag_name))
    m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    if not m:
        return None
    return m.group("body").strip()


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """从文本中尽可能提取一个 JSON 对象。

    策略（从严格到宽松）：
        1. 如果整体看起来就是 JSON（以 ``{`` 开头、以 ``}`` 结尾），直接解析。
        2. 使用正则在文本中寻找第一个 ``{...}`` 结构并尝试解析。

    如果解析失败，返回 ``None`` 而不是抛出异常。
    """

    if not text:
        return None

    cleaned = text.strip()

    # 方法0：先尝试从 markdown 代码块（```json ... ``` 或 ``` ... ```）中提取
    try:
        fence_pattern = r"```json\s*\n?(.*?)\n?```"
        m = re.search(fence_pattern, cleaned, re.DOTALL | re.IGNORECASE)
        if not m:
            # 无显式 json 标志时，尝试任意 ```...``` 代码块
            fence_pattern_generic = r"```\s*\n?(.*?)\n?```"
            m = re.search(fence_pattern_generic, cleaned, re.DOTALL)
        if m:
            inner = m.group(1).strip()
            if inner.startswith("{") and inner.endswith("}"):
                return json.loads(inner)
    except Exception:
        logger.debug("extract_json_object: markdown-fenced JSON parse failed")
    # 方法1：整体是 JSON
    if cleaned.startswith("{") and cleaned.endswith("}"):
        try:
            return json.loads(cleaned)
        except Exception:
            logger.debug("extract_json_object: whole-text JSON parse failed")

    # 方法2：在文本中查找第一个 { ... } 片段
    try:
        json_pattern = r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}"
        m = re.search(json_pattern, cleaned, re.DOTALL)
        if m:
            candidate = m.group(0)
            return json.loads(candidate)
    except Exception:
        logger.debug("extract_json_object: regex-based JSON parse failed")

    return None


def parse_tool_call_payload(text: str) -> Optional[Dict[str, Any]]:
    """解析 LLM 输出中的 tool_call 负载 JSON。

    支持以下情况：
        - 规范格式：``<tool_call>{...}</tool_call>``
        - 带额外说明：例如“我将调用工具：<tool_call>{...}</tool_call>”
        - 模型忘记加 ``<tool_call>`` 标签，只输出 ``{...}`` 的情况。

    Args:
        text: 完整的 LLM 响应文本。

    Returns:
        解析得到的 JSON 对象（通常形如
        ``{\"name\": \"retrieve\", \"arguments\": {...}}``），失败返回 ``None``。
    """

    if not text:
        return None

    # 1) 优先从 <tool_call>...</tool_call> 中提取
    block = find_tag_block(text, "tool_call")
    if block:
        obj = extract_json_object(block)
        if obj is not None:
            return obj

    # 2) 回退：直接在整个文本中查找 JSON
    obj = extract_json_object(text)
    if obj is not None:
        return obj

    logger.debug("parse_tool_call_payload: no valid tool_call payload found")
    return None


