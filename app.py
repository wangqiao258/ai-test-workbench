"""AI 协同测试工作台 - 本地版（入口 + 网页端）

网页端：账号密码 session 登录；API 端拆在 `api/` 包里，用 X-API-Token 鉴权。
AI 写入的文档/接口/用例免审；只有 Bug 进待审核（误报成本高，且驳回会改变下游可见性）。

模块分工：
    core/validation.py   文档类型、接口路径/域名、覆盖维度的校验规则（无 IO）
    core/steps.py        结构化步骤的校验、渲染与分步结果推导（无 IO）
    core/anchors.py      用例锚点、接口关联表、标题查重
    core/openapi_doc.py  由 interfaces 表装配 OpenAPI
    api/                 /api/* 全部端点（蓝图）
"""
import functools
import json
import os
import re
import secrets
import threading
import time
from urllib.parse import parse_qsl, urlsplit

import markdown as md_lib
import nh3
from flask import (Flask, Response, abort, flash, g, jsonify, redirect, render_template,
                   request, send_from_directory, session, url_for)
from markupsafe import Markup
from werkzeug.security import check_password_hash, generate_password_hash

from api import api_bp
from api.packets import packet_bodies, packets_for_view
from api.common import clear_table_cols_cache, json_dumps, rows_to_list
from core import lists, passwords
from core.notify import build_payload, post_webhook, validate_notify
from core.packets import raw_name, raw_text
from core.filters import clean_qs, qs_with
from core.openapi_doc import project_openapi
from core.runs import can_transition, cancelled_summary
from core.steps import parse_step_list, parse_steps, render_ui_text
from core.validation import BUG_REJECT_CATS, BUG_REPRO_LABELS, DIM_VOCAB, DOC_TYPES, parse_dims
from db import DATA_DIR, UPLOAD_DIR, get_db, init_db, log_audit, now

app = Flask(__name__)


def _load_or_create_secret_key():
    """session 密钥落盘到 data/secret_key。

    每次进程重启都随机的话，一重启全员掉登录态（2026-10-23 实测过的老问题），
    而且将来上多 worker/多进程会互相踢会话。密钥与库同卷同密级：
    库在谁手里，谁本来就能重签 session，不引入新的泄露面。
    写不进去（只读挂载等）时退回进程级随机，功能不让路。
    """
    path = os.path.join(DATA_DIR, "secret_key")
    try:
        with open(path, encoding="utf-8") as f:
            key = f.read().strip()
        if len(key) >= 32:
            return key
    except OSError:
        pass
    key = secrets.token_hex(32)
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(key)
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


app.secret_key = _load_or_create_secret_key()
# 上传大小上限（默认 50MB，env APP_MAX_UPLOAD_MB 可配）；超限由下面的 413 处理返回 JSON
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("APP_MAX_UPLOAD_MB", "50")) * 1024 * 1024

@app.errorhandler(413)
def payload_too_large(_):
    limit_mb = app.config["MAX_CONTENT_LENGTH"] // 1024 // 1024
    return jsonify({"error": f"文件超过大小上限（{limit_mb}MB）"}), 413
app.register_blueprint(api_bp)

# Markdown 净化白名单（2026-10-26）：python-markdown 默认原样透传原始 HTML，
# 探针复现过 <script>/<img onerror>/javascript: 链接随文档直出（存储型 XSS）。
# 文档内容是 AI 写的，等于把浏览器交给最不可控的那一环——输出前过 nh3 剥一遍。
MD_TAGS = {"a", "b", "i", "em", "strong", "del", "s", "p", "br", "hr", "span", "div",
           "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "blockquote", "pre",
           "code", "table", "thead", "tbody", "tr", "td", "th", "img"}
MD_ATTRS = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title"},
    "code": {"class"}, "pre": {"class"}, "span": {"class"}, "div": {"class"},
    "th": {"colspan", "rowspan"}, "td": {"colspan", "rowspan"},
}

@app.template_filter("md")
def render_markdown(text):
    """把 Markdown 渲染为 HTML（表格/代码块/标题等），并净化原始 HTML。"""
    html = md_lib.markdown(text or "", extensions=["tables", "fenced_code", "nl2br"])
    return Markup(nh3.clean(html, tags=MD_TAGS, attributes=MD_ATTRS,
                            url_schemes={"http", "https", "mailto"}))


@app.context_processor
def inject_review_count():
    """导航栏的待办数 = 待审核 + 待上报，这是"还有多少条等我动手"的唯一全局提示。

    口径由 lists.bug_todo_breakdown 统一给出，与 /review 收件箱的列表同源——
    两边各写一套 SQL 时出过"角标 1、点进去空的"（待上报不进收件箱）。
    未登录不查库（登录页不渲染导航）。
    """
    if not session.get("user"):
        return {"review_count": 0, "review_pending": 0, "review_toreport": 0}
    conn = get_db()
    n = lists.bug_todo_breakdown(conn)
    conn.close()
    return {"review_count": n["pending"] + n["toreport"],
            "review_pending": n["pending"], "review_toreport": n["toreport"]}

IMG_URL_RE = re.compile(r"/files/(\S+?\.(?:png|jpg|jpeg|gif|webp))", re.I)

def evidence_images(*texts):
    """从证据文本中提取 /files/ 下的图片链接，用于内嵌显示。"""
    found = []
    for t in texts:
        if t:
            found.extend(IMG_URL_RE.findall(t))
    return sorted(set(found))

app.jinja_env.globals["evidence_images"] = evidence_images
# 模板里要拼"保留当前筛选、只改一个参数"的链接（如点模块名只看该模块）
app.jinja_env.globals["qs_with"] = qs_with
# UI 步骤渲染成一句人话（"点击 [按文本]登 录"），别在页面上直接甩 dict repr
app.jinja_env.globals["ui_text"] = render_ui_text


@app.context_processor
def inject_css_version():
    """给 style.css 带上文件 mtime 当版本号。

    不加的话改完样式，浏览器还拿着上一次的缓存文件，看到的是没样式的
    多选面板（<details> 的默认外观），而且刷新也未必能恢复。
    """
    try:
        v = int(os.path.getmtime(os.path.join(app.static_folder, "style.css")))
    except OSError:
        v = 0
    return {"css_v": v}

@app.template_filter("dim_list")
def dim_list(raw):
    """把 cases.dims 的 JSON 字符串渲染成标签列表（模板用）。"""
    return parse_dims(raw)

@app.template_filter("json_list")
def json_list(raw):
    """把 executions.step_results 的 JSON 字符串渲染成列表（模板用）。"""
    return parse_step_list(raw)

