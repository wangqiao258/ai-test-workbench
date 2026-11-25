# AI 协同测试工作台

[![CI](https://github.com/wangqiao258/ai-test-workbench/actions/workflows/ci.yml/badge.svg)](https://github.com/wangqiao258/ai-test-workbench/actions/workflows/ci.yml)

AI 生成测试资产、runner 执行、人工审判缺陷的测试工作台。接口用例由 pytest + Tavern 驱动，运行结果与真实请求响应作为证据留档，人只负责审 Bug 和管理项目。

## 组成

- `frontend/`：React 18 + TypeScript + Vite 单页应用
- `backend/`：FastAPI 服务、Alembic 迁移、pytest 插件 `pytest_workbench`、执行器 `workbench_runner`

## 能力

- 项目、成员角色和项目级 API Token（按 scope 划分读写权限）
- 前端导入 / 编辑 / 删除需求文档与 OpenAPI 契约（OpenAPI 3.x，JSON 或 YAML，支持 HEAD / OPTIONS / TRACE）
- 用例 / 需求 / OpenAPI 资产导入与追溯
- 运行结果、日志、请求响应、HAR 证据的接入与查询
- 外部 AI 分析结果落库，finding 人工审判
- 缺陷流转（`new → confirmed → fixing → fixed → closed`）与审计日志
- 项目资料修改与删除

## 三机协作

| 机器 | 职责 | 说明 |
| --- | --- | --- |
| AI 机 | 只运行大模型，读取需求 / 契约 / 历史运行，产出 pytest + Tavern YAML | 不安装 pytest 插件、不执行用例；使用项目 Token 只读访问平台 |
| 平台机 | 运行本平台、PostgreSQL 与 pytest runner，执行用例并归档证据 | 唯一写入运行结果与证据的机器 |
| 被测机 | 运行被测试系统（SUT） | 只被平台机访问 |

AI 机交付 YAML 的两种方式：

1. **接口上传**：`POST /ingest/v1/specs`（scope `specs:write`）提交 `{"files":[{"path":"order/create.yaml","content":"..."}]}`，平台落盘到 `storage/specs/<project-key>/`；把 Platform 机上 runner 的 `WORKBENCH_RUNNER_SPEC_DIR` 指向该目录即可执行。
2. **仓库同步**：YAML 提交到代码仓库，平台机 `git pull` 到 `specs/` 后由 runner 执行。

AI 机读取上下文（项目 Token）：

- `GET /ingest/v1/assets/requirements`、`GET /ingest/v1/assets/openapi`（scope `assets:read`）
- `GET /ingest/v1/assets/runs?limit=20`（scope `runs:read`）

分析结果回写：`POST /ingest/v1/runs/{run_uuid}/analysis`（scope `analysis:write`）。
`pytest_workbench` 插件只在**平台机**上使用，AI 机无需安装。

### AI 机如何发现平台能力

- `GET /ingest/v1/whoami`：返回当前 Token 的 `scopes`、可用 `capabilities`（端点 → scope）与文档地址，AI 启动时先调一次即可知道能读能写什么。
- `GET /ingest/openapi.json`：只包含 `/ingest/v1/*` 的 OpenAPI 3.1，带 `ProjectToken`（`X-Project-Token`）鉴权声明。
- `GET /ingest/docs`：上述 spec 的 Swagger UI，可直接填 Token 调试。
- `GET /openapi.json` / `GET /docs`：全量后台接口（含 JWT 的 `/api/v1/*`），给平台前端与运维使用。

写接口需要 `Idempotency-Key` 请求头；复杂请求体（运行结果、分析结果、YAML 规格）在 `/ingest/docs` 中带有最小可跑示例。

## 快速开始

### 后端

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # 修改 DATABASE_URL、JWT_SECRET
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

首次使用创建账号、项目和 ingestion Token：

```bash
python -m scripts.manage create-user --email you@example.com --name 你的名字
python -m scripts.manage create-project --key shop-api --name 商城接口
python -m scripts.manage add-member --project shop-api --email you@example.com --role admin
python -m scripts.manage create-token --project shop-api --name local-pytest --scope ingest
```

Token scope 对照：

| scope | 允许的操作 |
| --- | --- |
| `ingest` | 历史兼容，等价于全部写权限 |
| `assets:read` | 读取需求 / OpenAPI 契约（AI 机只读上下文） |
| `assets:write` | 写入需求 / 契约 / 用例目录 |
| `runs:read` | 读取运行批次列表 |
| `runs:write` | 上传运行结果、证据、HAR |
| `analysis:write` | 写入 AI 分析结果与 finding |
| `specs:write` | 上传 pytest / Tavern YAML 规格 |

平台侧成员用 JWT 登录，不占用 Token scope；Token 只用于 `/ingest/v1/*`。

### 前端

```bash
cd frontend
npm install
npm run dev
```

打开 http://127.0.0.1:5173，`/api` 已代理到 `http://127.0.0.1:8000`。

「01 需求与接口」右上角可直接导入需求 Markdown 与 OpenAPI 文档（JSON / YAML），导入后可在页面内编辑、删除；项目名、仓库、环境、负责人与项目删除在项目下拉菜单的「项目设置」中维护。

<img width="1912" height="948" alt="image" src="https://github.com/user-attachments/assets/c71f8e2f-f4a1-4159-a5c3-fc68681fe8d2" />

### Runner

```bash
cd backend
python -m workbench_runner
```

配置见 `backend/.env.example` 中的 `WORKBENCH_RUNNER_*` 和 `WORKBENCH_PROJECT_TOKENS`。

## 接口分区

- `/api/v1/*`：登录、项目、运行与证据、资产、finding / defect 查询与审判
- `/ingest/v1/*`：pytest 插件与 runner 的写入通道，使用项目 Token
- `/healthz`：健康检查

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
`frontend/package.json` 的 `version` 固定为 `0.0.0`，仅作为私有包的占位，不参与显示。

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
