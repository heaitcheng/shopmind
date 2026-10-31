# shopmind

电商智能客服系统。当前完成两章：

- **ch01 纯对话链路** —— 多轮对话 + SSE 流式输出 + 售后信息结构化抽取
- **ch02 工具调用** —— 模型自主决定调用查订单 / 查商品 / 查物流 / 查 FAQ / 建工单，结果回灌后组织回答，全程落库

> 尚未实现 Agent 多轮循环与向量检索，留给后续章节。

## 能力

| 能力 | 接口 |
|---|---|
| 多轮对话 + 工具调用，逐 token 流式推送（SSE） | `POST /api/chat/stream` |
| 售后描述 → 结构化 JSON | `POST /api/chat/extract` |
| 清空会话 | `POST /api/chat/reset` |
| 聊天页面（含工具轨迹徽章） | `GET /` |
| 健康检查 | `GET /health` |

模型上游统一走 OpenAI 协议，换供应商只改 `.env`。默认接智谱 `glm-4.5-airx`，GPT / DeepSeek / Ollama 都能直接换。

五个工具：

| 工具 | 作用 | 数据来源 |
|---|---|---|
| `query_order` | 查订单详情 | 按 id 播种的假数据 |
| `query_product` | 查商品信息 | 按 id 播种的假数据 |
| `query_logistics` | 查物流进度 | 按 id 播种的假数据 |
| `query_faq` | 查常见问题 | MySQL `faq` 表，LIKE 匹配 |
| `create_ticket` | 创建人工工单 | 写入 MySQL `tickets` 表 |

## 快速开始

```bash
# 1 建虚拟环境并装依赖
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # macOS / Linux

# 2 配置密钥
cp .env.example .env
# 编辑 .env：填 LLM_API_KEY，确认 DATABASE_URL 与 TEST_DATABASE_URL

# 3 起 MySQL
docker compose up -d

# 4 建表并灌 FAQ（17 条，幂等，可重复执行）
.venv/Scripts/python.exe -m app.db.seed

# 5 启动
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000/ 即为聊天页面。

> - 首次运行 `tiktoken` 会联网下载分词表，约 70 秒，之后走缓存。
> - 数据库连不上时服务仍能启动（纯对话可用），只是工具调用与落库会失败并打 warning。
> - 改 `.env` 里的 `LLM_*` 即时生效；改 `DATABASE_URL` 需要重启（引擎缓存）。

## 验收命令

### ch02：工具调用三条

```bash
# 1 查物流：应看到 event: tool 帧，且回答引用工具返回的运单号与签收时间
curl -N -X POST http://127.0.0.1:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message":"订单 1001 的物流到哪了"}'

# 2 查 FAQ：应看到 query_faq 工具帧，回答复述 FAQ 原文
curl -N -X POST http://127.0.0.1:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message":"退货政策是什么"}'

# 3 预期漏召回：关键词「邮费」查不到任何条目，模型应如实说查不到并转人工
curl -N -X POST http://127.0.0.1:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message":"邮费是多少"}'
```

浏览器里能直接看到工具徽章：气泡上方一行 `query_logistics({"order_id":1001}) · 1ms`。
完整验收记录与截图见 `docs/ch02-verify.md`。

### ch01：纯对话三条

```bash
# 1 流式：应看到连续的 event: token，最后一条是 event: done
curl -N -X POST http://127.0.0.1:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message":"我要退货"}'

# 2 多轮：第二轮应能答出第一轮给的订单号
curl -N -X POST http://127.0.0.1:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"session_id":"demo1","message":"我的订单是 SO20261029001，尺码不合适想退货"}'

curl -N -X POST http://127.0.0.1:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"session_id":"demo1","message":"我刚才说的订单号是多少？"}'

# 3 结构化：应返回 order_id / intent / reason / expected_solution / missing_fields / confidence
curl -s -X POST http://127.0.0.1:8000/api/chat/extract \
  -H "Content-Type: application/json" \
  -d '{"text":"昨天买的外套太小了，订单号 SO20261029001，想换成 L 码"}'
```

### SSE 事件格式

```
event: token
data: {"delta": "文"}

event: tool
data: {"name": "query_logistics", "args": {"order_id": 1001}, "status": "running"}

event: tool
data: {"name": "query_logistics", "args": {"order_id": 1001}, "status": "ok", "elapsed_ms": 1, "error": null}

event: done
data: {"content": "完整回复", "session_id": "xxx", "trimmed": 0, "tools": [...]}

event: error
data: {"message": "上游超时"}
```

- `trimmed`：本轮因 token 预算被丢弃的历史消息条数。
- `tool` 帧：`status` 取 `running` / `ok` / `error` 三态，同一次调用会推两帧（先 running 再终结态）。
- `done.tools`：本轮全部工具轨迹，每项含 `id` / `name` / `args` / `ok` / `elapsed_ms` / `error` / `result`。
  前端用它做兜底渲染，防止 `tool` 帧漏接。

## 测试与评估

```bash
# 单元测试（112 条；接口层与编排层不发网络请求，接口层也不连 MySQL）
.venv/Scripts/python.exe -m pytest

