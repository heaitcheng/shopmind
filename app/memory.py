import json
import threading

import tiktoken
from langchain_core.messages import BaseMessage, trim_messages

_encoding = None
_encoding_lock = threading.Lock()


def _get_encoding():
    """tiktoken 首次加载需联网下载 BPE 表（约 70 秒），之后走缓存。"""
    global _encoding
    if _encoding is None:
        with _encoding_lock:
            if _encoding is None:
                _encoding = tiktoken.get_encoding("cl100k_base")
    return _encoding


def count_tokens(messages) -> int:
    """同时支持单条消息和消息列表，供 trim_messages 两种调用方式复用。"""
    if isinstance(messages, list):
        return sum(count_tokens(m) for m in messages)

    content = getattr(messages, "content", messages)
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    return len(_get_encoding().encode(content))


def build_context(
    history: list[BaseMessage], max_tokens: int
) -> tuple[list[BaseMessage], int]:
    """按 token 预算裁剪历史，返回 (保留的消息, 被丢弃的条数)。

    strategy="last" 保留最近的对话；start_on="human" 保证不会从半轮中间切入，
    否则模型会看到一条没有提问的回答。
    """
    if not history:
        return [], 0

    kept = trim_messages(
        history,
        max_tokens=max_tokens,
        token_counter=count_tokens,
        strategy="last",
        allow_partial=False,
        start_on="human",
        include_system=False,
    )
    return kept, len(history) - len(kept)


class SessionStore:
    """进程内会话存储。重启即丢，ch01 不做持久化。"""

    def __init__(self) -> None:
        self._data: dict[str, list[BaseMessage]] = {}
        self._lock = threading.Lock()

    def get(self, session_id: str) -> list[BaseMessage]:
        with self._lock:
            return list(self._data.get(session_id, []))

    def append(self, session_id: str, messages: list[BaseMessage]) -> None:
        with self._lock:
            self._data.setdefault(session_id, []).extend(messages)

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._data.pop(session_id, None)

    def clear_all(self) -> None:
        with self._lock:
            self._data.clear()
