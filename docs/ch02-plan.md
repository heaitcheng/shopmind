# ch02 实施计划 · 工具调用接入客服聊天

> 输入：`docs/ch02-spec.md`（已定稿）
> 执行方式：**子代理驱动**。主代理只做编排与评审，不自己写业务代码。
> 每个任务派一个全新上下文的子代理，两段式评审（规格符合度 + 代码质量）都过才推进。

## 派活时必须带上的约束（每个任务都要复制进子代理的 prompt）

1. 模型固定 `glm-4.5-airx`，`thinking` 必须 `disabled`，**不许改 `.env`**。
2. 不许换技术栈。技术选型已定死：FastAPI + SQLAlchemy 异步 + MySQL + LangChain `@tool`。
3. 测试**连真 MySQL**（用户已定），前置条件 `docker compose up -d`。
4. 编排层测试一律用 `tests/conftest.py` 的 FakeModel，**不许发真实网络请求**。
5. 只做被要求的事，不顺手加缓存、加抽象、加"以后可能用到"的东西。
6. 改完必须自己跑验证命令，贴出输出，不许说"应该可以通过"。

## 前置（人工）

1. Docker Desktop 已启动，`docker info` 能返回 ServerVersion。
2. `.env` 追加 `DATABASE_URL`，形如：
   `mysql+aiomysql://shopmind:shopmind_pw@127.0.0.1:3306/shopmind?charset=utf8mb4`

---

# 阶段 A · 目录重构（不带任何功能改动）

## 任务 A1（已合并进 A2）

> 计划变更：A1 原为「新建四个空包 + `__init__.py`」，实测不到 1 分钟，单独派子代理的编排成本大于任务本身。合并进 A2 一起做。此改动记入 `dev-notes/ch02.md`。

## 任务 A2：建分层目录 + 迁移基础设施

- 文件：
  - 新建 `app/core/__init__.py`、`app/db/__init__.py`、`app/tools/__init__.py`、`app/api/__init__.py`
  - `git mv app/config.py app/core/config.py`
  - `git mv app/llm.py app/core/llm.py`
  - `git mv app/prompts.py app/core/prompts.py`
- 要做的：
  - 建四个包，移动三个文件（内容保持不变）
  - 同步改引用：`app/core/llm.py`、`app/service.py`、`app/main.py`、`tests/test_llm.py`、`tests/test_prompts.py`、`tests/test_service_extract.py`、`tests/test_service_stream.py`、`eval/run_extract_eval.py`
  - **不许顺手改任何逻辑**，只改 import 路径
- 验证：`pytest -q` 全绿（53 条）

## 任务 A3：路由抽出 main.py

- 文件：`app/api/routes.py`（新建）、`app/main.py`（改）
- 要做的：
  - 把 `/health`、`/api/chat/stream`、`/api/chat/extract`、`/api/chat/reset`、`/`、`sse()`、请求体模型、`store`、依赖函数全部搬到 `app/api/routes.py`
  - `main.py` 只保留：创建 app、`include_router`、导出 `app`
  - 注意：测试里 `app.main.app` 和 `app.main.get_chat_model`、`app.main.store` 被引用，要么在 main 里 re-export，要么同步改测试。**优先改测试**，不留 re-export 兜底
- 验证：`pytest -q` 全绿；`main.py` 行数 ≤ 40

## 任务 A4：重构确认

- 文件：无新增
- 要做的：全量跑测试 + 起服务冒烟
- 验证：`pytest -q` 全绿；`curl http://127.0.0.1:8000/health` 返回 ok；`curl -N -X POST .../api/chat/stream` 能看到 `event: token`
- 产出：单独一个提交 `refactor: 目录分层`，**不夹带任何功能改动**

---

# 阶段 B · 数据库

## 任务 B1：Docker MySQL 起起来

- 文件：`docker-compose.yml`
- 要做的：

```yaml
services:
  mysql:
    image: mysql:8
    container_name: shopmind-mysql
    environment:
      MYSQL_ROOT_PASSWORD: shopmind_root
      MYSQL_DATABASE: shopmind
      MYSQL_USER: shopmind
      MYSQL_PASSWORD: shopmind_pw
    ports:
      - "3306:3306"
    command:
      - --character-set-server=utf8mb4
      - --collation-server=utf8mb4_unicode_ci
    volumes:
      - shopmind_mysql:/var/lib/mysql
volumes:
  shopmind_mysql:
```

