# AI 协同测试工作台

[![CI](https://github.com/wangqiao258/ai-test-workbench/actions/workflows/ci.yml/badge.svg)](https://github.com/wangqiao258/ai-test-workbench/actions/workflows/ci.yml)

AI 生成测试资产、执行 pytest、人工审判缺陷的测试工作台。接口用例由 pytest + Tavern 驱动，运行结果与真实请求响应作为证据留档，人只负责审 Bug 和管理项目。

## 组成

- `frontend/`：React 18 + TypeScript + Vite 单页应用
- `backend/`：FastAPI 服务、Alembic 迁移、pytest 插件 `pytest_workbench`

## 能力

- 项目、成员角色和项目级 API Token（按 scope 划分读写权限）
- 项目级测试凭据（加密存储，pytest 插件运行时注入环境变量）
- 前端导入 / 编辑 / 删除需求文档与 OpenAPI 契约（OpenAPI 3.x，JSON 或 YAML，支持 HEAD / OPTIONS / TRACE）
- 用例 / 需求 / OpenAPI 资产导入与追溯
- 用例规格在线编辑与删除、用例归档
- 运行结果、日志、请求响应、HAR 证据的接入与查询
- 外部 AI 分析结果落库，finding 人工审判
- 缺陷流转（`new → confirmed → fixing → fixed → closed`）与审计日志
- 项目资料修改与删除

## 三机协作

| 机器 | 职责 | 说明 |
| --- | --- | --- |
| AI 机 | 读取需求 / 契约 / 历史运行，产出并执行 pytest + Tavern YAML，上传运行结果、证据与分析 | 需要被测系统凭据；平台 Token 用于上传和读取测试凭据 |
| 平台机 | 运行本平台与 PostgreSQL，聚合运行结果与证据 | 不执行用例 |
| 被测机 | 运行被测试系统（SUT） | 被 AI 机访问 |

AI 机先调 `GET /ingest/v1/whoami`，按返回的 `project.baseUrl`、`start`、`actions` 执行；接口和 scope 细节见 `/ingest/docs`。每个 action 带 `detail`，参数、请求体和示例从 `/ingest/v1/actions/{step}` 取，不手写说明。

需求与接口不预先绑定。Tavern 用例在 `marks` 里声明需求：

```yaml
marks:
  - "workbench:requirement:A-01"
```

运行后平台按真实请求自动建立关联，`associations` 返回已测接口和置信度。不要读取全量 OpenAPI 或全量需求：摘要选接口，生成用例前取 `/operations/{id}` 详情。单轮通常 5-15K tokens。

### 测试凭据

在「项目设置 → 测试凭据」配置 `SUT_TOKEN`、`SUT_USERNAME`、`SUT_PASSWORD` 等名称。值加密保存、保存后不回显；`pytest_workbench` 启动时从平台读取并注入同名环境变量。pytest 用例用 `os.environ["SUT_TOKEN"]`，Tavern 用例用 `{tavern.env_vars.SUT_TOKEN}` 引用，不要把值写进 YAML 或代码。

最小提示词：

```text
平台 http://<host>:8000，Token: <X-Project-Token>。
先 GET /ingest/v1/whoami，按 project.baseUrl 和 actions 执行。
```

发现入口：`/ingest/docs`（Swagger）、`/ingest/openapi.json`（只含 `/ingest/v1/*`）、`/openapi.json`（全量后台接口）。写接口需要 `Idempotency-Key`。

## 快速开始

### 后端

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # 修改 DATABASE_URL、JWT_SECRET；生产环境同时配置 SECRETS_KEY
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

首次使用创建账号和项目：

```bash
python -m scripts.manage create-user --email you@example.com --name 你的名字
python -m scripts.manage create-project --name 商城接口 --base-url http://127.0.0.1:8080
python -m scripts.manage add-member --project 商城接口 --email you@example.com --role admin
```

登录后在「项目设置 → AI 接入」创建 Token。scope 与预设由 `GET /api/v1/meta/token-scopes` 提供，写/执行权限包含对应读权限；平台成员用 JWT，Token 只用于 `/ingest/v1/*`。

### 前端

```bash
cd frontend
npm install
npm run dev
```

打开 http://127.0.0.1:5173，`/api` 与 `/ingest` 已代理到 `http://127.0.0.1:8000`。

「01 需求与接口」右上角可直接导入需求 Markdown 与 OpenAPI 文档（JSON / YAML），导入后可在页面内编辑、删除；项目名称、被测服务地址、AI 接入令牌与项目删除在项目下拉菜单的「项目设置」中维护。

<img width="1912" height="948" alt="image" src="https://github.com/user-attachments/assets/c71f8e2f-f4a1-4159-a5c3-fc68681fe8d2" />

## 接口分区

- `/api/v1/*`：登录、项目、运行与证据、资产、finding / defect 查询与审判
- `/ingest/v1/*`：pytest 插件与 AI 机的读写通道，使用项目 Token；AI 通过 `/ingest/v1/runs` 上传运行结果
- `/healthz`：健康检查

## 访问日志

请求以 JSONL 写入 `logs/access.log`，按天切分，默认保留 90 天。关键字段：`ts`、`requestId`、`method`、`path`、`route`、`projectId`、`query`、`status`、`durationMs`、`auth`。响应头带 `X-Request-ID`。

`projectId` 由认证依赖写入，未认证请求为 `null`；日志目录已在 `.gitignore` 中忽略。配置见 `.env.example`：

```bash
ACCESS_LOG_PATH=logs/access.log
ACCESS_LOG_RETENTION_DAYS=90
```

```bash
jq -r 'select(.projectId == "<project-id>") | [.ts,.method,.path,.status,.durationMs] | @tsv' logs/access.log
```

默认不记录 JSON 请求体；测试流量的请求与响应证据保存在 `run` / `exchange` / `artifact`，变更记录在 `audit_log`。

## 版本号

- **git tag 是唯一来源**（如 `v0.2.0`），仓库里不再维护 `VERSION` 文件，也不再手工同步多个文件。
- 前端构建时用 `git describe --tags --dirty` 注入版本：正好在 tag 上显示 `v0.2.0`，tag 之后有提交显示 `v0.2.0+3.68e5b8e`，工作区有改动追加 `.dirty`。
- 后端由 `setuptools-scm` 生成包版本，运行时依次取 `APP_VERSION` 环境变量 → git tag → 安装元数据。
- 发布只需打 tag 并重新构建/部署：

```bash
git tag v0.2.0
git push origin v0.2.0
```

无 `.git` 的构建环境（Docker / 源码包）设置 `APP_VERSION=0.2.0` 即可覆盖；后端打包可设 `SETUPTOOLS_SCM_PRETEND_VERSION=0.2.0`。

## 校验

```bash
cd backend && ruff check . && pytest
cd frontend && npm install && npm run build
```

GitHub Actions 会在 push 和 PR 时自动执行以上检查，并在 Postgres 15 上从零执行 `alembic upgrade head`。

## 数据与配置

- PostgreSQL 存结构化数据；`backend/storage/` 存请求响应 body、HAR 和截图等证据
- `.env`、`storage/`、`.venv/`、`node_modules/` 不进仓库

## 环境要求

- Python >= 3.11
- Node.js 18+
- PostgreSQL 15（或兼容版本）
- HAR 采集依赖 [pytest-traffic-capture](https://github.com/wangqiao258/pytest-traffic-capture)

## License

[MIT](LICENSE)
