# ch01 设计定稿 · 纯对话链路

> 目标：跑通一条多轮、流式、可结构化抽取的对话链路。不做工具调用、不做 Agent。
> 定稿日期：2026-10-30

## 1. 范围

**做**：SSE 流式对话、Prompt 模板化、结构化售后信息提取、多轮上下文最简裁剪。

**不做**（YAGNI）：工具调用、Agent 循环、RAG、数据库持久化、鉴权、部署。

## 2. 验收点 → 接口映射

| 验收标准 | 落地接口 |
|---|---|
| curl 看到逐 token 流式回复 | `POST /api/chat/stream` |
| 连续两轮，第二轮接住第一轮上下文 | 同上，复用 `session_id` |
| 售后描述 → 结构化 JSON | `POST /api/chat/extract` |
| （附加）清空会话 | `POST /api/chat/reset` |
| （附加）聊天页面 | `GET /` |
| （附加）健康检查 | `GET /health` |

## 3. 目录结构

```
app/
  __init__.py
  config.py      # pydantic-settings 读 .env
  llm.py         # ChatOpenAI 工厂，统一 OpenAI 协议
  prompts.py     # PromptTemplate 模板
  schemas.py     # 结构化输出 Pydantic 模型
  memory.py      # 会话存储 + token 预算裁剪
  service.py     # 编排：组装消息 → 调模型 → 产出事件
  main.py        # FastAPI 应用与路由
static/index.html  # 聊天页（vibe coding 产物）
tests/            # pytest
docs/ch01-spec.md, docs/ch01-plan.md
dev-notes/ch01.md
.env.example
requirements.txt
```

## 4. 关键设计决策

### 4.1 上游：一律 OpenAI 协议

```python
ChatOpenAI(model=..., base_url=..., api_key=..., extra_body=...)
```

别名 `base_url` / `api_key` 在 langchain-openai 1.7.3 实测可用（等价 `openai_api_base` / `openai_api_key`）。
`.env` 四个变量即可切换上游：`LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` / `LLM_TEMPERATURE`。

**默认落地：智谱 BigModel**
- 端点 `https://open.bigmodel.cn/api/paas/v4`（实测直连可达，无需代理）
- 模型 `glm-4.5-airx`（轻量付费档，128K 上下文，¥0.8/¥2 每百万 tokens，支持 Function Calling / 结构化输出 / 流式）
- 免费档 `glm-4.7-flash` 实测限流极严（20 条连续请求约 1/4 触发 429），只适合试玩
- 想提效果就改 `LLM_MODEL` 为 `glm-4.7`，端点不变

**已核实的限制**：Anthropic 官方 API 不是 OpenAI 协议。要接原生 Claude，需经 one-api / LiteLLM 网关转一层，或改用 `langchain-anthropic`。
按用户决定，ch01 不处理 Claude，仅记录为已知限制。

### 4.2 流式：手写 SSE，不引 sse-starlette

`StreamingResponse(media_type="text/event-stream")` + 手动拼帧。三种事件：

```
event: token
data: {"delta": "文"}

event: done
data: {"content": "完整回复", "session_id": "xxx", "usage": {...}, "trimmed": 6}

event: error
data: {"message": "上游超时"}
```

理由：只有三种事件，`sse-starlette` 的心跳/重连能力用不上，多一个依赖不值得。

### 4.3 会话：进程内 dict，不做持久化

`dict[str, list[BaseMessage]]` + 线程锁。重启即丢，ch01 明确接受。
前端不传 `session_id` 时服务端生成并随 `done` 事件返回。

### 4.4 上下文裁剪：`trim_messages`

```python
trim_messages(
    history,
    max_tokens=settings.history_max_tokens,   # 默认 1500
    token_counter=count_tokens,
    strategy="last",
    start_on="human",        # 关键：避免从半轮中间切入
    allow_partial=False,     # 不切半条消息
    include_system=False,
)
```

`token_counter` 用 tiktoken `cl100k_base`。**已实测**：首次加载需联网下载编码表约 71 秒，之后 0.3 秒。
对 DeepSeek 等非 OpenAI 模型，计数是近似值，用于预算够用。

裁剪掉的条数回传给前端（`trimmed` 字段），便于观察。

