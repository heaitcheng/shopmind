# ch02 设计定稿 · 工具调用接入客服聊天

> 目标：给 ch01 的客服聊天装上查数据能力。模型自己决定调哪个工具，工具结果回灌后组织回答。
> 定稿日期：2026-10-31

## 1. 范围

**做**：四张表 + Docker MySQL、五个业务工具、工具基础设施（注册/校验/超时/重试/错误）、工具轨迹接进 SSE 聊天、对话落库、页面工具徽章。

**不做**：Agent Loop 多轮自动循环（只做单轮）、向量检索 / RAG（留给下一步）。

## 2. 验收点 → 落地

| 验收标准 | 落地 |
|---|---|
| 问「订单 1001 的物流到哪了」→ 模型选中工具、气泡带徽章、按结果作答 | `query_logistics` + SSE `tool` 帧 + 前端徽章 |
| 问「退货政策是什么」→ `query_faq` 查得到 | faq 表 LIKE 查询 |
| 问「邮费是多少」→ 查不出来 | **预期漏召回**，记入已知限制，不在本章修 |

## 3. 目录结构（在 ch01 基础上分层）

```
app/
  main.py              # 只做 app 装配，路由搬走
  api/
    routes.py          # /api/chat/stream、/api/chat/extract、/api/chat/reset、/health、/
  core/
    config.py          # 原 app/config.py，新增 DATABASE_URL 等
    llm.py             # 原 app/llm.py
    prompts.py         # 原 app/prompts.py，新增工具使用约束
  db/
    base.py            # Base / async engine / async_sessionmaker
    models.py          # 四张表
    session.py         # get_session 依赖
    seed.py            # 灌测试数据
  tools/
    registry.py        # 工具注册 + 执行器（超时/重试/错误封装）
    business.py        # query_order / query_product / query_logistics
    faq.py             # query_faq
    ticket.py          # create_ticket
  service.py           # 编排：模型定工具 → 执行 → 回灌 → 流式
  memory.py            # 保留（ch01 的进程内会话，本章仍用）
docker-compose.yml     # MySQL 8
```

**这是本章唯一的大改动**：ch01 的 `app/*.py` 平铺结构改成 `core/` + `api/` + `db/` + `tools/` 分层。文件内容基本平移，主要成本是改 import 路径和测试引用。

## 4. 数据模型

```python
# faq
id: int PK
question: str(500)
answer: Text
category: str(50)
created_at: datetime

# conversations
id: int PK
session_key: str(64) unique   # ← 规格外的必要补充，见下方说明
user_id: str(64)              # 无鉴权，存前端生成的匿名 id
status: str(20)               # open / closed
created_at: datetime

# messages
id: int PK
conversation_id: int FK
role: str(16)             # user / assistant / tool
content: Text
tool_calls: JSON | None   # 模型发起的工具调用申请
tool_call_id: str(64) | None
created_at: datetime

# tickets
ticket_no: str(32) PK     # 形如 TK20261031-0001
conversation_id: int FK
description: Text
ticket_type: str(32)
status: str(20)           # open / processing / closed
created_at: datetime
```

字符集 `utf8mb4` + `utf8mb4_unicode_ci`，否则中文 LIKE 会出问题。

**为什么多一个 `session_key`**：用户给的 conversations 字段是「用户、处理状态、创建时间」，没有主键类型也没说怎么和 ch01 的 `session_id` 对上。ch01 的 `session_id` 是前端生成的字符串（如 `nl2`、uuid hex），而 `conversations.id` 是自增 int，两者必须有映射才能把消息挂到正确的会话上。加一列 `session_key` 存原始字符串、加唯一索引，是改动成本最低的做法。如果不加，就只能把 `user_id` 当会话键用，那样一个用户只能有一个会话，「新开会话」这个动作就废了。

## 5. 五个工具

| 工具 | 参数 | 实现 |
|---|---|---|
| `query_order` | `order_id: int` | **假数据**，按 order_id 播种随机 |
| `query_product` | `product_id: int` | 同上 |
| `query_logistics` | `order_id: int` | 同上 |
| `query_faq` | `keyword: str` | `SELECT ... WHERE question LIKE %kw% OR answer LIKE %kw%` |
| `create_ticket` | `description: str, ticket_type: str` | 写 tickets 表 |

**假数据必须确定性**：`random.Random(order_id)` 播种。同一订单号永远返回同样的物流，演示不飘、测试可断言。

