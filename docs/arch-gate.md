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
| 调大 `arch_baseline.json` | 基线只允许下调；`--update-baseline` 会打印警告 |

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

## 棘轮怎么用

`arch_baseline.json` 记录**当前违规数**。CI 要求实际数 `<=` 基线数。

- 新违规 → CI 失败
- 修掉违规 → 必须跑 `--update-baseline` 把基线收紧，否则基线虚高、后面可以偷偷加回来

```bash
cd backend
python tests/architecture/arch_rules.py --root . --baseline arch_baseline.json --update-baseline
```

## 临时抑制

```python
def legacy_thing():  # arch: ignore rule=ARCH001 reason=等 v0.3 合并路由 until=2027-03-01
    ...
```

三个字段缺一不可，且 `until` 过期后 CI 会失败。
