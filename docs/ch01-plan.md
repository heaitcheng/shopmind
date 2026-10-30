# ch01 实施计划 · 纯对话链路

> 输入：`docs/ch01-spec.md`（已定稿）
> 计划粒度：核心模块给完整代码，样板部分给签名 + 约束。每任务 2-5 分钟。

## 前置（人工）

1. 复制 `.env.example` 为 `.env`，填 `LLM_API_KEY`（默认上游智谱 BigModel，模型 `glm-4.7-flash` 免费）。
2. `tiktoken` 首次运行需联网下载编码表，约 71 秒。

## 任务 0：开隔离分支

```bash
git checkout -b ch01-chat
```

验证：`git branch --show-current` 输出 `ch01-chat`。

---

## 任务 1：项目骨架与配置

- 文件：`requirements.txt`、`.env.example`、`app/__init__.py`、`app/config.py`
- `app/config.py` 用 `pydantic-settings`：

```python
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    llm_model: str = "glm-4.7-flash"
    llm_api_key: str = ""
    llm_temperature: float = 0.7
    llm_timeout: float = 60.0
    llm_thinking: str = ""          # 智谱专用，留空则不发送 thinking 参数

    history_max_tokens: int = 1500
    structured_method: str = "function_calling"
    shop_name: str = "小店"

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- 验证：`.venv/Scripts/python.exe -c "from app.config import get_settings; print(get_settings().llm_model)"`

---

## 任务 2：结构化模型（TDD）

- 文件：`app/schemas.py`、`tests/test_schemas.py`
- 先写 `tests/test_schemas.py`：`AfterSaleRequest` 能接受合法输入、`intent` 非法值抛 `ValidationError`、`missing_fields` 默认空列表、`confidence` 越界抛错。跑测试看 **红**。
- 再实现 `app/schemas.py`：

```python
from enum import Enum
from pydantic import BaseModel, Field

class AfterSaleIntent(str, Enum):
    RETURN = "return"            # 退货
    EXCHANGE = "exchange"        # 换货
    REPAIR = "repair"            # 维修
    REFUND_ONLY = "refund_only"  # 仅退款
    OTHER = "other"

class AfterSaleRequest(BaseModel):
    order_id: str | None = Field(None, description="订单号，形如 SO20261029001")
    intent: AfterSaleIntent = Field(..., description="用户诉求类型")
    reason: str | None = Field(None, description="用户给出的原因")
    expected_solution: str | None = Field(None, description="用户期望的方案")
    missing_fields: list[str] = Field(default_factory=list, description="缺失的必要信息")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="抽取置信度")
```

- 验证：`pytest -q tests/test_schemas.py` 转 **绿**。

---

## 任务 3：Prompt 模板（TDD + 标注样例）

- 文件：`app/prompts.py`、`tests/test_prompts.py`
- `app/prompts.py` 用 `PromptTemplate`：

```python
from langchain_core.prompts import PromptTemplate

SYSTEM_PROMPT = PromptTemplate.from_template(
    """你是「{shop_name}」的在线客服。当前能力范围：售后咨询（退货、换货、维修、退款进度）。

规则：
1. 只用中文回答，语气平和、简洁，不寒暄铺垫。
2. 不承诺规则允许范围之外的事：不承诺赔偿、不承诺加急、不承诺具体到账时间。
3. 信息不足时先追问缺失项，一次最多问两个问题。
4. 不编造订单状态、物流单号、金额。不知道就说不清楚，并引导用户提供订单号。
5. 用户情绪激动时先共情一句，再给具体办法。
6. 无法处理时明确说明会转人工，不要假装能处理。
"""
)

EXTRACT_INSTRUCTION = PromptTemplate.from_template(
    """从用户的售后描述中抽取结构化信息。

要求：
- order_id 只抽取形如 SO+8位数字 的订单号，没有就留空，不要编造。
- intent 从给定枚举中选择，判断不了填 other。
- missing_fields 列出推进售后处理还缺哪些信息，例如 订单号、原因、凭证。
- 只输出结构化结果。"""
)

