# AI 协同测试工作台

[![CI](https://github.com/wangqiao258/ai-test-workbench/actions/workflows/ci.yml/badge.svg)](https://github.com/wangqiao258/ai-test-workbench/actions/workflows/ci.yml)

AI 机负责读取需求与接口、生成并执行测试用例、回写分析；平台负责资产索引、运行证据归档和人工审判。平台不克隆测试仓库、不执行测试，只接收索引、运行结果与证据。

## 组成

- `frontend/`：React 18 + TypeScript + Vite 单页应用
- `backend/`：FastAPI 服务、Alembic 迁移、pytest 插件 `pytest_workbench`

## 能力

- 项目、成员角色和项目级 API Token（按 scope 划分读写权限）
- 项目级测试仓库与用例索引：记录 `repo / ref / commit`，用例正文以 Git 为主来源
- 用例库接受任意框架名，推荐 `pytest`、`tavern`、`postman`、`playwright`、`cypress`；`script` 仅用于临时脚本，不进入用例库
- 项目级 AI 规则：默认规则由后端下发，项目可在设置页覆盖或恢复
- 需求文档与 OpenAPI 契约的导入、编辑、删除与追溯
- 可选的 pytest / Tavern YAML 规格上传、在线编辑与用例归档
- 运行结果、日志、请求响应与 HAR 证据的接入和查询
- 外部 AI 分析结果落库，finding 人工审判；确认后生成 `DEF-1001` 这类缺陷编号
- 发现 / 缺陷支持按编号只读查询分析上下文：批次、用例、日志、完整 HAR、需求与接口契约
- 缺陷流转（`new → confirmed → fixing → fixed → closed`）与审计日志
- 项目资料、测试仓库、AI 规则、接入令牌、测试凭据与项目删除

## 三机协作

| 机器 | 职责 | 说明 |
| --- | --- | --- |
| AI 机 | 读取需求 / 契约 / 历史运行，生成用例并提交到测试仓库，执行测试，上传运行结果、证据与分析；可按 FND / DEF 编号读取发现与缺陷上下文 | 需要被测系统凭据；平台 Token 用于上传、读取测试凭据与只读分析查询 |
| 平台机 | 运行本平台与 PostgreSQL，保存需求 / 接口 / 用例索引、运行结果与证据 | 不克隆测试仓库，不执行用例 |
| 被测机 | 运行被测试系统（SUT） | 由 AI 机访问 |

AI 机先调 `GET /ingest/v1/whoami`，读取 `project.entries`、`project.testRepo`、`rules`、`actions` 和 `secrets`。动作参数、请求体和示例从 `/ingest/v1/actions/{step}` 获取；批量写入需要 `Idempotency-Key`，以 `action.detail` 为准。`actions` 中的 `list_pending_findings`、`read_finding`、`read_defect` 用于只读分析查询。

`project.entries` 是测试入口信息（名称 / 地址 / 备注），可能包含页面或接口，不保证就是接口基准地址。AI 应以 OpenAPI 文档的 server、实际请求或 HAR 中出现的 host 判断接口地址，不要用入口地址直接拼接 `operation.path`。

用例正文先 commit 并 push 到 `project.testRepo`，再调 `POST /ingest/v1/catalog` 上报索引与 `source(repo/ref/commit)`。`catalog` 只写索引，不要只上报不落仓库；临时脚本用 `framework=script`，只保留运行与证据。

### 需求与接口关联

需求与接口不预先绑定：

- 需求关联来自用例索引的 `requirements`，或 Tavern marks 中的 `workbench:requirement:<需求ID>`。
- 接口关联在运行上传后，按最近一次运行的真实 `method + path` 匹配 OpenAPI operation；`associations` 返回已测接口与置信度，置信度按关联用例数分级。

按需读取：摘要用于选接口，生成用例前再取 `/operations/{id}` 详情；不要全量拉取 OpenAPI 或需求。

### 运行证据

HAR 只接收有效证据：合法 JSON，`log.entries` 为数组，且至少包含一条 http(s) 的 XHR / Fetch 请求；标注为 document / script / stylesheet / image 等静态资源的条目会被跳过。解析后没有有效请求的 HAR 会判定为失败，不会覆盖该用例已有证据。

### AI 分析查询

发现和缺陷有稳定编号：`FND-003`（AI 发现）、`DEF-1001`（确认后生成，按项目递增）。外部 AI 可按编号读取分析上下文：

- `GET /ingest/v1/findings/{FND}`、`GET /ingest/v1/defects/{DEF}`：一次返回发现 / 缺陷本体、批次、用例、错误与日志、完整 HAR、关联需求、接口契约、接口候选、审判记录和运行级分析。
- `GET /ingest/v1/runs/{run}/cases/{nodeid}`、`.../exchanges/{index}`：按需读取单个用例或交换。
- 认证可用 `X-Project-Token`（要求 `runs:read`，带 `assets:read` 时返回需求与契约），或在页面点「复制给 AI」获取只读签名票据（`?ticket=`）。票据默认 60 分钟有效，只绑定当前发现 / 缺陷及其用例，不能列表、不能读其他资源、不能写；`AI_TICKET_TTL_MINUTES` 可调整有效期。
- 请求 / 响应 body 默认每段截断 4KB，`?body_limit=0` 可取全文。
- 访问日志会脱敏 `ticket` 参数。

### 测试凭据

在「项目设置 → 测试凭据」配置 `SUT_TOKEN`、`SUT_USERNAME`、`SUT_PASSWORD` 等名称。值加密保存，可在设置页查看和复制；`pytest_workbench` 启动时从平台读取并注入同名环境变量。pytest 用例用 `os.environ["SUT_TOKEN"]`，Tavern 用例用 `{tavern.env_vars.SUT_TOKEN}` 引用，不要把值写进 YAML 或代码。

最小提示词：

```text
平台 http://<host>:8000，Token: <X-Project-Token>。
先 GET /ingest/v1/whoami，按返回的 project、rules 与 actions 执行。
```

发现入口：`/ingest/docs`（Swagger）、`/ingest/openapi.json`（只含 `/ingest/v1/*`）、`/openapi.json`（全量后台接口）。

## 快速开始

### 后端

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # Windows 用 copy；修改 DATABASE_URL、JWT_SECRET；生产环境同时配置 SECRETS_KEY
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

首次使用创建账号和项目：

```bash
python -m scripts.manage create-user --email you@example.com --name 你的名字
# --entry 可重复，用于多个测试入口
python -m scripts.manage create-project --name 商城接口 \
  --entry 商城前端=http://127.0.0.1:8080
python -m scripts.manage add-member --project 商城接口 --email you@example.com --role admin
# 也可在项目设置页创建 Token
python -m scripts.manage create-token --project 商城接口 --name local-pytest
```

登录后在「项目设置 → 接入令牌」创建 Token（需项目管理员）。当前提供两个预设：**测试权限**（读资产、报用例目录、传规格、读凭据、上传运行与写分析）和 **资产管理**（读写需求与 OpenAPI）。scope 与预设由 `GET /api/v1/meta/token-scopes` 提供，写 / 执行权限包含对应读权限；平台成员用 JWT，项目 Token 用于 `/ingest/v1/*`（含发现 / 缺陷只读查询）。

### 前端

```bash
cd frontend
npm install
npm run dev
```

打开 http://127.0.0.1:5173，`/api` 与 `/ingest` 已代理到 `http://127.0.0.1:8000`。

「01 需求与接口」支持直接导入需求 Markdown 与 OpenAPI 文档（JSON / YAML），导入后可在页面内编辑、删除。项目名称、测试入口、测试仓库、AI 规则、接入令牌、测试凭据与项目删除在「项目设置」中维护。

## 接口分区

- `/api/v1/*`：登录、项目 / 成员 / 令牌 / 凭据、资产、运行与证据、finding / defect 查询与审判、AI 查询票据签发
- `/ingest/v1/*`：AI 机与 pytest 插件的读写通道；使用项目 Token 或短时效票据，支持发现 / 缺陷 / 证据只读查询
- `/healthz`：健康检查

## 访问日志

请求以 JSONL 写入 `logs/access.log`，按天切分，默认保留 90 天。记录包含 `ts`、`requestId`、`method`、`path`、`route`、`projectId`、`query`、`status`、`durationMs`、`auth` 等字段；响应头带 `X-Request-ID`。默认不记录请求体。`token`、`ticket` 等敏感 query 参数会脱敏，票据请求的 `auth` 标记为 `ticket`。

配置见 `.env.example`：

```bash
ACCESS_LOG_PATH=logs/access.log
ACCESS_LOG_RETENTION_DAYS=90
```

```bash
jq -r 'select(.projectId == "<project-id>") | [.ts,.method,.path,.status,.durationMs] | @tsv' logs/access.log
```

请求与响应证据在运行证据中查看，变更记录在审计日志中。

## 版本号

`git tag` 是唯一来源（如 `v0.2.0`）。前端构建和后端运行时都从 tag 解析版本；无 `.git` 的构建环境可用 `APP_VERSION` 覆盖。发布：

```bash
git tag v0.2.0
git push origin v0.2.0
```

## 校验

```bash
cd backend && ruff check . && pytest
cd frontend && npm run build
```

GitHub Actions 会在 push 和 PR 时执行以上检查，并在 Postgres 15 上从零执行 `alembic upgrade head`。

## 数据与配置

- PostgreSQL 存结构化数据；`backend/storage/` 存请求响应 body、HAR 和截图等证据
- 「复制给 AI」签名票据默认 60 分钟有效，可通过 `AI_TICKET_TTL_MINUTES` 调整
- `.env`、`storage/`、`.venv/`、`node_modules/` 不会进入仓库

## 环境要求

- Python >= 3.11
- Node.js 18+
- PostgreSQL 15（或兼容版本）
- HAR 采集由 [pytest-traffic-capture](https://github.com/wangqiao258/pytest-traffic-capture) 提供，已包含在后端依赖中；也支持浏览器或代理导出的 HAR 文件

## License

[MIT](LICENSE)
