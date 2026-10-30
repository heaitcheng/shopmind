# shopmind

电商智能客服系统。当前为第一章：**纯对话链路** —— 多轮对话 + SSE 流式输出 + 售后信息结构化抽取。

> 尚未实现工具调用与 Agent 循环，那一部分留给后续章节。

## 能力

| 能力 | 接口 |
|---|---|
| 多轮对话，逐 token 流式推送（SSE） | `POST /api/chat/stream` |
| 售后描述 → 结构化 JSON | `POST /api/chat/extract` |
| 清空会话 | `POST /api/chat/reset` |
| 聊天页面 | `GET /` |
| 健康检查 | `GET /health` |

模型上游统一走 OpenAI 协议，换供应商只改 `.env`。默认接智谱 `glm-4.5-airx`，GPT / DeepSeek / Ollama 都能直接换。

## 快速开始

```bash
# 1 建虚拟环境并装依赖
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # macOS / Linux

# 2 配置密钥
cp .env.example .env
# 编辑 .env，把 LLM_API_KEY 换成真实密钥

# 3 启动
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000/ 即为聊天页面。

> 首次运行 `tiktoken` 会联网下载分词表，约 70 秒，之后走缓存。断网环境下 token 预算功能不可用。

## 验收命令

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

event: done
data: {"content": "完整回复", "session_id": "xxx", "trimmed": 0}

event: error
data: {"message": "上游超时"}
```

`trimmed` 表示本轮因 token 预算被丢弃的历史消息条数。

## 测试与评估

```bash
# 单元测试（47 条，全部用 FakeModel，不发网络请求）
.venv/Scripts/python.exe -m pytest

# 结构化抽取评估（20 条标注样例，会真实调上游并产生费用）
.venv/Scripts/python.exe eval/run_extract_eval.py --delay 1.2
```

最近一次评估：订单号准确率 100%，意图准确率 90%，缺失项召回率 100%。

## 目录结构

```
app/
  config.py    # pydantic-settings 读 .env，不缓存，改完即生效
  llm.py       # ChatOpenAI 工厂，统一 OpenAI 协议
  prompts.py   # PromptTemplate：客服 system prompt + 抽取指令
  schemas.py   # AfterSaleRequest 结构化模型
  memory.py    # token 计数、上下文裁剪、进程内会话存储
  service.py   # 编排：拼消息 → 调模型 → 产出事件
  main.py      # FastAPI 路由与 SSE 帧
static/index.html   # 聊天页面，单文件无构建
tests/              # 47 条单元测试
eval/               # 标注样例与评估脚本
docs/               # 设计定稿与实施计划
dev-notes/          # 开发过程追记
tools/ctx7.mjs      # Context7 文档查询小工具
```

## 设计要点

- **上下文裁剪**：`trim_messages` 按 token 预算裁剪，`start_on="human"` 保证不从半轮中间切入。
- **结构化输出**：`with_structured_output` 默认 `method="function_calling"`，兼容性最好。
  约束写在 schema 的字段 description 里比写在长 prompt 里更有效。
- **thinking 必须关闭**：智谱 GLM 的思考模式会先吐 `reasoning_content`，
  而 `langchain-openai` 不解析该字段，开启后流式会静默到思考结束。详见 `docs/ch01-spec.md` 4.7。
- **会话不持久化**：进程内 dict，重启即丢，只跑单 worker。

## 已知限制

- Anthropic 官方 API 不是 OpenAI 协议，要接原生 Claude 需经 one-api / LiteLLM 等网关转一层。
- 上下文裁剪按 tiktoken `cl100k_base` 计数，对非 OpenAI 模型是近似值。
- 无鉴权、无数据库、无工具调用。

## 文档

- `docs/ch01-spec.md` —— 设计定稿，含评估结果与调优记录
- `docs/ch01-plan.md` —— 实施计划
- `dev-notes/ch01.md` —— 开发过程追记
