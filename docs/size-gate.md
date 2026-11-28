# 减法门禁（size-gate）

> 目标：让代码体量与功能面**只允许下降**。做减法时用它兜底。

## 为什么需要它

arch-gate 保证结构正确，但不阻止代码越长越多。这个门禁反过来：
新增代码、新增端点、新增文件一律失败；删代码永远放行。

## 预算项

| 规则 | 含义 | 方向 |
|---|---|---|
| SIZE001 | backend/app 生产代码行数 | 只降 |
| SIZE002 | backend/app 生产代码文件数 | 只降 |
| SIZE003 | frontend/src 代码行数（.ts/.tsx） | 只降 |
| SIZE004 | frontend/src 样式行数（.css） | 只降 |
| SIZE005 | /api/v1 端点数量 | 只降 |
| SIZE006 | /ingest/v1 端点数量 | 只降 |
| SIZE007 | backend/app 模块级公开函数数量 | 只降 |
| SIZE008 | 测试文件数量 | **只升** |
| SIZE009 | 测试函数数量 | **只升** |
| SIZE010 | 新增端点前端无人调用 | 拦截 |
| SIZE011 | 允许清单条目已失效 | 拦截 |

## 当前预算（基线，2026-11-28）

| 项 | 值 |
|---|---|
| backend/app 行数 | 8981 |
| backend/app 文件数 | 90 |
| frontend/src 行数 | 9837 |
| frontend/src 样式行数 | 5279 |
| /api/v1 端点 | 53 |
| /ingest/v1 端点 | 28 |
| 公开函数 | 206 |
| 测试文件 | 14 |
| 测试函数 | 64 |

## 三个容易被绕过的点，已经堵住

**1. 删测试换减量**
如果只统计生产代码，删测试就能让指标变好看。所以 SIZE008/SIZE009 方向相反：删一个测试立刻失败。

**2. 调大预算**
`--update-budget` 检测到任何预算项被调大就返回 1，且**不修改文件**。只能收紧，不能放宽。

**3. 新增没人用的功能**
SIZE010 要求每个新端点在前端有对应调用。若确实供外部/AI 调用，加进 `size_budget.json` 的 `unused_endpoints`；条目失效会报 SIZE011，避免清单腐烂。

## 怎么做减法

```bash
# 1. 删代码 / 删功能
# 2. 收紧预算（这一步必须做，否则预算虚高）
cd backend
python tests/architecture/size_rules.py --root . --budget size_budget.json --update-budget
# 3. 提交
```

CI 在体量下降时会在日志里列出"哪些预算项可以收紧"。

## 当前已确认的 4 个死端点

前端零调用，可安全删除（已在 `unused_endpoints` 里登记）：

| 端点 | 位置 |
|---|---|
| `GET /projects/{id}/audit` | `app/api/v1/audit.py` |
| `GET /projects/{id}/findings/{fid}` | `app/api/v1/findings.py` |
| `GET /projects/{id}/runs/{ref}` | `app/api/v1/runs.py` |
| `GET /projects/{id}/summary` | `app/api/v1/projects.py` |

删掉后记得把它们从 `unused_endpoints` 移除，否则 SIZE011 会报失效。

## 改前端取数方式时

`size_rules.py` 用正则识别前端取数调用：

```python
_CALL_RE = re.compile(
    r"(?:request|fetchJson|fetchAllPages)\s*(?:<[^>]*>)?\s*\(\s*[`'\"]([^`'\"]+)[`'\"]"
)
```

新增别的取数封装（如 `fetchStream`）要同步加进这个正则，否则会把在用的端点误报成"无人调用"。

## 自检

门禁自身有 14 个自检用例，CI 里先跑自检再跑校验：

```bash
cd backend
python tests/architecture/size_selftest.py
```