**create_ticket 的 conversation_id 由执行器注入**，不让模型填——模型编不出真实会话 id。做法是工具工厂：`make_create_ticket(session, conversation_id)`，闭包持有上下文。

## 6. 工具基础设施

```python
class ToolRegistry:
    def register(tool)
    def get(name) -> BaseTool
    def all() -> list[BaseTool]
```

执行器 `run_tool(name, args) -> ToolResult`：

1. **参数校验**：`BaseTool.args_schema` 先 `model_validate`，不合法直接返回 `ToolResult(ok=False, error="参数不合法: ...")`，不调函数
2. **超时**：`asyncio.wait_for(..., timeout=settings.tool_timeout)`，默认 5s
3. **重试**：仅对超时与「可重试异常」重试，最多 `settings.tool_max_retries`（默认 1 次），退避 0.2s
4. **错误封装**：任何异常都转成 `ToolResult(ok=False, error=str(exc))`，绝不抛给上层

## 7. 编排：单轮工具调用

关键取舍：**不能让所有问题都先跑一趟不流式的「判断」**，否则「你好」这种普通问题也要多等一次完整推理。做法是让第一趟仍然流式，边流边判断。

```
第一趟（bind_tools 后 astream）
  ├─ 收到 content 分片      → 直接推 token 帧（ch01 的流式体验保持不变）
  ├─ 收到 tool_call_chunks  → 只累积，不推送（这是 JSON 碎片，推出去前端没法看）
  └─ 流结束
       ├─ gathered.tool_calls 为空 → 第一趟推出的 token 就是答案，直接 done
       └─ 非空 →
            推 tool 帧(running)
            执行工具（校验/超时/重试/错误封装）
            推 tool 帧(ok/error + 耗时)
            追加 AIMessage(tool_calls) + ToolMessage(结果) 到消息列表
            第二趟：不带 tools，astream，token 帧照推  ← 不 bind_tools，从根上杜绝二次调用
```

**边界情况**：模型偶尔会先吐一段文字再发起工具调用。此时文字已经推出去了，工具结果后会接着推更多文字。可以接受，但要保证 `done` 帧里的 `content` 是两段拼接的完整文本。

**失败兜底**（用户已选）：工具失败时把错误以 `ToolMessage` 回灌，并在第二趟的 system 指令里追加一条「工具调用失败，只能说明查询失败并建议转人工，不得编造结果」。

## 8. SSE 协议扩展

沿用 ch01 的三种帧，新增一种：

```
event: tool
data: {"name": "query_logistics", "args": {"order_id": 1001},
       "status": "running"}

event: tool
data: {"name": "query_logistics", "args": {"order_id": 1001},
       "status": "ok", "elapsed_ms": 82}

event: tool
data: {"name": "query_logistics", "args": {...},
       "status": "error", "error": "上游超时", "elapsed_ms": 5001}

event: token / done / error   # 与 ch01 一致
```

`done` 帧新增 `tools` 字段，回传本轮工具轨迹，供页面渲染徽章。

## 9. 落库

- 每轮对话：确认 `conversations` 有对应行（首次创建），写 `messages` 三条左右（user / assistant+tool_calls / tool）
- 只在整轮成功后落库，与 ch01「流失败不写历史」的约定一致
- `conversation_id` 即 ch01 的 `session_id`，映射成 int 后存

**注意**：ch01 的 `session_id` 是前端生成的字符串，本章 `conversations.id` 是自增 int。需要一个映射：首次请求时按 `user_id + session_key` 建 conversation，返回 int id。ch01 的进程内 `SessionStore` 继续用于上下文裁剪，数据库只做记录，不参与上下文组装。

## 10. 测试策略（用户已定：全部连真 MySQL）

- `pytest` 前置：连不上库就 `pytest.exit("MySQL 不可达，先 docker compose up -d")`，**不能让它表现为一堆红色的断言失败**
- 每个测试用事务回滚或清表，保证隔离
- 工具单测：假数据确定性、参数非法、超时、重试、错误封装
- 编排单测：用 FakeModel 产出构造好的 `tool_calls` chunk，断言执行顺序与帧序列
- 端到端：三条验收用 curl 跑

## 11. 已知限制

1. **「邮费是多少」查不出来是预期结果**（验收标准 3）。LIKE 关键词匹配对同义改写无能为力，这是本章的地板，下一步上向量检索解决。
2. 只做单轮工具调用，模型无法「调完一个再调一个」。
3. 无鉴权，`user_id` 是前端生成的匿名串。
4. 无 Alembic 迁移，建表靠 `create_all` + seed 脚本。生产环境需要补。