- 验证：`docker compose up -d` 后 `docker compose ps` 显示 healthy/running；`docker exec shopmind-mysql mysqladmin ping -uroot -pshopmind_root` 返回 `mysqld is alive`

## 任务 B2 + B3（合并执行）

> 计划变更：B2 只有 15 行，单独派子代理编排成本大于任务本身，与 B3 合并。此改动记入 `dev-notes/ch02.md`。

## 任务 B2：引擎与会话工厂

- 文件：`app/db/base.py`
- 要做的：

```python
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

def build_engine(url: str):
    return create_async_engine(url, pool_pre_ping=True, pool_recycle=1800)

def build_sessionmaker(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
```

- `app/core/config.py` 增加 `database_url: str`
- 验证：`python -c "from app.db.base import build_engine; print(build_engine('sqlite+aiosqlite://'))"` 能构造（不在本任务连真实库）

## 任务 B3：四张表

- 文件：`app/db/models.py`
- 要做的：按 spec 第 4 节定义 `Faq`、`Conversation`、`Message`、`Ticket`，全部 `mapped_column` 风格
  - `Message.role` 用 `String(16)` + CheckConstraint 限定 `user/assistant/tool`
  - `Message.tool_calls` 用 `JSON`
  - `Conversation.session_key` 唯一索引
  - 所有表 `__table_args__` 指定 `mysql_charset="utf8mb4"`、`mysql_collate="utf8mb4_unicode_ci"`
- 验证：`python -c "from app.db.models import Faq, Conversation, Message, Ticket; print('ok')"`；建表后 `SHOW TABLES` 四张齐全

## 任务 B4：灌测试数据

- 文件：`app/db/seed.py`
- 要做的：
  - `create_all` 建表
  - faq 灌 **15 条以上**，必须包含「退货政策」「邮费」相关条目。注意：**「邮费」故意只写「运费」相关表述，让「邮费是多少」查不出来**（验收标准 3 要求的预期漏召回）
  - 提供 `python -m app.db.seed` 入口，可重复执行（先清后灌）
- 验证：`python -m app.db.seed` 后 `SELECT COUNT(*) FROM faq` ≥ 15；`SELECT question FROM faq WHERE question LIKE '%退货%'` 有结果；`LIKE '%邮费%'` 无结果（这是设计）

## 任务 B5：测试夹具与前置检查

- 文件：`tests/conftest.py`（追加）、`tests/test_db_smoke.py`（新建）
- 要做的：
  - session 级 fixture 建 engine；连不上时 `pytest.exit("MySQL 不可达，先 docker compose up -d")`，**不要让它变成一堆红色断言失败**
  - function 级 fixture 在每个用例前后按外键顺序清表
  - 加一条冒烟测试：能建表、能插一条 faq、能查回来
- 验证：关掉 MySQL 时 `pytest` 输出那句中文提示并退出；打开时 `pytest -q` 全绿

---

# 阶段 C · 工具

## 任务 C1：注册表与执行器

- 文件：`app/tools/registry.py`、`tests/test_tool_registry.py`
- 要做的（TDD，先写测试）：
  - `ToolResult` dataclass：`ok: bool`、`data: str | None`、`error: str | None`、`elapsed_ms: int`
  - `ToolRegistry`：`register` / `get` / `all`，重名注册抛 ValueError
  - `async def run_tool(tool, args, timeout, max_retries) -> ToolResult`：
    1. `tool.args_schema.model_validate(args)` 失败 → `ok=False, error="参数不合法: ..."`，**不调用函数**
    2. `asyncio.wait_for(tool.ainvoke(validated), timeout)` 超时 → 重试 `max_retries` 次，仍超时则 `ok=False, error="执行超时"`
    3. 其他异常 → `ok=False, error=str(exc)`，**绝不向上抛**
    4. 成功 → `ok=True, data=json.dumps(结果, ensure_ascii=False)`
- 测试覆盖：非法参数不调函数、超时后重试、重试耗尽返回错误、普通异常被吞、成功路径带耗时
- 验证：`pytest -q tests/test_tool_registry.py` 全绿

## 任务 C2：三个假数据工具

- 文件：`app/tools/business.py`、`tests/test_tools_business.py`
- 要做的：
  - `query_order(order_id: int) -> dict`、`query_product(product_id: int) -> dict`、`query_logistics(order_id: int) -> dict`
  - 全部用 `random.Random(order_id)` 播种，**同一 id 必须永远返回同样内容**
  - docstring 写清用途与参数（docstring 就是给模型看的工具说明，必须写人话）
