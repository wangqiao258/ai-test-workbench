# 架构门禁（arch-gate）

## 它解决什么

这个项目的模块化是**靠作者自觉维持**的，不是靠机制保障的。已知的三类问题：

1. `api/v1/projects.py` 横向 `from app.api.v1.runs import run_out`（路由互依赖）
2. `api/v1/` 与 `api/ingest/` 的 `_load_finding` / `_load_defect` / 列表组装**逐行重复**
3. `services/` 沦为杂物层：19 个文件里 6 个不足 1.3KB

单靠 code review 拦不住，因为**假修复看起来像真修复**。

## 假修复为什么过不了

| 假修复手法 | 检测结果 |
|---|---|
| 改函数名 | AST 归一化抹掉标识符，指纹不变 → 计数不降 |
| 改局部变量名 | 同上 → 计数不降 |
| 把重复代码挪到第三个文件 | 参与重复的函数数**增加** → 更糟 |
| `# arch: ignore` 批量消音 | 缺 `reason=` / `until=` 直接报错；有到期日，过期即失败 |
| 调大 `arch_baseline.json` | `--update-baseline` 直接拒绝写入并返回 1 |

## 规则表

| 规则 | 含义 |
|---|---|
| ARCH001 | api 层横向 import 其它 api 模块 |
| ARCH002 | services 反向 import api |
| ARCH003 | core 依赖外层 |
| ARCH004 | db 依赖外层 |
| ARCH005 | 跨文件精确重复代码 |
| ARCH006 | 结构性重复（改名即可绕过的那类） |
| ARCH007 | 路由函数承担查询编排（>4 次查询调用） |
| ARCH008 | service 模块退化为单函数仓储包装（<=40 行且 <=1 个公开函数） |
| ARCH009 | 前后端契约字段漂移 |
| ARCH900 | 基线被调大 |
| ARCH901 | 抑制注释无理由 / 无到期日 / 已过期 |

## 零容忍模式（当前配置）

`arch_baseline.json` 全部为 **0**。含义：

- **任何一条架构违规都会让 CI 立即失败**，没有存量豁免
- 修好之后无需改基线（它已经是 0，没有下调空间）
- `--update-baseline` 已禁用调大：只要检测到任何规则数量上升，直接拒绝写入并返回 1

也就是说，想让 CI 变绿，**只能真的把代码改对**，不存在"改个数字"的捷径。

当前待修（34 处，全部为存量）：

| 规则 | 数量 | 主要位置 |
|---|---|---|
| ARCH001 | 2 | `api/v1/auth.py` → `projects`；`api/v1/projects.py` → `runs` |
| ARCH005 | 10 | `_load_finding`/`_load_defect` 跨 API 面重复；`runs.py` 与 `agent_views.py` 三个函数重复 |
| ARCH006 | 7 | 7 个函数同一结构（`_load_*` / `get_*` 模板） |
| ARCH007 | 11 | 最重为 `projects.py:150 project_summary`（14 次查询调用） |
| ARCH008 | 4 | `services/projects.py`(13行)、`project_secrets.py`(16行) 等薄壳 |

修完一类后跑一次校验确认数量下降即可，不需要动基线文件。

## 临时抑制

```python
def legacy_thing():  # arch: ignore rule=ARCH001 reason=等 v0.3 合并路由 until=2027-03-01
    ...
```

三个字段缺一不可，且 `until` 过期后 CI 会失败。

注意：抑制注释会让 ARCH901 计数上升，零容忍模式下同样会导致 CI 失败。零容忍模式与抑制机制互斥 —— 如需抑制，必须同时调整基线，这相当于一次显式的、可审计的决策。
