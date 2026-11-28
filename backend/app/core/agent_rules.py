"""whoami 下发的默认 AI 规则；项目可在设置页覆盖。"""

from app.core.frameworks import AD_HOC_FRAMEWORK, KNOWN_FRAMEWORKS

DEFAULT_RULES: tuple[str, ...] = (
    "测试入口见 project.entries（名称、地址、备注，可能是页面或接口）；"
    "接口地址以 OpenAPI 文档 server、实际请求或有效 HAR 为准，不要用入口地址直接拼接 operation.path",
    "动作需要参数或请求体先读 action.detail，不要猜；requirements/next 默认处理返回条目，勿问总数或全量读取",
    "按 actions 顺序执行；需求与接口关联由测试请求自动建立",
    "已测接口优先复用，未覆盖的再按 tag / q 检索",
    "摘要只用于选接口，生成用例前必须读 /operations/{id} 详情",
    "Tavern marks 写 workbench:requirement:<需求ID>",
    "用例正文必须沉淀到项目测试仓库（project.testRepo.url，分支 testRepo.ref）："
    "生成后 commit 并 push，再上报 catalog；仓库未配置时先在项目设置填写",
    "catalog 只写索引，禁止只上报不落仓库；source(repo/ref/commit) 必须填实际仓库、"
    "分支和提交后的 commit",
    f"用例库接受任意框架名，建议用规范小写（如 {'、'.join(KNOWN_FRAMEWORKS)}）；"
    "catalog 不要用 script",
    f"临时脚本上报时 framework={AD_HOC_FRAMEWORK}，只留运行与证据，不进入用例库",
    "平台不执行测试：AI 自行选择框架（pytest、Tavern、Postman、Playwright、Cypress）"
    "在本机或外部环境执行，执行后通过 /ingest/v1/runs 上传结果与证据",
    "失败用例先归因再回写：随 run 传 analysis，findings 需含 nodeid、type、severity、"
    "confidence、root_cause、impact，有证据时带 exchange_index；"
    "type 只收 regression、spec-mismatch、contract、duplicate、flaky",
    "证据优先上传原始 HAR（浏览器、Playwright、代理工具导出的均可）；"
    "无法抓包时随 run 内联 cases[].exchanges",
    "有效 HAR：合法 JSON，至少一条 http(s) 的 XHR/Fetch 请求，能按 path 关联到被测接口；"
    "静态资源、埋点、第三方请求不计入",
    "HAR 需在运行上传后按 nodeid 上传，解析结果会替换该用例已有交换记录",
    "测试凭据只引用名称：pytest/Playwright 读环境变量（os.environ / process.env），"
    "Tavern 用 {tavern.env_vars.KEY}，值由插件注入，不要写死",
)