def render_system(shop_name: str) -> str:
    return SYSTEM_PROMPT.format(shop_name=shop_name)

def render_extract_instruction() -> str:
    return EXTRACT_INSTRUCTION.format()
```

- 验证：`pytest -q tests/test_prompts.py`，断言渲染结果包含店铺名与「不编造」字样。
- 纯 Prompt 部分另用标注样例验证（任务 12）。

---

## 任务 4：token 计数与上下文裁剪（TDD）

- 文件：`app/memory.py`（本任务只放计数与裁剪）、`tests/test_memory.py`
- 测试先行：造 20 条消息，`max_tokens=120`，断言 `len(kept) < 20`、`kept[0]` 是 `HumanMessage`、计数不超预算。
- 实现：

```python
import json
import tiktoken
from langchain_core.messages import BaseMessage, trim_messages

_enc = None

def _encoding():
    global _enc
    if _enc is None:
        _enc = tiktoken.get_encoding("cl100k_base")
    return _enc

def count_tokens(messages) -> int:
    if isinstance(messages, list):
        return sum(count_tokens(m) for m in messages)
    content = getattr(messages, "content", messages)
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    return len(_encoding().encode(content))

def build_context(history: list[BaseMessage], max_tokens: int) -> tuple[list[BaseMessage], int]:
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
```

- 注意：`strategy="last"` 是默认值但必须显式写，与 `start_on="human"` 配合才保证不从半轮切入。
- 验证：`pytest -q tests/test_memory.py` 转绿。

---

## 任务 5：会话存储（TDD）

- 文件：`app/memory.py` 追加、`tests/test_memory.py` 追加
- 测试：同 `session_id` 两次 `append` 后能取回 4 条；未知 id 返回空列表；`clear` 后为空。

```python
import threading

class SessionStore:
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
```

- 验证：`pytest -q tests/test_memory.py`

---

## 任务 6：模型工厂

- 文件：`app/llm.py`
- 统一 OpenAI 协议，四个变量切上游；`LLM_THINKING` 非空时才附加 `extra_body`：

```python
from functools import lru_cache
from langchain_openai import ChatOpenAI
from app.config import get_settings

@lru_cache
def get_llm() -> ChatOpenAI:
    s = get_settings()
    extra = {"thinking": {"type": s.llm_thinking}} if s.llm_thinking else None
    return ChatOpenAI(
        model=s.llm_model,
        base_url=s.llm_base_url,
        api_key=s.llm_api_key,
        temperature=s.llm_temperature,
        timeout=s.llm_timeout,
        **({"extra_body": extra} if extra else {}),
    )
```

- **关键**：`extra_body` 必须显式传，且 `thinking` 必须 `disabled`。`langchain-openai` 不解析 GLM 的 `reasoning_content`，开启后流式会静默到思考结束。
- 验证：`python -c "from app.llm import get_llm; m=get_llm(); print(m.model_name, m.openai_api_base, m._default_params.get('extra_body'))"`（不发请求）

---

## 任务 7：对话编排（TDD，用 FakeModel）

- 文件：`app/service.py`、`tests/conftest.py`、`tests/test_service_stream.py`
- `FakeModel` 需满足三件事：`astream(messages)` 异步产出 `AIMessageChunk`；记录收到的消息供断言；`with_structured_output(schema, method=...)` 返回可 `ainvoke` 的对象。
- 测试断言：首次请求产出若干 `token` 事件 + 一个 `done` 事件；`done.content` 为拼接结果；第二轮请求时传给模型的消息里含第一轮内容。
- 实现核心：

```python
class ChatService:
    def __init__(self, model, store: SessionStore, settings: Settings, session_id_factory=uuid4) -> None:
        ...

    async def stream(self, session_id: str | None, user_input: str):
        sid = session_id or str(self._new_id())
        kept, trimmed = build_context(self.store.get(sid), self.settings.history_max_tokens)
        messages = [
            SystemMessage(self._system()),
            *kept,
            HumanMessage(user_input),
        ]
        parts: list[str] = []
        async for chunk in self.model.astream(messages):
            text = chunk.content
            if isinstance(text, str) and text:
                parts.append(text)
                yield {"event": "token", "data": {"delta": text}}
        answer = "".join(parts)
        self.store.append(sid, [HumanMessage(user_input), AIMessage(answer)])
        yield {"event": "done", "data": {"content": answer, "session_id": sid, "trimmed": trimmed}}