- 验证：`pytest -q tests/test_tools_business.py`；关键断言是「同一个 order_id 调两次结果完全相同」和「不同 order_id 结果不同」

## 任务 C3：query_faq

- 文件：`app/tools/faq.py`、`tests/test_tools_faq.py`
- 要做的：工厂函数 `make_query_faq(session)` 返回 `@tool`，内部 `SELECT ... WHERE question LIKE :kw OR answer LIKE :kw`，限 3 条
- 验证：`pytest -q tests/test_tools_faq.py`；「退货」能命中、「邮费」查空（预期）

## 任务 C4：create_ticket

- 文件：`app/tools/ticket.py`、`tests/test_tools_ticket.py`
- 要做的：工厂 `make_create_ticket(session, conversation_id)`，模型只填 `description` 和 `ticket_type`，`conversation_id` 由闭包注入；工单号 `TK{YYYYMMDD}-{4位序号}`
- 验证：`pytest -q tests/test_tools_ticket.py`；断言写库后能查到、`conversation_id` 正确、工单号格式对

---

# 阶段 D · 编排与接口

## 任务 D1：单轮工具编排

- 文件：`app/service.py`（追加 `stream_with_tools`）、`tests/test_service_tools.py`
- 要做的：按 spec 第 7 节实现两趟流程
  - 第一趟：`model.bind_tools(registry.all()).astream(...)`，content 分片推 token，`tool_call_chunks` 只累积
  - 无 tool_calls → 直接 done
  - 有 tool_calls → 推 tool 帧 → 执行 → 推结果帧 → 追加 `AIMessage(tool_calls)` + `ToolMessage`
  - 第二趟：**不 bind_tools**，astream 推 token
  - 累积 chunk 用 `gathered = chunk if gathered is None else gathered + chunk`
- 测试：FakeModel 能产出构造好的 `tool_call_chunks`；断言帧顺序、断言第二趟的 model 没有 tools 绑定
- 验证：`pytest -q tests/test_service_tools.py`

## 任务 D2：SSE 协议扩展

- 文件：`app/api/routes.py`、`tests/test_api_tools.py`
- 要做的：`tool` 帧四种状态（running/ok/error）、`done` 帧加 `tools` 字段
- 验证：`pytest -q tests/test_api_tools.py`；响应体里能 grep 到 `event: tool`

## 任务 D3：对话落库

- 文件：`app/db/repo.py`、`app/service.py`、`tests/test_repo.py`
- 要做的：
  - `get_or_create_conversation(session, session_key, user_id)`：按 `session_key` 查到就复用，否则建
  - 整轮成功后写 messages：user 一条、assistant（带 tool_calls 时存 JSON）一条、tool 一条
  - 失败/中断不写，与 ch01 约定一致
- 验证：`pytest -q tests/test_repo.py`；重跑同一 session_key 不会重复建 conversation

## 任务 D4：Prompt 加工具约束

- 文件：`app/core/prompts.py`
- 要做的：system prompt 增加
  - 「能查的先用工具查，不要凭印象答订单、物流、商品」
  - 「工具返回什么就说什么，不要补充工具没给的信息」
  - 「工具失败时只说明查询失败并建议转人工，禁止编造结果」
- 验证（**纯 Prompt，按约定用标注样例替代 TDD**）：`pytest -q tests/test_prompts.py` 断言三条都在；另用 5 条样例人工跑一遍（见任务 F1）

---

# 阶段 E · 前端（Vibe Coding，不套 TDD / code review）

## 任务 E1：工具轨迹徽章

- 文件：`static/index.html`
- 要做的：
  - 解析 `event: tool` 帧，在气泡上方渲染一个小徽章：`🔧 query_logistics(1001) · 82ms`
  - running 态显示进行中样式，ok/error 用不同颜色
  - `done` 帧的 `tools` 字段兜底渲染（防止前端漏接帧）
- 验证：浏览器实测三条验收；**由用户描述效果迭代**，不走 TDD

---

# 阶段 F · 验收与收尾

## 任务 F1：三条验收 + 已知限制

- 要做的：
  - 验收 1：问「订单 1001 的物流到哪了」→ 看到徽章 + 按结果作答
  - 验收 2：问「退货政策是什么」→ `query_faq` 命中并作答
  - 验收 3：问「邮费是多少」→ 查不出来（**预期**），把这条写进 `docs/ch02-spec.md` 已知限制
- 验证：三条 curl/浏览器记录贴进 dev-notes

## 任务 F2：收尾

- 全部测试绿、`dev-notes/ch02.md` 补齐阶段记录、README 更新、合并 main