SEVERITY_LABELS = {"critical": "严重", "major": "较重", "normal": "一般", "minor": "轻微"}
app.jinja_env.globals["sev_label"] = lambda s: SEVERITY_LABELS.get(s, s)
# Bug 自检字段与驳回分类的词表（2026-10-26 加，与 core/validation 同源）
app.jinja_env.globals["repro_label"] = lambda k: BUG_REPRO_LABELS.get(k, k or "")
app.jinja_env.globals["reject_cat_label"] = lambda k: BUG_REJECT_CATS.get(k, k or "")
# 驳回分类的下拉选项（与词表同源，别在模板里手抄一份）
app.jinja_env.globals["reject_cat_options"] = BUG_REJECT_CATS
app.jinja_env.globals["doc_type_label"] = lambda t: DOC_TYPES.get(t, t)
# 模板改动免重启。光设 TEMPLATES_AUTO_RELOAD 不够（实测 include 的 partial 仍读缓存），
# 要把 Jinja 环境的 auto_reload 显式打开——它必须在 jinja_env 首次创建之后设才留得住。
app.jinja_env.auto_reload = True
app.config["TEMPLATES_AUTO_RELOAD"] = True
# 设计原则：域名是接口的"属性"，不是目录树的固定层级。
# 单域名项目里域名就等于环境 base_url，不重复进树；真出现第二个域名时树才长出一层。

# 状态显示层：数据库/API 恒用英文代码，网页显示中文标签（参照禅道/Jira 做法）
STATUS_LABELS = {
    # 审核状态（文档/用例/接口的 status，Bug 的 review_status）
    "pending": "待审核", "approved": "已通过", "rejected": "已驳回",
    # Bug 生命周期状态
    "open": "待处理", "fixed": "已修复", "verified": "已验证", "closed": "已关闭",
    # 用例执行结果
    "pass": "通过", "fail": "未通过", "blocked": "阻塞",
    # 执行批次（run）状态；stalled 是派生的"卡住"（心跳超时），不进库
    "queued": "排队", "running": "运行中", "done": "完成", "failed": "失败",
    "stalled": "卡住",
}
app.jinja_env.globals["status_label"] = lambda s: STATUS_LABELS.get(s, s)
# 轮次类型（与状态正交）：回归 / 自检 / 诊断。列表里先看类型，再看跑没跑完
KIND_LABELS = {"regression": "回归", "selfcheck": "自检", "diagnostic": "诊断"}
app.jinja_env.globals["kind_label"] = lambda k: KIND_LABELS.get(k, k or "")

# ---------- 初始化 ----------

def bootstrap():
    init_db()
    clear_table_cols_cache()    # 迁移后列可能变化，清掉列名缓存
    conn = get_db()
    row = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()
    if not row:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?,?)",
            ("admin", generate_password_hash("admin123")),
        )
        conn.commit()
    conn.close()

bootstrap()

# ---------- 鉴权 ----------

def login_required(view):
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapper

# ==================== 网页端 ====================

# tab 白名单：tab 参与模板 include，不能让 URL 决定加载哪个文件
# 2026-10-27：原「接口文档」tab（apidoc）已合并进「接口」的视图切换（?view=），
# 理由：两者是同一张 interfaces 表的只读视图，搜索/契约展示/验证状态全部重叠。
TABS = ("docs", "interfaces", "cases", "bugs", "runs", "settings")

# 接口 tab 的两个视图：列表（检索）/ 目录树（浏览）。
# 白名单外的 view 一律回列表，手改 URL 不会得到空白页。
# 2026-10-27：Swagger 视图已删除——AI 不渲染页面（走 /api/interfaces 切片），
# 平台内也没有"只想读文档"的读者；要标准文档就下载 openapi.json 导入 Apifox/Postman。
IFACE_VIEWS = ("list", "tree")


def project_back(pid, raw, default_tab="docs"):
    """详情页的返回地址。back 参数只接受白名单键，防止被当成任意跳转。"""
    qs = clean_qs(raw) or f"tab={default_tab}"
    return url_for("project_detail", pid=pid) + "?" + qs


def action_back(pid, raw):
    """审核 / 改状态之后的回跳。

    带 tab 的是从项目页发起的，回原筛选；没有 tab 的是从审核队列发起的，
    回 /review 并保留队列自己的筛选（fp/fe/fv/fq）。完全没带 back 的保持旧行为，
    回项目页的 Bug tab——避免老调用点行为漂移。
    """
    qs = clean_qs(raw)
    if not qs or dict(parse_qsl(qs)).get("tab"):
        return redirect(url_for("project_detail", pid=pid) + "?" + (qs or "tab=bugs"))
    return redirect(url_for("review") + "?" + qs)


def _safe_next(target):
    """登录后只允许跳站内相对路径。

    /login?next=https://evil.com 曾能让"登录成功"直接把用户送到钓鱼页
    （2026-10-26 探针复现 302）。协议相对地址 //host 同样算外站，一并拒。
    """
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return None


# ---------- 基础 Web 安全（2026-10-26 评审修复） ----------
# 1)  SameSite=Lax：跨站发起的 POST 不再自动带上 session cookie。
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True

# 2)  同源校验：网页端所有 POST 必须来自同源（Origin 缺失时退看 Referer）。
#     /api/* 用 X-API-Token 鉴权、根本不发 cookie，CSRF 不适用，整条豁免。
@app.before_request
def _enforce_same_origin():
    if request.method != "POST" or request.path.startswith("/api/"):
        return None
    origin = request.headers.get("Origin") or request.headers.get("Referer") or ""
    if not origin:
        return None          # 两个头都没有的基本是非浏览器客户端，放行
    host = (urlsplit(origin).netloc or "").lower()
    if host and host != (request.host or "").lower():
        return jsonify({"error": "跨站请求已被拒绝（Origin 与站点不一致）"}), 403
    return None

# 3)  安全响应头：防嗅探 / 防iframe劫持 / 收敛 Referer。
@app.after_request
def _security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    return resp

# 4)  登录限速：同一 (用户名, IP) 10 分钟内失败 5 次，锁定 60 秒。
#     内网单用户工具不做字典防护，这条拦的是"脚本暴力试口令"。
_LOGIN_FAILS = {}          # key -> (失败次数, 最后一次失败时间, 锁定截止时间)
_LOGIN_LOCK = threading.Lock()
LOGIN_WINDOW, LOGIN_MAX_TRIES, LOGIN_LOCKOUT = 600, 5, 60


def _login_key(username):
    return f"{username}|{request.remote_addr or '?'}"


def _login_blocked(key):
    """锁定期内返回 True；窗口外陈旧的记录顺手清掉。"""
    with _LOGIN_LOCK:
        count, last, until = _LOGIN_FAILS.get(key, (0, 0.0, 0.0))
        now_ts = time.time()
        if until > now_ts:
            return True
        if now_ts - last > LOGIN_WINDOW:
            _LOGIN_FAILS.pop(key, None)
        return False


def _record_login_fail(key):
    with _LOGIN_LOCK:
        count, last, until = _LOGIN_FAILS.get(key, (0, 0.0, 0.0))
        now_ts = time.time()
        if now_ts - last > LOGIN_WINDOW:
            count = 0                      # 超出窗口从头计
        count += 1
        until = now_ts + LOGIN_LOCKOUT if count >= LOGIN_MAX_TRIES else 0.0
        _LOGIN_FAILS[key] = (count, now_ts, until)


