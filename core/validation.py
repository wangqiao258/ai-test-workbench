"""纯校验规则：文档类型、接口路径/域名、覆盖维度。无 IO，可单独单测。"""

import json

import re

DOC_TYPES = {
    "test_plan": "测试计划", "test_scheme": "测试方案", "test_report": "测试报告",
    "interface": "接口文档", "page": "页面说明", "flow": "业务流程",
    "analysis": "分析报告", "record": "过程记录", "general": "通用文档",
}

BUG_ATTACHMENT_HINTS = ("复现", "撤回", "复核结论", "证据补充", "补充说明")

STRUCTURED_MIN_LEN = 200

HOST_RE = re.compile(r"^https?://[^/\s?#]+$", re.I)

PATH_ERR = ("path 只能是路径部分（如 /admin-api/system/auth/login），不要带协议和域名。"
            "域名请用 host 字段（该接口有独立域名时）或项目环境的 base_url（同域名时），"
            "否则目录树无法按路径分段。")

HOST_ERR = ("host 格式应为 scheme://host[:port]，例如 https://api.example.com，"
            "不带路径、不带结尾斜杠。")

DIM_VOCAB = ("正常", "边界", "异常", "鉴权", "越权", "幂等", "并发", "兼容", "性能", "安全")

# Bug 提交前自检字段（2026-10-26 评审修复，均为可选但建议填）：
# 复现频率——"必现/经常/偶现/仅一次"直接决定值不值得跟；
# 影响范围——一句话说清哪些用户/场景受影响。
BUG_REPRO_VOCAB = ("always", "often", "sometimes", "once")
BUG_REPRO_LABELS = {"always": "必现", "often": "经常", "sometimes": "偶现", "once": "仅一次"}

# 驳回分类：驳回必填原因不变，分类可选。目的是统计"哪类误报最多"，
# 用数据告诉 AI 下次别再犯哪类（线上 57 投 55 驳，无统计就只能凭印象）。
BUG_REJECT_CATS = {
    "repeat": "重复提交",
    "unrepro": "不可复现",
    "lowharm": "危害不足",
    "misuse": "理解偏差/非缺陷",
    "noevidence": "证据不足",
    "other": "其他",
}

def validate_doc(dtype, title, content):
    """返回 None 表示通过；否则返回错误说明。"""
    if dtype not in DOC_TYPES:
        return ("dtype 必须是以下之一: " +
                ", ".join(f"{k}({v})" for k, v in DOC_TYPES.items()))
    if dtype == "interface":
        return ("interface 类型已废弃：接口文档 = 目录树/OpenAPI（由接口记录自动生成）。"
                "请改用 POST /api/interfaces 逐条提交接口（一接口一记录，附 evidence）；"
                "若是鉴权机制等叙述性说明，请用 analysis 或 flow。")
    if any(k in (title or "") for k in BUG_ATTACHMENT_HINTS):
        return ("该标题疑似 Bug 附属材料（复现/撤回/复核/补充说明类），不应作为独立文档。"
                "正确做法：1) 调用 PUT /api/bugs/<id> 把内容写入该 Bug 的 evidence；"
                "2) 或 POST /api/upload（multipart，字段 file，带 linked_type=bug、"
                "linked_id=Bug ID）上传截图/抓包。")
    if dtype in ("test_plan", "test_scheme", "test_report"):
        if len((content or "").strip()) < STRUCTURED_MIN_LEN:
            return (f"{DOC_TYPES[dtype]}属于结构化交付物，正文至少 {STRUCTURED_MIN_LEN} 字，"
                    "且应包含完整章节（如背景/范围/用例/结论），请补全后再提交。")
    return None

def normalize_host(value):
    """'https://api.x.com/' -> 'https://api.x.com'；空值 -> ''；非法 -> None。"""
    v = (value or "").strip().rstrip("/")
    if not v:
        return ""
    return v if HOST_RE.match(v) else None

def normalize_path(value):
    """接口路径只保留 path 部分：拒绝带协议/域名的写法，缺前导 / 时补上。"""
    p = (value or "").strip()
    if not p or "://" in p:
        return None
    return p if p.startswith("/") else "/" + p

def normalize_dims(raw):
    """dims 只接受词表内的值；兼容数组或逗号分隔字符串。返回 (dims, err)。"""
    if not raw:
        return [], None
    if isinstance(raw, str):
        raw = [s for s in re.split(r"[,，/、\s]+", raw) if s]
    if not isinstance(raw, (list, tuple)):
        return None, 'dims 应为数组，如 ["正常","边界"]'
    bad = [d for d in raw if d not in DIM_VOCAB]
    if bad:
        return None, f"dims 取值非法: {bad}；可选: {list(DIM_VOCAB)}"
    return list(dict.fromkeys(raw)), None

def parse_dims(raw):
    """cases.dims 以 JSON 数组存储；兼容旧数据/空值。"""
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        return list(raw)
    try:
        val = json.loads(raw)
        return list(val) if isinstance(val, list) else []
    except (ValueError, TypeError):
        return []