```

- 关键约束：先落 `token` 事件，`done` 一定最后发；历史写入必须在流结束后（中途失败不污染历史）。

---

## 任务 8：结构化抽取编排（TDD）

- 文件：`app/service.py` 追加、`tests/test_service_extract.py`
- 测试：FakeModel 的 `with_structured_output` 被传入 `AfterSaleRequest` 与 `method="function_calling"`；返回值是 `AfterSaleRequest` 实例。

```python
async def extract(self, text: str) -> AfterSaleRequest:
    structured = self.model.with_structured_output(
        AfterSaleRequest, method=self.settings.structured_method
    )
    return await structured.ainvoke(
        [SystemMessage(render_extract_instruction()), HumanMessage(text)]
    )
```

- 验证：`pytest -q tests/test_service_extract.py`

---

## 任务 9：SSE 路由（TDD，依赖注入 FakeModel）

- 文件：`app/main.py`、`tests/test_api_stream.py`
- 帧格式函数固定为：

```python
def sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
```

- 路由返回 `StreamingResponse(media_type="text/event-stream")`，响应头带 `Cache-Control: no-cache` 与 `X-Accel-Buffering: no`。
- 异常在生成器内就地转成 `error` 事件，不让连接直接断。
- 测试用 `app.dependency_overrides` 注入 FakeModel，断言响应体包含 `event: token` 与 `event: done`。
- 验证：`pytest -q tests/test_api_stream.py`

---

## 任务 10：抽取路由与健康检查（TDD）

- 文件：`app/main.py` 追加、`tests/test_api_extract.py`
- `POST /api/chat/extract`，入参 `{"text": "..."}`，出参为 `AfterSaleRequest` 的 JSON。
- `GET /health` 返回 `{"status":"ok"}`。
- 验证：`pytest -q tests/test_api_extract.py`

---

## 任务 11：聊天页面（Vibe Coding，不套 TDD）

- 文件：`static/index.html`
- 单文件，无构建。`fetch` + `ReadableStream` 手动解析 SSE；输入框、消息气泡、发送中禁用、清空会话按钮。
- 由用户描述效果、我改，迭代到满意为止。
- 验证：`uvicorn app.main:app --reload` 后浏览器实测。

---

## 任务 12：验收与评估

- 三条 curl（见文末）
- 结构化抽取评估：`eval/extract_cases.jsonl` 20 条标注样例，脚本跑一遍算字段级准确率
- 数据写入 `dev-notes/ch01.md`
- 验证：三条 curl 输出符合预期，评估脚本输出准确率

---

## 验收命令

```bash
# 1 流式
curl -N -X POST http://127.0.0.1:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message":"我要退货"}'

# 2 两轮上下文
curl -N -X POST http://127.0.0.1:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"session_id":"demo1","message":"我的订单是 SO20261029001，尺码不合适想退货"}'
curl -N -X POST http://127.0.0.1:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"session_id":"demo1","message":"那我刚才是哪个订单来着？"}'

# 3 结构化
curl -s -X POST http://127.0.0.1:8000/api/chat/extract \
  -H "Content-Type: application/json" \
  -d '{"text":"昨天买的那件外套太小了穿不上，订单号 SO20261029001，我想换成L码，能不能直接寄新的过来"}'
```