def _clear_login_fails(key):
    with _LOGIN_LOCK:
        _LOGIN_FAILS.pop(key, None)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        key = _login_key(username)
        if _login_blocked(key):
            flash("失败次数过多，请 1 分钟后再试")
            return render_template("login.html")
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password_hash"], password):
            session["user"] = username
            _clear_login_fails(key)
            log_audit(f"user:{username}", "login")
            return redirect(_safe_next(request.args.get("next")) or url_for("dashboard"))
        _record_login_fail(key)
        flash("用户名或密码错误")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def dashboard():
    conn = get_db()
    projects = rows_to_list(conn.execute("SELECT * FROM projects ORDER BY id DESC"))
    stats = {}
    for p in projects:
        pid = p["id"]
        stats[pid] = {
            "docs": conn.execute("SELECT COUNT(*) c FROM docs WHERE project_id=?", (pid,)).fetchone()["c"],
            "cases": conn.execute("SELECT COUNT(*) c FROM cases WHERE project_id=?", (pid,)).fetchone()["c"],
            # 未结案 = 待审核 + 待上报（status 轴已废弃，见 db.py 迁移注释）
            "bugs": lists.bug_todo_count(conn, pid),
            # 数据质量（修复项 13）：总量飘绿掩盖不了"发动机空"，四个比率单独看
            "quality": lists.quality_stats(conn, pid),
        }
    # 只剩 Bug 进审核队列：文档/接口已于 2026-10-22 免审
    pending = conn.execute(
        "SELECT COUNT(*) c FROM bugs WHERE review_status='pending'"
    ).fetchone()["c"]
    conn.close()
    return render_template("dashboard.html", projects=projects, stats=stats, pending=pending)

@app.route("/projects/new", methods=["POST"])
@login_required
def project_new():
    name = request.form.get("name", "").strip()
    desc = request.form.get("description", "").strip()
    if name:
        conn = get_db()
        cur = conn.execute(
            "INSERT INTO projects (name, description, created_at) VALUES (?,?,?)",
            (name, desc, now()),
        )
        conn.commit()
        conn.close()
        log_audit(f"user:{session['user']}", "create_project", f"project:{cur.lastrowid}", name)
    return redirect(url_for("dashboard"))

@app.route("/projects/<int:pid>")
@login_required
def project_detail(pid):
    """项目页：每个 tab 只查自己要用的数据，并各自带筛选与分页。

    改造前这里不分 tab 全查（161 接口 + 61 用例 + 39 Bug + 61 次执行记录查询），
    打开"项目文档"也要跑 70 次 SQL。现在按 tab 分流，列表页只取索引列。
    """
    tab = request.args.get("tab", "docs")
    if tab == "apidoc":
        # 旧链接兼容（书签 / README 旧表格 / 详情页的 back 参数）：一律 302 到目录树。
        # 原 view=swagger 的那个页面已删除，旧参数会被白名单过滤成列表，这里统一收口到 tree。
        qs = qs_with(request.args, tab="interfaces", view="tree")
        return redirect(url_for("project_detail", pid=pid) + "?" + qs)
    if tab not in TABS:
        tab = "docs"
    conn = get_db()
    project = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    if not project:
        conn.close()
        abort(404)

    args = request.args
    envs = rows_to_list(conn.execute(
        "SELECT * FROM environments WHERE project_id=? ORDER BY id", (pid,)))
    # 服务地址：默认取第一个环境，?env=<id> 只切换展示用的 base_url，不改数据
    env_id = args.get("env", type=int)
    active_env = next((e for e in envs if e["id"] == env_id), None)
    if active_env is None and envs:
        active_env = envs[0]
    default_base = (active_env["base_url"] or "").rstrip("/") if active_env else ""

    ctx = dict(project=dict(project), tab=tab, envs=envs,
               active_env=active_env, default_base=default_base,
               qs=request.query_string.decode(),
               base_qs=qs_with(args, page="", apage="", sel=""),
               counts=lists.tab_counts(conn, pid))

    if tab == "docs":
        rows, total, f, all_total = lists.docs_list(conn, pid, args)
        ctx.update(docs=rows, doc_total=total, doc_all_total=all_total,
                   doc_f=f, doc_types=DOC_TYPES)

    elif tab == "interfaces":
        # 两个视图共用一个入口，各自只查自己需要的列：
        # 列表分页取索引列，目录树取全量节点（不含 evidence）。
        view = args.get("view", "list")
        if view not in IFACE_VIEWS:
            view = "list"
        ctx.update(itf_view=view, itf_stats=lists.interface_stats(conn, pid))

        if view == "list":
            rows, pg, f = lists.interfaces_page(conn, pid, args)
            items = lists.module_counts(conn, "interfaces", pid)
            ctx.update(itf_rows=rows, itf_pg=pg, itf_f=f,
                       itf_group_opts=lists.group_options(items),
                       # 选了分组就把面板收窄到该组；已选模块跨组时自动退回全量
                       itf_module_opts=lists.module_options(
                           items, f["state"].get("group"), f["state"].get("module", ())))
        elif view == "tree":
            tree = lists.interfaces_tree(conn, pid)
            hosts_seen = []
            for i in tree:
                base = (i.get("host") or default_base).rstrip("/")
                i["host_used"] = base
                if base and base not in hosts_seen:
                    hosts_seen.append(base)
            ctx.update(itf_tree=tree, hosts_seen=hosts_seen,
                       multi_host=len(hosts_seen) >= 2)

    elif tab == "cases":
        rows, pg, f = lists.cases_page(conn, pid, args)
        items = lists.module_counts(conn, "cases", pid)
        ctx.update(case_rows=rows, case_pg=pg, case_f=f,
                   case_group_opts=lists.group_options(items),
                   case_module_opts=lists.module_options(
                       items, f["state"].get("group"), f["state"].get("module", ())),
                   dim_vocab=DIM_VOCAB)

    elif tab == "bugs":
        rows, pg, f = lists.bugs_page(conn, pid, args)
        # 分栏右栏：?sel=<id> 指定看哪条；缺省选当前页第一条，打开 tab 就有内容，
        # 不必再点一次。sel 指向别的项目时当作没选，不能让 URL 越权读别的项目。
        sel_bug, sel_atts = None, []
        sel_id = args.get("sel", type=int)
        if sel_id:
            sel_bug, sel_atts = lists.bug_detail(conn, sel_id)
            if sel_bug and sel_bug["pid"] != pid:
                sel_bug, sel_atts = None, []
        if sel_bug is None and rows:
            sel_bug, sel_atts = lists.bug_detail(conn, rows[0]["id"])
        sel_packets = packets_for_view(conn, "bug", sel_bug["id"]) if sel_bug else []
        ctx.update(bug_rows=rows, bug_pg=pg, bug_f=f,
                   bug_modules=[(m, m) for m in lists.modules(conn, "bugs", pid)],
                   sel_bug=sel_bug, sel_atts=sel_atts, sel_packets=sel_packets,
                   # 卡片链接在服务端拼好：模板里手拼 query 容易漏掉筛选条件
                   sel_qs={b["id"]: qs_with(args, sel=b["id"]) for b in rows})

    elif tab == "runs":
        rows, pg, f = lists.runs_page(conn, pid, args, now())
        ctx.update(run_rows=rows, run_pg=pg, run_f=f)

    elif tab == "settings":
        accounts = rows_to_list(conn.execute(
            "SELECT a.*, e.name env_name FROM accounts a "
            "LEFT JOIN environments e ON a.env_id=e.id WHERE a.project_id=? "
            "ORDER BY a.id", (pid,)))
        # 就地编辑由 URL 决定哪一行（?edit=<id>），与列表筛选同一套"状态唯一来源是 URL"的规矩：
        # 刷新/回退都能回到同一状态，不需要前端记住谁在编辑。
        edit_id = args.get("edit", type=int)
        srow = conn.execute(
            "SELECT value FROM project_settings WHERE project_id=? AND key='notify'",
            (pid,)).fetchone()
        notify_cfg = None
        if srow:
            try:
                val = json.loads(srow["value"])
                if isinstance(val, dict):
                    notify_cfg = val
            except (ValueError, TypeError):
                notify_cfg = None
        ctx.update(accounts=accounts,
                   edit_acc=next((a for a in accounts if a["id"] == edit_id), None),
                   notify_cfg=notify_cfg)

    conn.close()
    return render_template("project.html", **ctx)

