# AI 协同测试工作台

[![CI](https://github.com/wangqiao258/ai-test-workbench/actions/workflows/ci.yml/badge.svg)](https://github.com/wangqiao258/ai-test-workbench/actions/workflows/ci.yml)

AI 机负责读取需求与接口、生成并执行测试用例、回写分析；平台负责资产索引、运行证据归档和人工审判。平台不克隆测试仓库、不执行测试，只接收索引、运行结果与证据。

## 组成

- `frontend/`：React 18 + TypeScript + Vite 单页应用
- `backend/`：FastAPI 服务、Alembic 迁移、pytest 插件 `pytest_workbench`

## 能力

- 项目、成员角色和项目级 API Token（scope 与预设由后端统一下发）
- 项目级测试仓库与用例索引：记录 `repo / ref / commit`，用例正文以 Git 为主来源
- 需求文档与 OpenAPI 契约的导入、编辑、删除与追溯；需求与接口不预先绑定
- 运行结果、日志、请求响应与 HAR 证据的接入和查询
- 外部 AI 分析结果落库，finding 人工审判；确认后生成 `DEF-xxxx` 缺陷编号并支持状态流转
- 发现 / 缺陷支持按编号只读查询分析上下文，包含用例、日志、HAR、需求与接口契约
- 测试凭据加密保存，pytest 插件启动时注入同名环境变量
- 项目设置：测试入口、测试仓库、AI 规则、接入令牌、测试凭据与项目删除

## 三机协作

| 机器 | 职责 | 说明 |
| --- | --- | --- |
| AI 机 | 读取需求 / 契约 / 历史运行，生成并执行用例，上传运行结果、证据与分析；可按编号读取发现 / 缺陷 | 需要被测系统凭据；平台 Token 用于上传、读取凭据与只读分析查询 |
| 平台机 | 运行本平台与 PostgreSQL，保存索引、运行结果与证据 | 不克隆测试仓库，不执行用例 |
| 被测机 | 运行被测试系统（SUT） | 由 AI 机访问 |

AI 机先调 `GET /ingest/v1/whoami`，按返回的 `project.entries`、`rules`、`actions` 执行；批量写入需要 `Idempotency-Key`。`entries` 只是测试入口信息，接口地址应以 OpenAPI server、实际请求或 HAR host 为准，不要用入口地址拼接 `operation.path`。

用例正文先 commit 并 push 到 `project.testRepo`，再调 `POST /ingest/v1/catalog` 上报索引；临时脚本用 `framework=script`，只保留运行与证据。

## 快速开始

### 后端

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # Windows 用 copy；修改 DATABASE_URL、JWT_SECRET
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
```

登录后在「项目设置 → 接入令牌」创建 Token（需项目管理员）。

### 前端

```bash
cd frontend
npm install
npm run dev
```

打开 http://127.0.0.1:5173，`/api` 与 `/ingest` 已代理到 `http://127.0.0.1:8000`。
<img width="1920" height="919" alt="image" src="https://github.com/user-attachments/assets/cecb9d79-417c-4810-bd26-9f4637b8c009" />

## AI 接入

- **项目 Token**：两个预设「测试权限」「资产管理」，完整 scope 由 `GET /api/v1/meta/token-scopes` 提供；写权限包含对应读权限。Token 用于 `/ingest/v1/*`。
- **发现 / 缺陷编号**：`FND-xxx`（AI 发现）、`DEF-xxxx`（确认后生成，按项目递增）。`GET /ingest/v1/findings/{FND}`、`GET /ingest/v1/defects/{DEF}` 返回发现 / 缺陷、批次、用例、日志、HAR、需求、接口契约与审判记录；`/runs/{run}/cases/{nodeid}`、`.../exchanges/{index}` 可按需读取单个用例或交换。
- **签名票据**：在页面点「复制给 AI」获取只读票据（`?ticket=`），默认 60 分钟有效，只绑定当前发现 / 缺陷及其用例，不能列表、不能写；`AI_TICKET_TTL_MINUTES` 可调整。
- **协议详情**：`/ingest/docs`（Swagger）、`/ingest/openapi.json`（只含 `/ingest/v1/*`）、`/openapi.json`（全量后台接口）。提示词可用：`先 GET /ingest/v1/whoami，按 project、rules 与 actions 执行`。

## 接口分区

- `/api/v1/*`：登录、项目 / 成员 / 令牌 / 凭据、资产、运行与证据、finding / defect、AI 票据签发
- `/ingest/v1/*`：AI 机与 pytest 插件的读写通道；支持项目 Token 或短时效票据，含发现 / 缺陷 / 证据只读查询
- `/healthz`：健康检查

## 配置与校验

- 配置见 `.env.example`：`DATABASE_URL`、`JWT_SECRET`、`SECRETS_KEY`、`ACCESS_LOG_*`、`AI_TICKET_TTL_MINUTES`
- 访问日志为 JSONL，按天切分；`token` / `ticket` 等敏感参数会脱敏
- 校验：

```bash
cd backend && ruff check . && pytest
cd frontend && npm run build
```

- GitHub Actions 在 push / PR 时执行以上检查，并在 Postgres 15 上从零执行 `alembic upgrade head`
- PostgreSQL 存结构化数据；`backend/storage/` 存请求响应 body、HAR 和截图等证据

## 环境要求

- Python >= 3.11
- Node.js 18+
- PostgreSQL 15（或兼容版本）
- 支持 pytest 插件、浏览器或代理导出的 HAR 证据

## License

[MIT](LICENSE)