### 4.5 结构化输出：默认 `function_calling`

```python
model.with_structured_output(AfterSaleRequest, method=settings.structured_method)
```

langchain-openai 1.7.3 的默认值是 `method="json_schema"`，**DeepSeek 不支持**该 `response_format`。
因此默认取 `function_calling`，`STRUCTURED_METHOD` 环境变量可覆盖为 `json_schema` / `json_mode`。

输出 schema：

```python
class AfterSaleRequest(BaseModel):
    order_id: str | None          # 订单号，形如 SO20261029001
    intent: AfterSaleIntent       # return / exchange / repair / refund_only / other
    reason: str | None            # 用户给出的原因
    expected_solution: str | None # 用户期望的方案
    missing_fields: list[str]     # 还缺哪些必要信息，供后续槽位补齐用
    confidence: float             # 0~1
```

`missing_fields` 现在只记录、不使用，为 ch02 的槽位补齐留钩子。

### 4.6 Prompt：用 `PromptTemplate` 而非 `ChatPromptTemplate`

用户点名 `PromptTemplate`。这里只需要渲染一段 system 文本，`ChatPromptTemplate` 的 `MessagesPlaceholder` 用不上。
消息组装手工完成：`[SystemMessage(渲染结果), *裁剪后历史, HumanMessage(输入)]`。

### 4.7 智谱 thinking 模式必须关闭

GLM 系列支持深度思考，开启后流式 delta 先给 `reasoning_content`、再给 `content`。

**已核实**：`langchain-openai` 的 `BaseChatOpenAI._create_chat_result` 源码里搜不到 `reasoning_content`，即不解析该字段。
后果是开启 thinking 后，流式接口在思考阶段一个字都不推，前端表现为卡死，直接违反验收标准 1。

解法：用 `extra_body` 显式关闭，且已验证该字段会进 `_default_params`、随请求发出。

```python
extra_body={"thinking": {"type": "disabled"}}
```

`LLM_THINKING` 留空时不发送该参数，保证非智谱上游不受影响。

## 5. 验证策略

TDD 不适用于纯 Prompt / 数据类，按要求替换为：

| 类型 | 验证手段 |
|---|---|
| 可单测代码（memory / schemas / 路由协议） | pytest + FakeLLM，红-绿-重构 |
| 纯 Prompt（system 人设与约束） | 标注样例集跑一遍，人工判定是否符合 |
| 结构化抽取 | 20 条标注样例，算字段级准确率 |
| 端到端 | curl 三条验收命令 |

## 6. 已知风险

1. tiktoken 首次运行需联网下载 BPE（约 71s），断网环境会失败 → 计入 README 前置说明。
2. `function_calling` 方式下对复杂 schema 偶有字段缺失，`missing_fields` 会暴露这一点。
3. 进程内会话在多 worker 下不共享，ch01 只跑单 worker。
4. 智谱免费档限流极严，已改付费轻量档。

## 7. 实测结果（2026-10-30，glm-4.5-airx）

抽取评估 20 条标注样例，`eval/run_extract_eval.py`：

| 指标 | 结果 |
|---|---|
| 调用成功率 | 20/20 |
| 订单号准确率 | 20/20 = 100% |
| 意图准确率 | 18/20 = 90% |
| 缺失项召回率 | 10/10 = 100% |

两条意图错判经人工复核属**标注歧义**，非模型错误：
「退款什么时候到账」判 `refund_only`、「少了一件」判 `return`，两种理解均成立。后续应细化标注口径。

调优过程（同为 20 条样本，免费档 `glm-4.7-flash`）：

| 轮次 | 改动 | 订单号 | 意图 | 缺失项召回 |
|---|---|---|---|---|
| 1 | 初版 prompt | 94.4% | 88.9% | 44.4% |
| 2 | 把约束写进 schema 字段 description + 长 prompt | 86.7% | 93.3% | 75.0% |
| 3 | 换 glm-4.5-airx + 归一化 `"null"` 字符串 | 100% | 90.0% | 100% |

关键教训：走 `function_calling` 时，模型更依赖 schema 里每个字段的 description，长指令 prompt 的作用有限。约束必须写进字段描述。