# ---------- 列表 → 详情（列表页只留索引，全文在这里看） ----------

@app.route("/cases/<int:cid>")
@login_required
def case_detail(cid):
    conn = get_db()
    case, runs, linked = lists.case_detail(conn, cid)
    if not case:
        conn.close()
        abort(404)
    case["steps_doc"] = parse_steps(case.get("steps_json"))
    case["dims"] = parse_dims(case.get("dims"))
    for r in runs:
        r["step_results_list"] = parse_step_list(r.get("step_results"))
        # 数据包挂在"某次执行"上，而不是用例上——同一用例跑多次要能区分
        r["packets"] = packets_for_view(conn, "execution", r["id"])
    conn.close()
    return render_template("case_detail.html", case=case, runs=runs, linked=linked,
                           back=project_back(case["pid"], request.args.get("back"),
                                             "cases"))

@app.route("/runs/<int:rid>")
@login_required
def run_detail(rid):
    """一轮 run 的全貌：进度、执行明细、还没跑到的用例、跑不了的用例（带原因）。

    只读 + 一个"收尾"动作（把卡住的 running 标成 failed）。不提供调度/重跑按钮：
    跑什么、要不要重跑是 AI 的判断，平台只负责把状态改回真实。
    """
    conn = get_db()
    run, execs, extra = lists.run_detail(conn, rid, now())
    conn.close()
    if not run:
        abort(404)
    for e in execs:
        e["step_results"] = parse_step_list(e.get("step_results"))
    return render_template("run_detail.html", run=run, execs=execs,
                           pending=extra["pending"], unrunnable=extra["unrunnable"],
                           back=project_back(run["pid"], request.args.get("back"), "runs"))


@app.route("/runs/<int:rid>/cancel", methods=["POST"])
@login_required
def run_cancel(rid):
    """把卡住的一轮收尾。网页端唯一的手动动作，不是调度入口。"""
    note = (request.form.get("note") or "").strip() or "网页人工取消"
    conn = get_db()
    row = conn.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
    if not row:
        conn.close()
        abort(404)
    if not can_transition(row["status"], "failed"):
        conn.close()
        flash(f"run {rid} 当前是 {row['status']}，不需要收尾", "error")
        return redirect(url_for("run_detail", rid=rid))
    total = json.loads(row["summary"] or "{}").get("total") or 0
    results = [r["result"] for r in conn.execute(
        "SELECT result FROM executions WHERE run_id=?", (rid,))]
    summary = cancelled_summary(total, results, note)
    conn.execute(
        "UPDATE runs SET status='failed', summary=?, cancel_note=?, finished_at=? "
        "WHERE id=?", (json.dumps(summary, ensure_ascii=False), note[:500], now(), rid))
    conn.commit()
    conn.close()
    # log_audit 自开连接，必须等业务事务 commit + close 之后调，否则 database is locked
    log_audit(f"user:{session['user']}", "run_cancel", f"run:{rid}",
              f"{row['status']} → failed / {note[:80]}")
    flash(f"run {rid} 已收尾为 failed", "ok")
    return redirect(url_for("run_detail", rid=rid))


@app.route("/bugs/<int:bid>")
@login_required
def bug_detail(bid):
    conn = get_db()
    bug, atts = lists.bug_detail(conn, bid)
    if not bug:
        conn.close()
        abort(404)
    packets = packets_for_view(conn, "bug", bid)
    conn.close()
    return render_template("bug_detail.html", bug=bug, atts=atts, packets=packets,
                           back=project_back(bug["pid"], request.args.get("back"),
                                             "bugs"),
                           back_qs=clean_qs(request.args.get("back")) or "tab=bugs")

# ---------- 接口契约：详情页与目录树右栏共用一份取数与渲染 ----------

def _contract_lists(row):
    """req_headers / req_params / error_codes 存的是 JSON 字符串，列表化后给模板用。

    详情页和右栏面板曾各写一遍这段解析，字段一改就得改两处。
    """
    for f in ("req_headers", "req_params", "error_codes"):
        try:
            row[f + "_list"] = json.loads(row[f]) if row[f] else []
        except (TypeError, ValueError):
            row[f + "_list"] = []
    return row


def _with_full_url(conn, itf, env_id):
    """补上 host_used / full_url：接口独立域名（host）优先，其次环境 base_url。"""
    envs = rows_to_list(conn.execute(
        "SELECT * FROM environments WHERE project_id=?", (itf["project_id"],)))
    active_env = next((e for e in envs if e["id"] == env_id), None)
    if active_env is None and envs:
        active_env = envs[0]
    default_base = (active_env["base_url"] or "").rstrip("/") if active_env else ""
    base = (itf.get("host") or default_base).rstrip("/")
    itf["host_used"] = base
    itf["full_url"] = (base + itf["path"]) if base else itf["path"]
    return itf, active_env, default_base


@app.route("/projects/<int:pid>/interfaces/<int:iid>/panel.html")
@login_required
def interface_panel_html(pid, iid):
    """目录树右栏：服务端渲染的契约片段。

    原来这里是 panel.json + 前端 detailHtml/paramRows 手拼 HTML，和 interface.html
    形成了两套契约渲染（notes 一边 Markdown 一边转义、表头一边「字段」一边「名称」）。
    现在只有 _detail_interface.html 一份，加字段不用改 JS。
    """
    env_id = request.args.get("env", type=int)
    conn = get_db()
    row = lists.interface_panel(conn, iid)
    if not row or row.get("project_id") != pid:
        conn.close()
        abort(404)
    itf, active_env, _ = _with_full_url(conn, _contract_lists(row), env_id)
    conn.close()
    back = "tab=interfaces&view=tree" + (f"&env={active_env['id']}" if active_env else "")
    return render_template("_panel_itf_contract.html", itf=itf, back_qs=back,
                           active_env=active_env)


