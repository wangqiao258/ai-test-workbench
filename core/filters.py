"""列表页的统一筛选与分页规则（纯函数，无 IO）。

每个列表面板只用一份 spec 声明"能筛什么"，这里负责三件事：
1. 从 query string 取值并按词表校验——手改 URL 造不出全空的结果页
2. 拼 WHERE 片段：值一律走 ? 占位，列名只来自 spec，不接受外部输入
3. 回填状态、已启用筛选项、分页窗口，供模板直接渲染

四+一种字段能力：
    eq         精确等于，可带 vocab 白名单
    like       子串匹配（cases.dims 这种 JSON 数组字段用它）
    like_multi 一个关键字同时搜多列，OR 连接
    map        取值映射成 SQL 片段（默认视图、"全部"、IS NULL 这类语义）
    multi=True 加在 eq 上表示可多选：?module=A&module=B → module IN (?,?)

设计取舍：不引入 ORM、不拼列名到 SQL。spec 是代码里的常量，URL 只影响值。
"""
from dataclasses import dataclass
from math import ceil
from urllib.parse import parse_qsl, urlencode

LIKE_ESC = "\\"


@dataclass(frozen=True)
class Field:
    """一个可筛字段。mapping 用 ((值, SQL, 参数元组), ...) 保留可哈希。

    multi=True 只对 eq 有意义：取值走 getlist，SQL 变成 IN (?,?,...)，
    单选字段的 state 仍是字符串，多选字段的 state 是 tuple。
    """
    name: str
    kind: str = "eq"
    col: str = ""
    cols: tuple = ()
    vocab: tuple = ()
    mapping: tuple = ()
    default: str = ""
    label: str = ""
    multi: bool = False

    def __post_init__(self):
        if self.kind not in ("eq", "like", "like_multi", "map"):
            raise ValueError(f"未知筛选类型: {self.kind}")
        if self.kind in ("eq", "like") and not self.col:
            raise ValueError(f"{self.name} 缺少 col")
        if self.kind == "like_multi" and not self.cols:
            raise ValueError(f"{self.name} 缺少 cols")
        if self.kind == "map" and not self.mapping:
            raise ValueError(f"{self.name} 缺少 mapping")
        if self.multi and self.kind != "eq":
            raise ValueError(f"{self.name}: multi 只能配 eq")


def escape_like(value):
    """转义 LIKE 通配符；调用方需配 ESCAPE '\\'。"""
    return (value.replace("\\", "\\\\").replace("%", "\\%")
            .replace("_", "\\_"))


def getlist(args, name):
    """取一个参数的全部值：request.args 是 MultiDict，普通 dict 只有单值。

    空串（?module=）当没传——多选框全不勾时浏览器仍会发一个空值。
    """
    getter = getattr(args, "getlist", None)
    if getter is not None:
        return [v.strip() for v in getter(name) if v and v.strip()]
    v = (args.get(name) or "").strip()
    return [v] if v else []


