"""数据库层：SQLite schema 与访问助手。"""
import os
import sqlite3
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "app.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS environments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    name TEXT NOT NULL,
    base_url TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    env_id INTEGER REFERENCES environments(id),
    label TEXT NOT NULL DEFAULT '',
    username TEXT NOT NULL DEFAULT '',
    password TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    dtype TEXT NOT NULL DEFAULT 'general',  -- interface / page / flow / general
    title TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    -- 文档免审（2026-10-22 移除 status / review_comment）：
    -- AI 写的是给下一次会话读的交接笔记，人从不逐条看，审核只是空转。
    created_by TEXT NOT NULL DEFAULT 'user',
    evidence TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
-- AI 持续生成：批次只负责分组，测试目标才记录"还有什么没验证"。
CREATE TABLE IF NOT EXISTS generation_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    strategy TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',     -- open / finished
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    finished_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS test_targets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    module TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    intent TEXT NOT NULL,                   -- 具体要验证的风险，不是泛泛的"补边界"
    strategy TEXT NOT NULL DEFAULT 'breadth',
    priority TEXT NOT NULL DEFAULT 'P2',
    status TEXT NOT NULL DEFAULT 'open',    -- open/claimed/generated/covered/blocked/deferred
    interface_id INTEGER REFERENCES interfaces(id),
    doc_id INTEGER REFERENCES docs(id),
    parent_target_id INTEGER REFERENCES test_targets(id),
    source_ref TEXT NOT NULL DEFAULT '',    -- 参数、文档段落、Bug 等来源定位
    generation_batch_id INTEGER REFERENCES generation_batches(id),
    claimed_by TEXT NOT NULL DEFAULT '',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_result TEXT NOT NULL DEFAULT '',
    feedback TEXT NOT NULL DEFAULT '',
    fingerprint TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    covered_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    module TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    preconditions TEXT NOT NULL DEFAULT '',
    steps TEXT NOT NULL DEFAULT '',
    steps_json TEXT NOT NULL DEFAULT '',   -- 结构化步骤（kind/steps[action,request,expect]），steps 由它渲染
    expected TEXT NOT NULL DEFAULT '',
    priority TEXT NOT NULL DEFAULT 'P2',
    -- 用例免审：不再有 status / review_comment（2026-10-22 移除）
    source TEXT NOT NULL DEFAULT 'manual',  -- ai / manual
    target_id INTEGER REFERENCES test_targets(id),
    generation_batch_id INTEGER REFERENCES generation_batches(id),
    generation_strategy TEXT NOT NULL DEFAULT '',
    intent_fingerprint TEXT NOT NULL DEFAULT '',
    novelty TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS case_interfaces (
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    interface_id INTEGER NOT NULL REFERENCES interfaces(id),
    PRIMARY KEY (case_id, interface_id)      -- 一条用例可覆盖多个接口
);
CREATE TABLE IF NOT EXISTS executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES cases(id),
    result TEXT NOT NULL,              -- pass / fail / blocked
    step_results TEXT NOT NULL DEFAULT '',  -- JSON: [{no, result, actual}]
    intent_fingerprint TEXT NOT NULL DEFAULT '', -- 执行时的用例行为版本，修改后旧结果不算覆盖
    actual_result TEXT NOT NULL DEFAULT '',
    evidence TEXT NOT NULL DEFAULT '',
    executed_by TEXT NOT NULL DEFAULT 'ai',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bugs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    case_id INTEGER REFERENCES cases(id),
    title TEXT NOT NULL,
    module TEXT NOT NULL DEFAULT '',
    severity TEXT NOT NULL DEFAULT 'normal', -- critical / major / normal / minor
    steps TEXT NOT NULL DEFAULT '',
    review_status TEXT NOT NULL DEFAULT 'pending', -- pending / approved / rejected
    reported_at TEXT NOT NULL DEFAULT '',    -- 已抄进公司在线表格的时间；空=还没上报
    created_by TEXT NOT NULL DEFAULT 'user',
    evidence TEXT NOT NULL DEFAULT '',
    review_comment TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS interfaces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    module TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    method TEXT NOT NULL DEFAULT 'GET',
    path TEXT NOT NULL,
    host TEXT NOT NULL DEFAULT '',          -- 接口独立域名（空=继承项目环境 base_url）
    req_headers TEXT NOT NULL DEFAULT '',   -- JSON: [{name, required, desc, example}]
    req_params TEXT NOT NULL DEFAULT '',    -- JSON: [{name, type, required, desc, example}]
    resp_example TEXT NOT NULL DEFAULT '',
    error_codes TEXT NOT NULL DEFAULT '',   -- JSON: [{code, desc}]
    notes TEXT NOT NULL DEFAULT '',
    evidence TEXT NOT NULL DEFAULT '',
    verified_at TEXT NOT NULL DEFAULT '',
    -- 接口免审（2026-10-22 移除 status / review_comment）：
    -- 质量只有一个轴——"这份契约是否经过实测"：verified / unverified / changed
    verify_status TEXT NOT NULL DEFAULT 'unverified',
    created_by TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    linked_type TEXT NOT NULL DEFAULT '',  -- bug / execution / doc
    linked_id INTEGER,
    created_at TEXT NOT NULL
);
-- 数据包证据（2026-10-22）：一次实测的完整请求 + 完整响应。
-- 取代原来把报文塞进 evidence 一个文本框的做法——那导致 161 条接口里
-- 只有 22% 能复核，最短的 evidence 是 10 个字符 "GET -> 200"。
-- 响应体超过 8KB 落盘（resp_body_file），DB 只存引用，绝不截断。
CREATE TABLE IF NOT EXISTS packets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    linked_type TEXT NOT NULL DEFAULT '',   -- interface / bug / execution
    linked_id INTEGER,
    label TEXT NOT NULL DEFAULT '',         -- 这次抓包的场景说明（人读）
    req_method TEXT NOT NULL DEFAULT '',
    req_url TEXT NOT NULL DEFAULT '',       -- 完整地址，含 query
    req_query TEXT NOT NULL DEFAULT '',     -- JSON 或原串
    req_headers TEXT NOT NULL DEFAULT '',   -- JSON: {name: value}
    req_body TEXT NOT NULL DEFAULT '',
    resp_status INTEGER,
    resp_headers TEXT NOT NULL DEFAULT '',  -- JSON: {name: value}
    resp_body TEXT NOT NULL DEFAULT '',     -- 小响应内联；大响应留空走 resp_body_file
    resp_body_file TEXT NOT NULL DEFAULT '',-- 相对 UPLOAD_DIR，如 packets/ab12...-114471.txt
    resp_chars INTEGER NOT NULL DEFAULT 0,  -- 响应体原始字符数（落盘后仍是全量）
    resp_bytes INTEGER NOT NULL DEFAULT 0,  -- 响应体原始字节数
    duration_ms INTEGER,
    sha256 TEXT NOT NULL DEFAULT '',        -- 响应体指纹，用于比对两次实测是否同包
    completeness TEXT NOT NULL DEFAULT 'partial',  -- full / partial，服务端算
    missing TEXT NOT NULL DEFAULT '',       -- 缺了什么（人读）
    created_by TEXT NOT NULL DEFAULT '',
    captured_at TEXT NOT NULL DEFAULT '',   -- 抓包时刻（可空=入库时刻）
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS modules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    name TEXT NOT NULL,
    sort INTEGER NOT NULL DEFAULT 100,
    UNIQUE(project_id, name)          -- 项目级受控词表：同一个 module 只有一个写法
);
-- 执行批次（P1）：一次 run = 一轮要跑的用例集合。
-- 没有它，"这一轮跑了哪些、跳过哪些、和上轮比怎样"在平台上答不出来——
-- executions 只有"某条用例某次结果"，没有"轮"这个单位。
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    name TEXT NOT NULL DEFAULT '',          -- 人读，如 "接口回归-会员侧 第3轮"
    scope TEXT NOT NULL DEFAULT '',         -- JSON: {"batch":...} | {"module":[...]} | {"case_ids":[...]} | {"group":...}
    trigger TEXT NOT NULL DEFAULT 'ai',     -- ai / manual
    kind TEXT NOT NULL DEFAULT 'regression',-- regression / selfcheck / diagnostic（这轮的性质）
    reason TEXT NOT NULL DEFAULT '',        -- 为什么跑
    status TEXT NOT NULL DEFAULT 'queued',  -- queued / running / done / failed
    baseline_run_id INTEGER,                -- 对比基准（P2 用）
    summary TEXT NOT NULL DEFAULT '',       -- JSON: {total,pass,fail,blocked,skipped}
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT '',
    finished_at TEXT NOT NULL DEFAULT '',
    -- 执行观测（2026-10-23）：谁认领的、最后一次有生命迹象、人工取消的原因。
    -- 只增不删；老数据留空，僵死判定会退回 started_at。
    runner_id TEXT NOT NULL DEFAULT '',
    last_heartbeat_at TEXT NOT NULL DEFAULT '',
    cancel_note TEXT NOT NULL DEFAULT ''
);
-- 项目级配置（P1 先用于 runner 鉴权；P2 加 diff_mask）。
-- 引擎零硬编码的落点：登录接口、租户头、token 路径都是数据，不是代码。
CREATE TABLE IF NOT EXISTS project_settings (
    project_id INTEGER NOT NULL REFERENCES projects(id),
    key TEXT NOT NULL,                      -- auth / diff_mask / ...
    value TEXT NOT NULL DEFAULT '',         -- JSON
    updated_by TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, key)
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def get_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")   # 并发读写不互锁（AI 高频写入场景）
    conn.execute("PRAGMA busy_timeout = 15000") # 锁等待 15s 而不是立刻报 database is locked
    return conn


