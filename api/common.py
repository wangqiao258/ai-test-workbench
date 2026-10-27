"""API 共用层：字段档位、通用列表查询、行转换。"""

import json

from flask import jsonify

from db import get_db
INTERFACE_FIELD_SETS = {
    "meta": ("id", "module", "name", "method", "path", "verify_status"),
    "contract": ("id", "project_id", "module", "name", "method", "path", "host",
                 "req_params", "resp_example", "error_codes", "notes",
                 "verify_status"),
    "full": None,
}

CASE_FIELD_SETS = {
    "summary": ("id", "project_id", "module", "title", "expected", "priority",
                "interface_id", "doc_id", "dims", "batch", "target_id",
                "generation_batch_id", "generation_strategy"),
    "full": None,
}

_COL_CACHE = {}

def json_dumps(v):
    return json.dumps(v, ensure_ascii=False)

def clear_table_cols_cache():
    """迁移后列可能变化，进程内缓存要清掉。"""
    _COL_CACHE.clear()


def table_cols(table):
    """表的实际列名（带缓存，bootstrap 里会清空）。用于增量迁移后的兼容判断。"""
    if table not in _COL_CACHE:
        conn = get_db()
        _COL_CACHE[table] = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        conn.close()
    return _COL_CACHE[table]

def pick_fields(field_sets, requested, default="full"):
    """把 ?fields= 映射成列元组；非法值回落到 default。"""
    key = (requested or default or "full").strip().lower()
    if key not in field_sets:
        key = default
    return field_sets[key], key

def api_list(table, filters=None, fields=None, order_by="id ASC", limit=None, offset=None):
    """通用列表查询。

    filters 形如 [(列名, 值)]，列名"__like"结尾表示前缀匹配（如 path__like）。
    列名一律由服务端字面量给出，不接受用户输入拼接。
    WHERE 与 args 必须同步构造——旧实现把 params 放在 args 最前面，
    与占位符顺序错位，导致 ?project_id=1&status=approved 恒返回空数组。
    """
    where, args = ["1=1"], []
    for col, val in (filters or []):
        if val is None or val == "":
            continue
        if val == "__null__":          # 只取该列为空的记录（如未挂接口的用例）
            where.append(f"{col} IS NULL")
            continue
        if col.endswith("__in"):       # IN 查询（如按关联表取一批 id）
            values = list(val)
            if not values:
                where.append("1=0")
                continue
            where.append(f"{col[:-4]} IN ({','.join('?' * len(values))})")
            args.extend(values)
            continue
        if col.endswith("__like"):
            where.append(f"{col[:-6]} LIKE ?")
            args.append(f"{val}%")
            continue
        where.append(f"{col}=?")
        args.append(val)
    cols = ", ".join(fields) if fields else "*"
    sql = f"SELECT {cols} FROM {table} WHERE " + " AND ".join(where)
    if order_by:
        sql += f" ORDER BY {order_by}"
    conn = get_db()
    total = conn.execute(
        f"SELECT COUNT(*) c FROM {table} WHERE " + " AND ".join(where), args
    ).fetchone()["c"]
    if limit:
        sql += " LIMIT ? OFFSET ?"
        args = args + [int(limit), int(offset or 0)]
    rows = rows_to_list(conn.execute(sql, args))
    conn.close()
    resp = jsonify(rows)
    if limit:
        resp.headers["X-Total-Count"] = str(total)
    return resp

def rows_to_list(rows):
    return [dict(r) for r in rows]


def as_id(v):
    """把 JSON 值归一成 id（int）或 None。

    兼容字符串数字（"5" -> 5，SQLite 亲和性本来就认）；bool / 对象 / 数组 /
    非数字字符串一律 None——交给调用方判"不存在"，别让 dict 撞 sqlite3
    InterfaceError 直接 500（2026-10-26 探针复现过）。
    """
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def check_project(conn, raw_pid):
    """校验 project_id：返回 (pid, err)。

    三类输入分别处理：缺/空 -> "必填"；非数字 -> "必须是数字"；数字但库里没有 ->
    "不存在"。没有这层校验时写操作会撞外键 IntegrityError 返回 HTML 500，
    调用方（AI）拿到 500 根本不知道该改什么。
    """
    if raw_pid in (None, ""):
        return None, "project_id 必填"
    pid = as_id(raw_pid)
    if pid is None:
        return None, "project_id 必须是数字"
    if not conn.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone():
        return None, f"project {pid} 不存在"
    return pid, None