def build(spec, args):
    """按 spec 解析 args，返回 {where, params, state, active, labels}。

    where 里每个片段都已用 AND 连接好，调用方只需再加自己的固定条件
    （如 project_id=?），并把 params 按同样顺序拼上去。
    """
    where, params, state, active, labels = [], [], {}, [], {}
    for f in spec:
        if f.kind == "map":
            raw = (args.get(f.name) or "").strip()
            if not raw:
                raw = f.default
            table = {k: (sql, ps) for k, sql, ps in f.mapping}
            if raw not in table:
                raw = f.default
            sql, ps = table.get(raw, ("", ()))
            state[f.name] = raw
            if sql and sql != "1=1":
                where.append(f"({sql})")
                params.extend(ps)
            if raw != f.default:
                active.append(f.label or f.name)
            continue

        if f.multi:
            vals = getlist(args, f.name)
            if not vals and f.default:
                vals = [f.default]
            # 词表外的一律丢掉；全被丢掉等于没传（沿用单选的既有规则）
            if f.vocab and vals:
                vals = [v for v in vals if v in f.vocab]
            vals = list(dict.fromkeys(vals))   # 去重但保留用户勾选顺序
            state[f.name] = tuple(vals)
            if not vals:
                continue
            if len(vals) == 1:
                where.append(f"{f.col}=?")
                params.append(vals[0])
            else:
                where.append(f"{f.col} IN ({','.join('?' * len(vals))})")
                params.extend(vals)
            if tuple(vals) != ((f.default,) if f.default else ()):
                label = f.label or f.name
                active.append(f"{label}（{len(vals)} 个）" if len(vals) > 1 else label)
            continue

        raw = (args.get(f.name) or "").strip()
        if not raw:
            raw = f.default

        # 词表外的一律当没传：避免 ?dtype=xxx 得到空页还不知道为什么
        if f.vocab and raw and raw not in f.vocab:
            raw = ""
        if not raw:
            state[f.name] = f.default
            continue

        if f.kind == "eq":
            where.append(f"{f.col}=?")
            params.append(raw)
        elif f.kind == "like":
            where.append(f"{f.col} LIKE ? ESCAPE '{LIKE_ESC}'")
            params.append(f"%{escape_like(raw)}%")
        else:  # like_multi
            ors = " OR ".join(f"{c} LIKE ? ESCAPE '{LIKE_ESC}'" for c in f.cols)
            where.append(f"({ors})")
            params.extend([f"%{escape_like(raw)}%"] * len(f.cols))

        state[f.name] = raw
        if raw != f.default:
            active.append(f.label or f.name)

    for f in spec:
        if f.label:
            labels[f.name] = f.label
    return {"where": where, "params": params, "state": state,
            "active": active, "labels": labels}


def paginate(total, page, per_page):
    """算出分页窗口；页码越界自动钳到有效范围。"""
    total = max(0, int(total or 0))
    per_page = max(1, int(per_page or 50))
    try:
        page = int(page or 1)
    except (TypeError, ValueError):
        page = 1
    pages = max(1, ceil(total / per_page))
    page = min(max(1, page), pages)
    offset = (page - 1) * per_page
    return {"page": page, "per_page": per_page, "total": total, "pages": pages,
            "offset": offset,
            "start": offset + 1 if total else 0,
            "end": min(offset + per_page, total),
            "has_prev": page > 1, "has_next": page < pages}


# 详情页"返回列表"允许携带的参数：只认这些，防止 back= 变成外部跳转
BACK_KEYS = ("tab", "module", "method", "q", "page", "priority", "dim",
             "result", "anchor", "dtype", "progress", "b_severity",
             # group 是模块的一级分组（侧边栏 / 家长端）：从详情页返回要能复原
             "group",
             "env", "view", "actor", "action", "apage",
             # sel 是分栏右栏当前选中的 Bug：从详情页办完审核跳回来时要能复原
             "sel",
             # 审核队列（跨项目）的前端筛选键，审完一条要能回到同一组筛选
             # fs = 进度（待审核 / 待上报）
             "fp", "fe", "fv", "fq", "fs")


def clean_qs(raw):
    """把 back 参数洗成只含白名单键的查询串。"""
    if not raw:
        return ""
    pairs = [(k, v) for k, v in parse_qsl(raw, keep_blank_values=False)
             if k in BACK_KEYS]
    return urlencode(pairs)


def qs_with(args, **overrides):
    """在当前 query 上覆盖若干参数，生成新查询串；空值等于删除该参数。

    多值参数（?module=A&module=B）原样保留：原来用 dict(args.items()) 会把
    重复键压成一个，翻页和"点模块名只看该模块"时就静默丢掉多选。
    """
    pairs = []
    getlists = getattr(args, "lists", None)
    for k, vs in (getlists() if getlists else
                  [(k, [v]) for k, v in args.items()]):
        if k in overrides:
            continue
        pairs.extend((k, str(v)) for v in vs if v not in (None, ""))
    for k, v in overrides.items():
        if v is None or v == "":
            continue
        if isinstance(v, (list, tuple)):
            pairs.extend((k, str(x)) for x in v if x not in (None, ""))
        else:
            pairs.append((k, str(v)))
    return urlencode(pairs)
