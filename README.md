# AI 协同测试工作台

[![CI](https://github.com/wangqiao258/ai-test-workbench/actions/workflows/ci.yml/badge.svg)](https://github.com/wangqiao258/ai-test-workbench/actions/workflows/ci.yml)

AI 生成测试资产、runner 执行、人工审判缺陷的测试工作台。接口用例由 pytest + Tavern 驱动，运行结果与真实请求响应作为证据留档，人只负责审 Bug 和管理项目。

## 组成

- `frontend/`：React 18 + TypeScript + Vite 单页应用
- `backend/`：FastAPI 服务、Alembic 迁移、pytest 插件 `pytest_workbench`、执行器 `workbench_runner`

## 能力

- 项目、成员角色和项目级 API Token
- 用例 / 需求 / OpenAPI 资产导入与追溯
- 运行结果、日志、请求响应、HAR 证据的接入与查询
- 外部 AI 分析结果落库，finding 人工审判
- 缺陷流转（`new → confirmed → fixing → fixed → closed`）与审计日志

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
python -m scripts.manage create-token --project shop-api --name local-pytest
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

打开 http://127.0.0.1:5173，`/api` 已代理到 `http://127.0.0.1:8000`。

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