@app.route("/interfaces/<int:iid>")
@login_required
def interface_detail(iid):
    conn = get_db()
    itf = conn.execute(
        "SELECT i.*, p.name project_name, p.id pid FROM interfaces i "
        "JOIN projects p ON i.project_id=p.id WHERE i.id=?", (iid,)).fetchone()
    if not itf:
        conn.close()
        abort(404)
    itf = _contract_lists(dict(itf))
    cases = rows_to_list(conn.execute(
        "SELECT c.id, c.title, c.dims FROM cases c WHERE c.interface_id=? "
        "OR c.id IN (SELECT case_id FROM case_interfaces WHERE interface_id=?) "
        "ORDER BY c.id", (iid, iid)))
    for c in cases:
        c["dims"] = parse_dims(c.get("dims"))
    covered = [d for d in DIM_VOCAB if any(d in c["dims"] for c in cases)]
    dims_covered, dims_missing = covered, [d for d in DIM_VOCAB if d not in covered]
    # 「正常」是基线不是风险维度：混在一起时，一条正常流用例会让接口看起来"有覆盖"。
    # 拆开后，只测了正常流的接口会明确显示"风险维度 0/9"。
    base_dim = "正常"
    baseline_done = base_dim in covered
    risk_total = len([d for d in DIM_VOCAB if d != base_dim])
    risk_covered = [d for d in covered if d != base_dim]
    risk_missing = [d for d in DIM_VOCAB if d != base_dim and d not in covered]
    bugs = rows_to_list(conn.execute(
        "SELECT id, title, severity, review_status, reported_at FROM bugs "
        "WHERE interface_id=?", (iid,)))
    packets = packets_for_view(conn, "interface", iid)
    itf, active_env, default_base = _with_full_url(
        conn, itf, request.args.get("env", type=int))
    conn.close()
    return render_template("interface.html", itf=itf, cases=cases, bugs=bugs,
                           active_env=active_env, default_base=default_base,
                           packets=packets,
                           dims_covered=dims_covered, dims_missing=dims_missing,
                           baseline_done=baseline_done, risk_covered=risk_covered,
                           risk_missing=risk_missing, risk_total=risk_total,
                           back=project_back(itf["project_id"],
                                             request.args.get("back"), "interfaces"))

# ---------- 活的 OpenAPI 文档（由 interfaces 表自动生成） ----------

@app.route("/projects/<int:pid>/openapi.json")
@login_required
def project_openapi_json(pid):
    """OpenAPI 活文档（接口免审，全量）：网页「导出 openapi.json」与外部工具共用这一份。"""
    doc = project_openapi(pid)
    if doc is None:
        abort(404)
    return jsonify(doc)

@app.route("/docs/<int:did>")
@login_required
def doc_detail(did):
    conn = get_db()
    doc = conn.execute(
        "SELECT d.*, p.name project_name, p.id pid FROM docs d "
        "JOIN projects p ON d.project_id=p.id WHERE d.id=?", (did,)).fetchone()
    if not doc:
        conn.close()
        abort(404)
    atts = rows_to_list(conn.execute(
        "SELECT * FROM attachments WHERE linked_type='doc' AND linked_id=?", (did,)))
    conn.close()
    return render_template("doc.html", doc=dict(doc), atts=atts,
                           back=project_back(doc["pid"], request.args.get("back"),
                                             "docs"))

@app.route("/projects/<int:pid>/env", methods=["POST"])
@login_required
def env_add(pid):
    conn = get_db()
    conn.execute(
        "INSERT INTO environments (project_id, name, base_url, notes) VALUES (?,?,?,?)",
        (pid, request.form.get("name", ""), request.form.get("base_url", ""),
         request.form.get("notes", "")),
    )
    conn.commit()
    conn.close()
    log_audit(f"user:{session['user']}", "add_env", f"project:{pid}", request.form.get("name", ""))
    return redirect(url_for("project_detail", pid=pid, tab="settings"))