# 工具调用标注样例（6 条，会真实调上游）
.venv/Scripts/python.exe eval/run_tool_eval.py --delay 2

# 结构化抽取评估（20 条标注样例，会真实调上游）
.venv/Scripts/python.exe eval/run_extract_eval.py --delay 1.2
```

最近一次结果：

- 单元测试 **112 passed**
- 工具调用样例 **6/6**（查物流 / 查订单 / FAQ 命中 / FAQ 漏召回 / 闲聊不调工具 / 能力边界）
- 结构化抽取：订单号 100%，意图 90%，缺失项召回 100%

## 目录结构

```
app/
  core/          # 基础设施
    config.py    #   pydantic-settings 读 .env，不缓存，改完即生效
    llm.py       #   ChatOpenAI 工厂，统一 OpenAI 协议，禁用环境代理
    prompts.py   #   PromptTemplate：客服 system prompt + 抽取指令
  db/            # 数据层
    base.py      #   引擎构造、会话工厂、建表
    models.py    #   faq / conversations / messages / tickets
    session.py   #   进程级引擎单例、FastAPI 会话依赖
    repo.py      #   建会话、写一轮对话
    seed.py      #   17 条 FAQ 种子数据，幂等
  tools/         # 工具层
    registry.py  #   注册表 + 执行器（校验/超时/重试/错误封装）
    business.py  #   query_order / query_product / query_logistics
    faq.py       #   query_faq
    ticket.py    #   create_ticket
  api/routes.py  # 路由、依赖装配、SSE 帧
  schemas.py     # AfterSaleRequest 结构化模型
  memory.py      # token 计数、上下文裁剪、进程内会话存储
  service.py     # 编排：单轮工具调用 + 流式产出事件
  main.py        # FastAPI 装配（仅装配）
static/index.html     # 聊天页面，单文件无构建
tests/                # 112 条测试
eval/                 # 标注样例与评估脚本
docs/                 # 设计定稿、实施计划、验收报告、截图
dev-notes/            # 开发过程追记
tools/                # Context7 查询、headless 截图脚本
docker-compose.yml    # MySQL 8.4，utf8mb4
```

## 设计要点

- **上下文裁剪**：`trim_messages` 按 token 预算裁剪，`start_on="human"` 保证不从半轮中间切入。
- **结构化输出**：`with_structured_output` 默认 `method="function_calling"`，兼容性最好。
  约束写在 schema 的字段 description 里比写在长 prompt 里更有效。
- **thinking 必须关闭**：智谱 GLM 的思考模式会先吐 `reasoning_content`，
  而 `langchain-openai` 不解析该字段，开启后流式会静默到思考结束。详见 `docs/ch01-spec.md` 4.7。
- **单轮收敛靠机制不靠 prompt**：第二趟调模型时不 `bind_tools`，模型根本没有工具可调。
  在 prompt 里写「只准调一次」不可靠。
- **工具参数约束用 `Literal`**：生成 JSON Schema 的 `enum`，比在 docstring 里写「只能选这几个」更硬。
- **`conversation_id` 不让模型填**：工具的会话 id 由闭包注入，模型编不出真实 id，让它填就是往表里写脏数据。
- **中间态消息不落 SessionStore**：`AIMessage(tool_calls)` 后面必须紧跟 `ToolMessage`，
  只存一半会让下一轮请求 400；全存又会让上下文迅速膨胀，而最终回答里已经包含工具结论。
- **测试库与演示库分离**：`TEST_DATABASE_URL` 不配就直接 `pytest.exit` 中止，
  不静默降级——静默降级会导致「跑一次测试把演示数据清空」。
- **会话不持久化到 SessionStore 之外**：进程内 dict 管上下文，MySQL 只做记录，两者不互相依赖。

## 已知限制

- **FAQ 只有关键词检索**：`LIKE '%keyword%'` 对同义词、口语化表达一律漏召回（「邮费」查不到「运费」）。
  模型偶尔会自发改写关键词，行为不稳定。下一步上向量检索。
- **只做单轮工具调用**：链式调用（先查订单再按状态决定查什么）和多单批量查询做不了。
- **假数据与真实业务无关**：订单 1001 永远是那件衬衫，改不了。
- **工单号并发不安全**：序号取「当天最大值 + 1」，并发创建理论上会撞主键。单机演示无碍。
- **无鉴权**：`session_id` 请求方自报，拿到即可读/写该会话。
- Anthropic 官方 API 不是 OpenAI 协议，要接原生 Claude 需经 one-api / LiteLLM 等网关转一层。
- 上下文裁剪按 tiktoken `cl100k_base` 计数，对非 OpenAI 模型是近似值。

## 文档

- `docs/ch02-spec.md` / `docs/ch02-plan.md` / `docs/ch02-verify.md` —— 工具调用一章的设计、计划、验收
- `docs/ch01-spec.md` / `docs/ch01-plan.md` —— 纯对话一章的设计定稿与实施计划
- `docs/ch01-review.md` —— 设计复盘：没问的问题、补丁式实现、拍脑袋的配置
- `dev-notes/ch01.md` / `dev-notes/ch02.md` —— 开发过程追记