def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    # 增量迁移：用例/Bug 可关联接口；接口可声明独立域名（空=继承环境 base_url）
    # 2026-10-22：用例补第二个锚点（doc_id）、覆盖维度（dims）、批次（batch）
    for table, column, ddl in (
        ("cases", "interface_id", "INTEGER REFERENCES interfaces(id)"),
        ("cases", "doc_id", "INTEGER REFERENCES docs(id)"),
        ("cases", "dims", "TEXT NOT NULL DEFAULT ''"),
        ("cases", "batch", "TEXT NOT NULL DEFAULT ''"),
        ("cases", "steps_json", "TEXT NOT NULL DEFAULT ''"),
        # AI 持续生成：老用例这些字段留空，不影响已有 API 和执行流程。
        ("cases", "target_id", "INTEGER REFERENCES test_targets(id)"),
        ("cases", "generation_batch_id", "INTEGER REFERENCES generation_batches(id)"),
        ("cases", "generation_strategy", "TEXT NOT NULL DEFAULT ''"),
        ("cases", "intent_fingerprint", "TEXT NOT NULL DEFAULT ''"),
        ("cases", "novelty", "TEXT NOT NULL DEFAULT ''"),
        ("executions", "step_results", "TEXT NOT NULL DEFAULT ''"),
        ("executions", "intent_fingerprint", "TEXT NOT NULL DEFAULT ''"),
        ("bugs", "interface_id", "INTEGER REFERENCES interfaces(id)"),
        ("interfaces", "host", "TEXT NOT NULL DEFAULT ''"),
        # P1：执行结果可以归到某一轮 run（历史数据留空，不影响旧视图）
        ("executions", "run_id", "INTEGER REFERENCES runs(id)"),
        # runs.project_id：建表语句里一直有，但老库（P1 之前）没有这条迁移，
        # 一旦被漏掉，下面的 idx_run_proj_status 建索引就会 "no such column" 直接崩。
        # 历史数据无法知道归属，按 1 号项目兜底（单项目部署的实际情形）。
        ("runs", "project_id", "INTEGER NOT NULL DEFAULT 1"),
        # 执行观测：认领者身份、心跳、取消原因（老库增量补列）
        ("runs", "runner_id", "TEXT NOT NULL DEFAULT ''"),
        ("runs", "last_heartbeat_at", "TEXT NOT NULL DEFAULT ''"),
        ("runs", "cancel_note", "TEXT NOT NULL DEFAULT ''"),
        # 轮次性质（回归 / 自检 / 诊断）：老库一律按 regression，回填脚本再细分
        ("runs", "kind", "TEXT NOT NULL DEFAULT 'regression'"),
        # Bug 提交前自检字段 + 驳回分类（2026-10-26 评审修复）：
        # 线上 57 投 55 驳，没有结构化信息就说不清"为什么驳"，也没法统计哪类误报最多。
        ("bugs", "repro_rate", "TEXT NOT NULL DEFAULT ''"),
        ("bugs", "impact", "TEXT NOT NULL DEFAULT ''"),
        ("bugs", "reject_category", "TEXT NOT NULL DEFAULT ''"),
    ):
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    # 按"项目 + 锚点"取数的索引（接口上千条后仍能秒回）
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_itf_proj_module ON interfaces(project_id, module);
        CREATE INDEX IF NOT EXISTS idx_itf_proj_path   ON interfaces(project_id, path);
        CREATE INDEX IF NOT EXISTS idx_case_proj_itf   ON cases(project_id, interface_id);
        CREATE INDEX IF NOT EXISTS idx_case_proj_module ON cases(project_id, module);
        CREATE INDEX IF NOT EXISTS idx_case_target      ON cases(target_id);
        CREATE INDEX IF NOT EXISTS idx_case_gen_batch   ON cases(generation_batch_id);
        CREATE INDEX IF NOT EXISTS idx_target_next      ON test_targets(project_id, status, strategy, priority);
        CREATE INDEX IF NOT EXISTS idx_target_parent    ON test_targets(parent_target_id);
        CREATE INDEX IF NOT EXISTS idx_target_fingerprint ON test_targets(project_id, fingerprint);
        CREATE INDEX IF NOT EXISTS idx_gen_batch_proj   ON generation_batches(project_id, status);
        CREATE INDEX IF NOT EXISTS idx_ci_itf          ON case_interfaces(interface_id);
        CREATE INDEX IF NOT EXISTS idx_pkt_linked      ON packets(linked_type, linked_id);
        CREATE INDEX IF NOT EXISTS idx_pkt_proj        ON packets(project_id);
        CREATE INDEX IF NOT EXISTS idx_run_proj_status ON runs(project_id, status);
        CREATE INDEX IF NOT EXISTS idx_exec_run        ON executions(run_id);
        CREATE INDEX IF NOT EXISTS idx_exec_case_intent ON executions(case_id, intent_fingerprint, id);
    """)
    # 用例免审：老库里 cases.status / review_comment 已无意义，直接删列
    case_cols = [r[1] for r in conn.execute("PRAGMA table_info(cases)")]
    for col in ("status", "review_comment"):
        if col in case_cols:
            conn.execute(f"ALTER TABLE cases DROP COLUMN {col}")
    # 文档/接口免审（2026-10-22）：两条审核流实测零驳回零意见，status 轴一并删掉。
    # 接口的质量信号改用 verify_status（verified / unverified / changed）+ evidence。
    for table in ("docs", "interfaces"):
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        for col in ("status", "review_comment"):
            if col in cols:
                conn.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
    # Bug 不再追踪"开发修没修"（2026-10-22）：开发只在我们自己的在线表格跟进，
    # 平台只做分诊。status 轴实测空转——fixed 从未使用、closed 的 5 条全是 rejected、
    # 剥掉 status 条件后默认视图与审核队列的条数一条不变。
    # 删列，换成一个事实字段 reported_at（已抄进表格的时间），空表示还没上报。
    bug_cols = [r[1] for r in conn.execute("PRAGMA table_info(bugs)")]
    if "status" in bug_cols:
        conn.execute("ALTER TABLE bugs DROP COLUMN status")
    if "reported_at" not in bug_cols:
        conn.execute("ALTER TABLE bugs ADD COLUMN reported_at TEXT NOT NULL DEFAULT ''")
    # 一条用例可覆盖多个接口：把主锚点回填进关联表
    conn.execute(
        "INSERT OR IGNORE INTO case_interfaces (case_id, interface_id) "
        "SELECT id, interface_id FROM cases WHERE interface_id IS NOT NULL")
    # 模块词表：用接口的 module 作为唯一来源（用例的 module 由接口派生），先做一次回填
    conn.execute(
        "INSERT OR IGNORE INTO modules (project_id, name, sort) "
        "SELECT project_id, module, 100 FROM interfaces WHERE module <> '' "
        "GROUP BY project_id, module")
    conn.execute(
        "INSERT OR IGNORE INTO modules (project_id, name, sort) "
        "SELECT project_id, module, 200 FROM cases WHERE module <> '' "
        "GROUP BY project_id, module")
    conn.commit()
    conn.close()


def log_audit(actor, action, target="", detail=""):
    """写操作日志。

    注意：这里自己开一条连接（不复用调用方的），所以**必须在业务事务 commit 之后**调用。
    调用方若还握着未提交的写事务，两条连接会抢写锁并直接抛 database is locked——
    busy_timeout 对同进程内的写-写冲突不生效。
    """
    conn = get_db()
    conn.execute(
        "INSERT INTO audit (actor, action, target, detail, created_at) VALUES (?,?,?,?,?)",
        (actor, action, target, detail, now()),
    )
    conn.commit()
    conn.close()