def _account_env_id(conn, pid, raw):
    """把表单里的 env_id 归一成 int 或 None，顺带守住两条：

    - 空 -> None（不指定环境）；
    - 非数字、或指向别的项目的环境 -> 抛 ValueError。
      不校验的话，伪造的 env_id 会撞外键（IntegrityError -> 500），
      也可能把账号挂到别的项目的环境上。
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    if not raw.isdigit():
        raise ValueError("环境参数非法")
    env_id = int(raw)
    if not conn.execute("SELECT 1 FROM environments WHERE id=? AND project_id=?",
                        (env_id, pid)).fetchone():
        raise ValueError("环境不存在或不属于该项目")
    return env_id


@app.route("/projects/<int:pid>/account", methods=["POST"])
@login_required
def account_add(pid):
    username = (request.form.get("username") or "").strip()
    if not username:
        flash("用户名不能为空：没有用户名的账号 AI 拿来登录不了")
        return redirect(url_for("project_detail", pid=pid, tab="settings"))
    conn = get_db()
    try:
        env_id = _account_env_id(conn, pid, request.form.get("env_id"))
    except ValueError as exc:
        conn.close()
        flash(str(exc))
        return redirect(url_for("project_detail", pid=pid, tab="settings"))
    conn.execute(
        "INSERT INTO accounts (project_id, env_id, label, username, password, role, notes) "
        "VALUES (?,?,?,?,?,?,?)",
        (pid, env_id, request.form.get("label", ""),
         username, request.form.get("password", ""),
         request.form.get("role", ""), request.form.get("notes", "")),
    )
    conn.commit()
    conn.close()
    log_audit(f"user:{session['user']}", "add_account", f"project:{pid}",
              f"{username} / {request.form.get('label', '')}")
    return redirect(url_for("project_detail", pid=pid, tab="settings"))

@app.route("/projects/<int:pid>/account/<int:aid>", methods=["POST"])
@login_required
def account_update(pid, aid):
    """改账号：按 id 原地更新，不新增行（2026-10-23）。

    三条约定，都是为了守住"AI 读到的那份凭据必须是当前有效的那份"：
    1. username 必填——空用户名的账号 AI 登录不了，等于脏数据；
    2. password 留空 = 不修改，不是清空。只改标签/角色时不会把密码抹掉，
       也避免明文密码再被写进表单的 value 属性里（页面默认只显示圆点）；
    3. env_id 留空 = 不指定环境，与新增时的 `or None` 一致。

    审计只记"改了哪几个字段名"，不记字段值——密码不能进 audit 表。
    """
    conn = get_db()
    row = conn.execute("SELECT * FROM accounts WHERE id=?", (aid,)).fetchone()
    if not row:
        conn.close()
        flash("账号不存在")
        return redirect(url_for("dashboard"))
    # 越权防护：pid 只用于校验归属，真正定位靠 id。归属不符就跳回它自己的项目，
    # 而不是跳到 pid 指的那个页面（那个项目可能根本不存在，提示会被 404 吃掉）。
    if row["project_id"] != pid:
        conn.close()
        flash("该账号不属于该项目，未作改动")
        return redirect(url_for("project_detail", pid=row["project_id"], tab="settings"))

    username = (request.form.get("username") or "").strip()
    if not username:
        conn.close()
        flash("用户名不能为空")
        return redirect(url_for("project_detail", pid=pid, tab="settings", edit=aid))

    label = request.form.get("label", "")
    role = request.form.get("role", "")
    notes = request.form.get("notes", "")
    password = request.form.get("password", "")
    try:
        env_id = _account_env_id(conn, pid, request.form.get("env_id"))
    except ValueError as exc:
        conn.close()
        flash(str(exc))
        return redirect(url_for("project_detail", pid=pid, tab="settings", edit=aid))

    changed = []
    if label != row["label"]:
        changed.append("label")
    if username != row["username"]:
        changed.append("username")
    if role != row["role"]:
        changed.append("role")
    if notes != row["notes"]:
        changed.append("notes")
    if env_id != row["env_id"]:
        changed.append("env_id")
    if password:
        changed.append("password")

    if not changed:
        conn.close()
        flash(f"账号 {username} 没有改动")
        return redirect(url_for("project_detail", pid=pid, tab="settings"))

    conn.execute(
        "UPDATE accounts SET env_id=?, label=?, username=?, role=?, notes=? WHERE id=?",
        (env_id, label, username, role, notes, aid))
    if password:
        conn.execute("UPDATE accounts SET password=? WHERE id=?", (password, aid))
    conn.commit()
    conn.close()
    log_audit(f"user:{session['user']}", "update_account", f"account:{aid}",
              f"{username}: {','.join(changed)}")
    flash(f"已保存账号 {username}（改动：{', '.join(changed)}）")
    return redirect(url_for("project_detail", pid=pid, tab="settings"))

@app.route("/projects/<int:pid>/account/<int:aid>/delete", methods=["POST"])
@login_required
def account_delete(pid, aid):
    """删账号（硬删，2026-10-23）。

    accounts 是叶子表：executions / packets / bugs 都不带 account_id，删掉不产生
    悬空引用，所以不需要"先停用再删"那道闸。删是唯一的撤销手段——作废的账号如果
    留在库里，AI 每次会话都会读到它并拿去登录（skill 要求不问人直接取）。
    """
    conn = get_db()
    row = conn.execute("SELECT * FROM accounts WHERE id=?", (aid,)).fetchone()
    if not row:
        conn.close()
        flash("账号不存在")
        return redirect(url_for("dashboard"))
    if row["project_id"] != pid:
        conn.close()
        flash("该账号不属于该项目，未删除")
        return redirect(url_for("project_detail", pid=row["project_id"], tab="settings"))
    conn.execute("DELETE FROM accounts WHERE id=?", (aid,))
    conn.commit()
    conn.close()
    # log_audit 自开连接，必须等业务事务 commit + close 之后再调，否则 database is locked
    log_audit(f"user:{session['user']}", "delete_account", f"account:{aid}",
              f"{row['username']} / {row['label']}")
    flash(f"已删除账号 {row['username']}（{row['label'] or '无标签'}）")
    return redirect(url_for("project_detail", pid=pid, tab="settings"))

# ---------- 运行收尾通知（webhook，修复项 12） ----------

@app.route("/projects/<int:pid>/notify", methods=["POST"])
@login_required
def notify_save(pid):
    """保存/停用运行通知。校验规则与 API 完全同一套（core/notify.validate_notify）——
    网页端只是壳，避免"网页能存进去、API 读出来却是坏的"。"""
    action = request.form.get("action", "save")
    conn = get_db()
    if not conn.execute("SELECT id FROM projects WHERE id=?", (pid,)).fetchone():
        conn.close()
        flash("项目不存在")
        return redirect(url_for("dashboard"))
    if action == "disable":
        conn.execute("DELETE FROM project_settings WHERE project_id=? AND key='notify'",
                     (pid,))
        conn.commit()
        conn.close()
        log_audit(f"user:{session['user']}", "notify_disable", f"project:{pid}", "")
        flash("已停用运行通知")
        return redirect(url_for("project_detail", pid=pid, tab="settings"))
    value, err = validate_notify({
        "webhook_url": request.form.get("webhook_url", ""),
        "on": request.form.getlist("on"),
        "format": request.form.get("format", "wecom"),
    })
    if err:
        conn.close()
        flash(f"保存失败：{err}")
        return redirect(url_for("project_detail", pid=pid, tab="settings"))
    conn.execute(
        "INSERT INTO project_settings (project_id, key, value, updated_by, updated_at) "
        "VALUES (?,?,?,?,?) ON CONFLICT(project_id, key) DO UPDATE SET "
        "value=excluded.value, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
        (pid, "notify", json_dumps(value), f"user:{session['user']}", now()))
    conn.commit()
    conn.close()
    log_audit(f"user:{session['user']}", "notify_save", f"project:{pid}",
              f"{value['format']} / on={','.join(value['on'])}")
    flash("已保存运行通知（新的一轮收尾后会发到该 webhook）")
    return redirect(url_for("project_detail", pid=pid, tab="settings"))

@app.route("/projects/<int:pid>/notify/test", methods=["POST"])
@login_required
def notify_test(pid):
    """发一条测试通知：同步等结果，成功/失败都如实说。

    webhook 配错（key 过期、URL 打错）只有真发一次才知道——静默失败的通知
    等于没有通知。payload 用一条假 run，不碰真实数据。
    """
    conn = get_db()
    srow = conn.execute(
        "SELECT value FROM project_settings WHERE project_id=? AND key='notify'",
        (pid,)).fetchone()
    conn.close()
    cfg = None
    if srow:
        try:
            val = json.loads(srow["value"])
            if isinstance(val, dict):
                cfg, _ = validate_notify(val)
        except (ValueError, TypeError):
            cfg = None
    if not cfg:
        flash("还没有可用的通知配置，先保存再测试")
        return redirect(url_for("project_detail", pid=pid, tab="settings"))
    demo = {"id": 0, "project_id": pid, "name": "（测试）通知连通性检查",
            "kind": "selfcheck", "status": "done",
            "summary": {"total": 1, "pass": 1, "fail": 0, "blocked": 0, "skipped": 0},
            "finished_at": now()}
    ok, detail = post_webhook(cfg["webhook_url"], build_payload(demo, cfg["format"]))
    if ok:
        flash(f"测试通知已送达（{detail}），去你的群里看看")
    else:
        flash(f"测试通知发送失败：{detail}。检查 webhook 地址/机器人 key 是否有效")
    return redirect(url_for("project_detail", pid=pid, tab="settings"))

# ---------- Bug 上报标记（审核通过之后的一步） ----------

@app.route("/bugs/<int:bid>/reported", methods=["POST"])
@login_required
def bug_reported(bid):
    """标记「已抄进公司在线表格」/ 撤销该标记。

    status 轴已废弃：开发不在平台里跟进修复，平台只记录"我抄过去了没有"。
    approved + reported_at 空 = 待上报；有值 = 已上报（离开默认视图）。
    """
    value = request.form.get("value", "1")
    conn = get_db()
    bug = conn.execute(
        "SELECT project_id, review_status FROM bugs WHERE id=?", (bid,)).fetchone()
    if not bug:
        conn.close()
        return redirect(url_for("dashboard"))
    if value == "1" and bug["review_status"] != "approved":
        conn.close()
        flash("只有审核通过的 Bug 才能标记为已上报")
        return action_back(bug["project_id"], request.form.get("back"))
    ts = now() if value == "1" else ""
    conn.execute("UPDATE bugs SET reported_at=?, updated_at=? WHERE id=?",
                 (ts, now(), bid))
    conn.commit()
    conn.close()
    log_audit(f"user:{session['user']}",
              "bug_report_done" if ts else "bug_report_undo", f"bug:{bid}")
    return action_back(bug["project_id"], request.form.get("back"))

# ---------- 审核队列 ----------

@app.route("/review")
@login_required
def review():
    """跨项目待办收件箱：待审核 + 待上报，与项目页 Bug tab 共用一套分栏与详情组件。

    数据源是全项目汇总（项目页只看单个项目），批量处理也保留在这里；
    右栏一次显示一条，?sel=<id> 指定，缺省选队列第一条（待审核优先）。
    队列口径与导航栏角标同源（lists.bug_todo_where），点角标进来一定找得到人。
    """
    conn = get_db()
    bugs = lists.review_queue(conn)
    counts = lists.bug_todo_breakdown(conn)
    sel_bug, sel_atts = None, []
    sel_id = request.args.get("sel", type=int)
    if sel_id:
        sel_bug, sel_atts = lists.bug_detail(conn, sel_id)
    if sel_bug is None and bugs:
        sel_bug, sel_atts = lists.bug_detail(conn, bugs[0]["id"])
    sel_packets = packets_for_view(conn, "bug", sel_bug["id"]) if sel_bug else []
    conn.close()
    # 直接访问 /review（无参数）时也要有 back：带上 sel，审完才不会掉回项目页
    back_qs = qs_with(request.args, sel=sel_bug["id"]) if sel_bug else ""
    return render_template("review.html", bugs=bugs,
                           n_pending=counts["pending"], n_toreport=counts["toreport"],
                           sev_options=sorted(SEVERITY_LABELS.items()),
                           sel_bug=sel_bug, sel_atts=sel_atts, back_qs=back_qs,
                           sel_packets=sel_packets,
                           # 队列不分页，卡片链接直接带 sel，并保留前端筛选键
                           sel_qs={b["id"]: qs_with(request.args, sel=b["id"])
                                   for b in bugs})

@app.route("/review/<string:kind>/<int:item_id>")
@login_required
def review_detail(kind, item_id):
    """旧详情页已并入队列右栏，这里只做跳转（已有链接和书签不破）。"""
    if kind != "bug":
        abort(404)
    return redirect(url_for("review", sel=item_id))

@app.route("/review/batch", methods=["POST"])
@login_required
def review_batch():
    kind = request.form.get("kind", "")
    action = request.form.get("action", "approve")
    comment = request.form.get("comment", "")
    ids = request.form.getlist("ids", type=int)
    field = "review_status"
    qs = clean_qs(request.form.get("back"))

    # 项目页也能批量了：back 带 tab 的要回项目页，得知道是哪个项目
    pid = None
    if ids:
        conn0 = get_db()
        r0 = conn0.execute("SELECT project_id FROM bugs WHERE id=?", (ids[0],)).fetchone()
        conn0.close()
        pid = r0["project_id"] if r0 else None

    def back_to():
        """批量办完回原处：back 带 tab 的回项目页原筛选，否则回审核队列。"""
        if pid is not None and qs and dict(parse_qsl(qs)).get("tab"):
            return redirect(url_for("project_detail", pid=pid) + "?" + qs)
        return redirect(url_for("review") + (("?" + qs) if qs else ""))

    if kind != "bug" or action not in ("approve", "reject"):
        return back_to()
    if not ids:
        flash("请先勾选要处理的条目")
        return back_to()
    if action == "reject" and not comment.strip():
        flash("批量打回必须填写原因（将反馈给 AI 修改）")
        return back_to()
    category = ""
    if action == "reject":
        category = (request.form.get("reject_category") or "").strip()
        if category and category not in BUG_REJECT_CATS:
            flash(f"驳回分类不在词表内（可选 {'/'.join(BUG_REJECT_CATS)}）")
            return back_to()
    status = "approved" if action == "approve" else "rejected"
    conn = get_db()
    marks = ",".join("?" * len(ids))
    # 收件箱混着待审核与待上报，项目页默认视图也一样：批量通过只对还没通过的生效，
    # 否则"批量通过"会把已通过那条的审核意见清空（待上报被顺手重写一遍）。
    cur = conn.execute(
        f"UPDATE bugs SET {field}=?, review_comment=?, reject_category=?, updated_at=? "
        f"WHERE id IN ({marks})"
        + (" AND review_status != 'approved'" if action == "approve" else ""),
        (status, comment, category, now(), *ids))
    changed = cur.rowcount
    conn.commit()
    conn.close()
    log_audit(f"user:{session['user']}", f"review_batch_{action}",
              f"{kind}:ids={ids}",
              comment + (f" [{BUG_REJECT_CATS[category]}]" if category else ""))
    skipped = len(ids) - changed
    flash(f"已批量{'通过' if action == 'approve' else '打回'} {changed} 条"
          + (f"（{skipped} 条已通过，跳过）" if skipped > 0 else ""))
    return back_to()

@app.route("/review/<string:kind>/<int:item_id>", methods=["POST"])
@login_required
def review_action(kind, item_id):
    """单条审核：审核页、Bug 列表、Bug 详情页三处共用。

    项目页点进来的带 back（原筛选），办完回原处；审核页点进来的回队列。
    改判（approved <-> rejected）走同一个入口，不需要先退回待审核。
    """
    action = request.form.get("action", "")
    comment = request.form.get("comment", "")
    if kind != "bug":
        abort(404)
    if action not in ("approve", "reject"):
        return redirect(url_for("review"))

    conn = get_db()
    row = conn.execute(
        "SELECT project_id FROM bugs WHERE id=?", (item_id,)).fetchone()

    def back_to():
        if row:
            return action_back(row["project_id"], request.form.get("back"))
        return redirect(url_for("review"))

    if action == "reject" and not comment.strip():
        conn.close()
        flash("打回必须填写原因（将反馈给 AI 修改）")
        return back_to()

    category = ""
    if action == "reject":
        category = (request.form.get("reject_category") or "").strip()
        if category and category not in BUG_REJECT_CATS:
            conn.close()
            flash(f"驳回分类不在词表内（可选 {'/'.join(BUG_REJECT_CATS)}）")
            return back_to()

    if row:
        if action == "approve" and not comment.strip():
            # 改判通过时保留原驳回意见：一段历史不该被一次改判抹掉
            conn.execute(
                "UPDATE bugs SET review_status='approved', reject_category='', updated_at=? "
                "WHERE id=?",
                (now(), item_id))
        else:
            new_status = "approved" if action == "approve" else "rejected"
            conn.execute(
                "UPDATE bugs SET review_status=?, review_comment=?, reject_category=?, "
                "updated_at=?, "
                # 驳回表示这条不往上报，"已上报"标记一并清掉，避免"已驳回却已上报"
                "reported_at=CASE WHEN ?='rejected' THEN '' ELSE reported_at END "
                "WHERE id=?",
                (new_status, comment, category, now(), new_status, item_id))
        conn.commit()
    conn.close()
    audit_detail = comment + (f" [{BUG_REJECT_CATS[category]}]" if category else "")
    log_audit(f"user:{session['user']}", f"review_{action}", f"{kind}:{item_id}", audit_detail)
    return back_to()

# ---------- 设置 ----------

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    conn = get_db()
    if request.method == "POST":
        old = request.form.get("old_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        user = conn.execute("SELECT * FROM users WHERE username=?", (session["user"],)).fetchone()
        # 校验顺序：身份 → 两次输入是否一致 → 密码规则。
        # 每条失败各有文案：改造前三种原因共用一句"原密码错误或新密码太短"，
        # 用户不知道该改哪一项，等于没有提示。
        if not (user and check_password_hash(user["password_hash"], old)):
            reason, action, detail = "原密码错误", "change_password_failed", "原密码错误"
        elif new != confirm:
            reason = "两次输入的新密码不一致"
            action, detail = "change_password_failed", reason
        else:
            reason = passwords.check_new_password(new, old)
            action, detail = "change_password_failed", reason or ""
            if not reason:
                conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                             (generate_password_hash(new), user["id"]))
                conn.commit()
                action, detail = "change_password", ""
        conn.close()
        # PRG：无论成败都重定向，刷新不会重发 POST。
        # 改造前成功后直接 render，按 F5 会重发已失效的表单、提示变成"原密码错误"，
        # 用户误以为没改成，反而拿旧密码再改一次。
        log_audit(f"user:{session['user']}", action, "", detail)
        flash(reason or "密码已修改", "error" if reason else "ok")
        qs = clean_qs(request.query_string.decode())
        return redirect(url_for("settings") + (f"?{qs}" if qs else ""))
    tokens = rows_to_list(conn.execute("SELECT * FROM tokens ORDER BY id DESC"))
    # 日志 734 条，原来固定只取最近 50 条；现在可按操作者/动作/关键字筛，并翻页
    audits, apg, af = lists.audit_page(conn, request.args)
    actors, actions = lists.audit_options(conn)
    conn.close()
    return render_template("settings.html", tokens=tokens, audits=audits,
                           apg=apg, af=af, actors=actors, actions=actions,
                           pwd_hint=passwords.hint(),
                           audit_base=qs_with(request.args, apage=""))

@app.route("/settings/tokens/new", methods=["POST"])
@login_required
def token_new():
    name = request.form.get("name", "").strip() or "ai"
    token = "atk_" + secrets.token_hex(24)
    conn = get_db()
    conn.execute("INSERT INTO tokens (token, name, created_at) VALUES (?,?,?)",
                 (token, name, now()))
    conn.commit()
    conn.close()
    log_audit(f"user:{session['user']}", "create_token", name)
    flash(f"新 Token 已生成（下方列表可随时复制）：{token}")
    return redirect(url_for("settings"))

@app.route("/settings/tokens/<int:tid>/revoke", methods=["POST"])
@login_required
def token_revoke(tid):
    conn = get_db()
    conn.execute("UPDATE tokens SET revoked=1 WHERE id=?", (tid,))
    conn.commit()
    conn.close()
    log_audit(f"user:{session['user']}", "revoke_token", f"token:{tid}")
    return redirect(url_for("settings"))

@app.route("/settings/tokens/<int:tid>/delete", methods=["POST"])
@login_required
def token_delete(tid):
    """删除 Token：仅允许删除已吊销的，防止误删在用凭证。"""
    conn = get_db()
    row = conn.execute("SELECT revoked FROM tokens WHERE id=?", (tid,)).fetchone()
    if row and row["revoked"]:
        conn.execute("DELETE FROM tokens WHERE id=?", (tid,))
        conn.commit()
        log_audit(f"user:{session['user']}", "delete_token", f"token:{tid}")
    else:
        flash("只能删除已吊销的 Token（请先吊销）")
    conn.close()
    return redirect(url_for("settings"))

@app.route("/files/<path:filename>")
@login_required
def files(filename):
    return send_from_directory(UPLOAD_DIR, filename)

@app.route("/packets/<int:pkid>/download")
@login_required
def packet_download(pkid):
    """页面上的"下载响应原文"。与 API 的同名能力共用一套取文件逻辑。"""
    conn = get_db()
    row = conn.execute("SELECT resp_body, resp_body_file, resp_status FROM packets "
                       "WHERE id=?", (pkid,)).fetchone()
    conn.close()
    if not row:
        abort(404)
    if not (row["resp_body"] or "") and row["resp_body_file"]:
        # 只允许 uploads/packets 下的文件：basename 去掉任何路径成分
        return send_from_directory(os.path.join(UPLOAD_DIR, "packets"),
                                   os.path.basename(row["resp_body_file"]),
                                   as_attachment=True,
                                   download_name=f"packet-{pkid}-{row['resp_status']}.txt")
    if not (row["resp_body"] or "").strip():
        abort(410)
    return Response(row["resp_body"], content_type="text/plain; charset=utf-8", headers={
        "Content-Disposition": f"attachment; filename=packet-{pkid}-{row['resp_status']}.txt"})


@app.route("/packets/<int:pkid>/raw")
@login_required
def packet_raw(pkid):
    """原始报文：整段请求 + 整段响应，原样给出去。

    与"下载响应原文"的分工：那个只发响应体（做对比、算 diff 够用），
    请求行/请求头/响应头全丢；复核要看的是"这条请求打出去到底回了什么"，
    少了前半截等于只剩一半证据。这里不做任何裁剪，也不加分隔注释——
    整段复制出去就能和 Postman / Charles 里的原文逐行对齐。
    """
    conn = get_db()
    data = packet_bodies(conn, pkid, preview=False)
    conn.close()
    if not data:
        abort(404)
    text = raw_text(data)
    if request.args.get("download"):
        return Response(text, content_type="text/plain; charset=utf-8", headers={
            "Content-Disposition": f"attachment; filename={raw_name(pkid)}"})
    return Response(text, content_type="text/plain; charset=utf-8")

# ==================== API 端（AI 使用） ====================

# 字段档位：AI 按任务选档，避免把 evidence 数据包原文整表灌进上下文。
#   meta     = 目录清单（全项目 138 条约 1.7 万字符，一个模块几百字符）
#   contract = 契约（参数/响应/错误码/备注），不含 evidence
#   full     = 全字段（要复核历史数据包时才显式指定）

#   summary = 覆盖索引（标题/预期/锚点），用于判断"写过没有"

# 覆盖维度词表（cases.dims 只能取这些值，可多值）

# ---- 项目 / 环境 / 账号（只读为主，项目由用户在网页创建） ----

# ---- 文档 ----

# ---- 接口（一接口一记录，结构化） ----

# ---- 用例 ----

# ---- 执行结果（直接回填，不需审核） ----

# ---- Bug ----

# ---- 附件上传（证据：截图/数据包文件） ----

if __name__ == "__main__":
    # 本地默认仍只听 127.0.0.1；服务器（Docker）经 APP_HOST=0.0.0.0 放开
    host = os.environ.get("APP_HOST", "127.0.0.1")
    port = int(os.environ.get("APP_PORT", "8501"))
    try:
        from waitress import serve
        serve(app, host=host, port=port, threads=8)
    except ImportError:  # 本地 venv 没装 waitress 时退回 Flask 自带服务器
        app.run(host=host, port=port, debug=False)
