# AI 协同测试工作台（本地版）

替代禅道的轻量测试管理工具：项目资料库 + 测试用例 + 执行记录 + Bug 管理（强制证据）。
平台、runner、执行观测、回归对比和 AI 持续生成目标池均已上线；执行由 `runner` 完成
（`/api/runs` + 认领/回填/收尾），AI 负责分析、生成与判读，人只审 Bug 和管理项目。

## 启动

```bash
python app.py
```

浏览器打开 http://127.0.0.1:8501 ，默认账号 `admin / admin123`（首次登录后到"设置"改密码）。

数据全部在 `data/` 目录：`app.db`（SQLite 数据库）+ `uploads/`（截图等证据附件）。备份整个目录即可。

## 部署到服务器（Docker）

完整设计与决策记录见 `docs/部署与执行引擎设计.md`。当前部署为平台 + 按需启动的 runner 双镜像，内网纯 HTTP。

首次部署（CentOS Stream 9）：

```bash
sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo systemctl enable --now docker
# 代码 git clone（或 scp）到 /opt/ai-test-platform；数据整体拷贝 data/
cd /opt/ai-test-platform
docker compose -f deploy/docker-compose.yml up -d --build
```

日常更新：`./deploy/update.sh`（自动：备份 → git pull → 构建 → 副本库 smoke → 绿才重启，任何一步失败都不切换）。

- 容器以 root 运行、内网纯 HTTP（8501 直接开放）是 2026-10-23 的明确取舍，风险与退出条件见设计文档 §10
- runner 使用独立的 API Token（设置页，命名 runner）：审计里 `ai:runner` 与 `ai:workbuddy` 分开，吊销互不影响；未配置时按需启动 runner
- 备份：update.sh 每次自动热备到 `backups/`；手动 `sqlite3 data/app.db ".backup backups/xxx.bak"` 同样可用

### 环境变量（真实地址不进仓库）

文档里的 `127.0.0.1`、`test.example.com` 都是占位符，按自己的环境设置：

| 变量 | 用途 | 默认 |
|---|---|---|
| `PLATFORM_URL` | runner 连平台 | `http://127.0.0.1:8501` |
| `RUNNER_TOKEN` | runner 用的 API Token（设置页生成） | 空 |
| `UI_HOST` / `UI_HOST_IP` | runner 里把页面域名指到内网 IP（compose 的 `extra_hosts`） | `test.example.com` / `127.0.0.1` |
| `APP_HOST` / `APP_PORT` | 平台监听地址 | `127.0.0.1` / `8501` |
| `APP_MAX_UPLOAD_MB` | 上传大小上限 | `50` |
| `VERIFY_SSL` | runner 是否校验被测系统证书 | `0` |
| `HEADLESS` | UI 用例是否无头运行 | `1` |
| `DIAG_TARGET` | `deploy/diag_443.sh` 的默认诊断目标 | `test.example.com` |

## 目录结构

```
ai-test-platform/
├── app.py              入口 + 网页端路由
├── db.py               SQLite schema、增量迁移、审计日志
├── openapi_gen.py      由 interfaces 表生成 OpenAPI 3.0
├── core/               纯规则层（不依赖 Flask 请求上下文，可单测）
│   ├── validation.py   文档类型、接口路径/域名、覆盖维度
│   ├── steps.py        结构化步骤：校验 / 渲染 / 分步结果推导
│   ├── anchors.py      用例锚点、接口关联表、行为与标题查重
│   ├── generation.py   测试目标、生成策略与测试意图指纹
│   ├── coverage.py     覆盖缺口的唯一口径：接口覆盖、UI 覆盖、零缺口清单与派活目标
│   ├── filters.py      列表页筛选字段规格、词表校验、多值 IN、分页（纯函数）
│   ├── lists.py        各列表的查询：筛选 SQL + COUNT + 分页 + 排序
│   └── openapi_doc.py  装配 OpenAPI（网页与 API 共用）
├── api/                /api/* 全部端点（Flask 蓝图，url_prefix=/api）
│   ├── __init__.py     注册蓝图
│   ├── common.py       字段档位、通用查询、行转换
│   ├── deps.py         X-API-Token 鉴权
│   └── meta / projects / docs / interfaces / cases / executions / generation / bugs / coverage / upload
├── start.bat           Windows 一键启动
├── deploy/             Docker 平台/runner 镜像、Compose 与更新脚本
├── runner/             执行引擎：只走公开 API 的独立包，默认按需启动
├── requirements.txt
├── README.md
├── templates/          页面模板（project 只留 tab 框架，各面板在 _panel_*.html）
│   ├── _macros.html    筛选控件 / 结果计数 / 分页（列表页共用）
│   ├── _bug_actions.html  Bug 页共用脚本：驳回必须填原因
│   ├── _bug_bulk.html     批量操作条：全选 / 已选计数 / 批量通过驳回（项目页与审核页共用）
│   ├── _detail_bug.html   Bug 卡身 + 顶部 sticky 操作条（项目页右栏、独立详情页、审核队列三处共用）
│   ├── _detail_interface.html  接口契约的唯一渲染处（详情页 + 目录树右栏共用）
│   ├── _panel_*.html   docs / interfaces / cases / bugs / runs / settings 六个面板
│   ├── _iface_*.html    interfaces 面板的两个视图：list / tree
│   ├── _panel_itf_contract.html  目录树右栏片段（panel.html 的模板）
│   └── case_detail.html、bug_detail.html  列表点进去看的全文页
├── static/style.css
├── data/               运行时数据，不要提交/乱放
│   ├── app.db          主数据库
│   ├── api-token.txt   AI 用的 API Token（明文，仅本机）
│   └── uploads/        证据附件
├── docs/               当前设计、部署与运维文档
│   ├── ai_guide.md     AI 开场手册（规则唯一真相源，约 5.6k 字符）
│   ├── ai_guide_reference.md  参考手册：接口字典/Bug/runs/错误码（按需查）
│   ├── 当前设计说明.md  模块筛选、用例锚点、行为查重、Bug 分诊规则
│   ├── 部署与执行引擎设计.md
│   ├── 执行任务管理与观测边界.md
│   └── 数据包证据.md
├── tests/              可复跑的验证脚本（均不污染主库）
│   ├── run_all.py      一键跑完本目录（失败不中断，最后汇总）
│   ├── test_core.py    core/ 纯规则单测（不起 Flask、不连库）
│   ├── test_filters.py 筛选、分页与 back 白名单纯函数测试
│   ├── smoke_api.py    API 冒烟、迁移兼容与字段裁剪
│   ├── verify_bug_views.py、verify_bug_review.py  Bug 分诊、审核与上报
│   ├── verify_filters.py、verify_split.py、verify_review_split.py  页面筛选与分栏
│   ├── verify_module_groups.py、verify_multi_select.py  模块分组与多选
│   ├── verify_coverage_gaps.py  两条覆盖轴、缺口派活（from-gaps）与 UI 用例提示
│   ├── verify_pages.py、verify_ui_contract.py  页面渲染巡检与模板 JS 契约
│   ├── verify_api_gaps.py  Token 鉴权矩阵与未覆盖端点
│   └── verify_generation.py  持续生成目标、行为查重与执行反馈
├── scripts/            运维脚本（不参与测试，按需手动跑）
│   ├── backfill_anchors.py        存量用例补锚点/维度（幂等）
│   ├── backfill_run_kind.py       存量 run 回填 kind
│   ├── backfill_run_scope.py      孤儿执行回填 run_id
│   └── backfill_verify_status.py  存量接口修正 verify_status
└── backups/            所有人工备份，按时间命名
```

**依赖方向**：`app.py` / `api/*` → `core/*` → `db.py`。`core/` 只做纯函数与数据装配，
不 import Flask 的请求对象；反过来 `core/` 不允许 import `api/` 或 `app`。

**改完怎么验**：`python -u tests/run_all.py` 顺序跑完 `tests/` 下所有脚本（每个独立进程 + 副本库，
失败不中断，最后汇总；`-k bug` 只跑文件名匹配的，`--stop` 遇错即停，退出码可直接进 CI）。
进度是流式的：每个脚本打 `RUN`、静默 10 秒打心跳、结束打 `PASS/FAIL`，全量约 1 分钟；
默认不转发脚本全文，需要看得加 `-v`。命令别接 `| Out-String`，那会把输出攒到结束才显示
（`-u` 必须加，否则块缓冲同样看不见进度），详见 `AGENTS.md`。
新增脚本按 `test_*` / `verify_*` 命名就会被自动收进来。`scripts/` 里的回填脚本不在其中，
它们会写库，必须手动 `--apply`。

**备份约定**：`backups/YYYYMMDD-HHMM_<原文件名>.bak`，例如 `20261022-0914_app.db.bak`。
代码与数据库的备份一律进 `backups/`，不要放在根目录或 `data/` 里——`data/` 只放运行时文件。
`data/app.db` 是 WAL 模式，热备请用 `sqlite3 data/app.db ".backup backups/xxx_app.db.bak"`，
直接 `cp` 在写入瞬间可能少最后一笔事务（本项目单机低频写入，实际影响很小）。

## 网页端列表：筛选、分页与详情

列表页只负责"找到那一条"，全文都在详情页。Bug 例外：它已经改成左右分栏，左栏索引、右栏就地看全文并审核。

| 列表 | 每页 | 可筛字段 | 全文去哪 |
|---|---|---|---|
| 项目文档 | 全部 | 类型、关键字（标题/提交人） | `/docs/<id>` |
| 接口（列表） | 50 | 分组、模块（多选）、方法、关键字（路径/名称/模块） | `/interfaces/<id>` |
| 接口（目录树） | 全部 | 顶部搜索框（路径/名称/模块，边输边过滤） | 右侧面板按需取 `panel.html` |
| 测试用例 | 50 | 分组、模块（多选）、优先级、覆盖维度、执行结果、锚点、关键字 | `/cases/<id>` |
| **Bug（分栏）** | **20** | 进度（未结案/待审核/待上报/已上报/已驳回/全部）、严重程度、模块、关键字 | **右栏就地显示**（`?sel=<id>`），可勾选批量，也可单独打开 `/bugs/<id>` |
| **Bug 待办（收件箱）** | 全部 | 进度（待审核/待上报）、项目、严重程度、有无证据、关键字（前端即时过滤） | **右栏就地显示**（`?sel=<id>`），可勾选批量 |
| 操作日志 | 50 | 操作者、动作、关键字 | — |

几条约定：

- **筛选状态全在 URL 里**：`?tab=cases&priority=P0&result=fail&page=2` 可刷新、可分享、可前进后退。
  切 tab 会重置（筛选参数跨 tab 没有意义），从详情页返回会带回原来的筛选。
- **模块分组是模块名的派生视图**：`侧边栏-客户` 的组头是 `侧边栏`，`?group=侧边栏` 等价于
  `module='侧边栏' OR module LIKE '侧边栏-%'`。接口页和用例页都有分组下拉，选了分组后模块
  面板收窄到该组；没有 `-` 的模块（系统 / 认证）不进分组，仍是普通选项。规则见
  `docs/当前设计说明.md`。
- **模块可多选**：`?module=A&module=B` 是并集，网页和 `/api/*` 用同一套语义——页面上选好的
  URL 直接给 AI，换成 `/api/interfaces` 就是同样的范围。多选面板底部实时显示「N 个模块 ·
  M 条接口」。见 `docs/当前设计说明.md`。
- **Bug 分栏的状态也全在 URL 里**：`?tab=bugs&sel=39&b_review=pending`。缺 `sel` 时默认选中当前页第一条，
  所以打开 tab 就有内容；翻页会清空 `sel`（换页后上一条多半不在本页，留着会高亮错位）。
  `sel` 指向别的项目时当作没选，一律回退到本项目第一条。
- **分栏左栏只放索引卡片**，卡片是纯链接，按钮全部在右栏顶部 sticky 操作条里——证据最长 17457 字符，
  按钮放页尾等于让人滚到底再找。左栏 20 条/页是按 70vh 可视高度算的（卡片约 76px，一屏 9~12 张）。
- **窄屏降级**：`≤1400px` 左栏压到 420px，`≤1120px` 改成上下堆叠、操作条取消 sticky。
- **词表外的参数不生效**：模块下拉的候选来自项目内实际值，手改 `?module=xxx` 不会筛出空页。
  接口的验证状态暂时没做下拉——现在 161 条全是 verified，加了也没有区分度，等出现 changed 再说。
- **列表页不渲染正文**：用例的 steps、Bug 的 evidence 只在详情页出现。接口目录树只带节点字段，
  契约点开才取，161 条接口的首屏从 686 KB 降到 54 KB。
- **「接口」是一个 tab、两个视图**：`?tab=interfaces&view=list|tree`。原来的「接口文档」tab
  （`?tab=apidoc`）已合并进来——两者是同一张 `interfaces` 表的只读视图，搜索/契约/验证状态完全重叠。
  旧链接一律 302 到 `?tab=interfaces&view=tree`，书签和 `back` 参数都不会失效。
  契约正文只有一份 `_detail_interface.html`：详情页和目录树右栏（`panel.html`）共用，
  加字段不用改 JS；方法徽标全站一套 `.badge.method-*`。
  分工：列表＝检索与给 AI 圈范围，目录树＝按 URL 结构浏览并看证据/覆盖。
  目录树里**点文件夹也有右栏内容**：该目录（含子目录）的接口数、方法分布、已验证/有变更/未验证
  计数和未验证清单；点接口才换成契约。否则停在目录上时右栏会挂着上一条接口，像"点了没反应"。
- **不内置 Swagger 页面**：标准文档的出口只有「导出 openapi.json」（OpenAPI 3.0，可导入
  Apifox / Postman / IDE）。2026-10-27 删掉了原有的 Swagger UI 视图：AI 从不渲染页面
  （它走 `/api/interfaces` 切片，比全量文档轻一个数量级），平台内也没有"只想读文档"的读者，
  留着等于多一个每天要选一次、却没人打开的入口。若日后确有对外展示需求，
  应做成独立只读门户（`/projects/<id>/docs`），而不是塞回测试工作台的 tab。
- **详情页的"返回"走 `back` 参数**，只认 `tab/module/q/page/sel/fp/fe/fv/fq/fs/...` 白名单键，挡住外部跳转。
- **三处 Bug 详情共用一份 `_detail_bug.html`**：项目页右栏、`/bugs/<id>`、待办收件箱右栏。`/review/bug/<id>`
  已改为 302 到 `/review?sel=<id>`。办完事回哪由 `back` 决定：带 `tab` 回项目页原筛选，不带 `tab`（审核页的
  `fp/fs/fe/fv/fq`）回 `/review` 并保留队列筛选。导航栏的「Bug 审核」后面显示未结案数（待审核 + 待上报），
  收件箱按同一口径取数——两边各写一套 SQL 时出过"角标 1、点进去空的"。
- **Bug 只有一条轴：分诊进度**（2026-10-22 废弃 status 轴）。四态由 `review_status` × `reported_at` 组合：
  待审核（pending，未上报）→ 待上报（approved，未上报）→ 已上报（approved，有上报时间）；旁支已驳回（rejected）。
  **默认视图 = 未结案 = 待审核 + 待上报**，一条记录只有"已上报"或"已驳回"才离开视野。
  项目页默认视图按「进度」单下拉切换，导航栏的「Bug 审核」显示未结案数。规则见 `docs/当前设计说明.md`。
- **项目页与待办收件箱是同一套分栏**：同一个卡片结构、同一个 `_bug_bulk.html` 批量条、同一个
  `filter-bar compact` 筛选网格、同一个 `_detail_bug.html` 详情。唯一差异是分页——项目页 20 条/页
  （要看全量 39 条），收件箱全量不分页（未结案处理完就没了）。批量操作两边都能用。
- 列表查询集中在 `core/lists.py`，筛选项声明在各函数的 `*_spec` 里：加一个筛选条件通常只加一行 `Field`。

## 安全模型

- 本地只监听 127.0.0.1，局域网访问不到；服务器部署（Docker，APP_HOST=0.0.0.0）为内网纯 HTTP——出内网/上域名前必须先加 HTTPS 反代
- 上传证据文件有白名单（png/jpg/jpeg/gif/webp/har/txt/json/log/pdf/mp4）+ 50MB 上限（`APP_MAX_UPLOAD_MB` 可配），越词表 400、超限 413，均返回 JSON
- 网页端：账号密码登录
- API 端：请求头必须携带 `X-API-Token`（在"设置"里生成，可吊销）
- **只有 Bug 进待审核**：误报会让开发白干，驳回还会改变下游可见性。文档、接口、用例全部免审，AI 提交即生效
- 接口的可信度由 `verify_status` 表达（`verified` 有数据包证据 / `unverified` 无证据 / `changed` 契约改过待复测），不由审批表达。改契约字段会自动降为 `changed`，补新证据则回到 `verified`
- 测试执行结果 AI 直接回填，事后统一查看
- Bug 只有一条分诊轴：`review_status`（待审核/已通过/已驳回）+ `reported_at`（是否已抄进公司在线表格）。
  平台**不管开发修没修**——开发只在我们自己的在线表格跟进。默认视图只显示未结案（待审核 + 待上报）
- 设置页可查看最近 50 条操作日志

## AI 使用前提

**AI 手册分两份**（2026-10-27 拆开，控制开场 token）：

| 文件 | 内容 | 读取方式 |
|---|---|---|
| `docs/ai_guide.md` | 开场必读：基本信息、角色、铁律、标准流程（约 5.6k 字符） | 每个会话都读 |
| `docs/ai_guide_reference.md` | 接口字典、用例、Bug、runs、错误码（约 24k 字符） | **按需查，不整篇读** |

平台通过 `GET /api/guide` 返回开场手册、`GET /api/guide?part=reference` 返回参考手册
（响应带 `path` / `chars` / `part`）。改规则只需改这两个文件再部署，所有 AI 下次会话自动生效。

**Skill 只做路由**：`~/.workbuddy/skills/ai-test-platform/SKILL.md` 只放平台地址、Token/手册的位置、开场三步，
**一条规则都不复制**（连"三条铁律"也不放）。此前 skill 里另有一份 `references/api_reference.md`，与手册同源，
已在 2026-10-23 归档到 `backups/20261023-1200_skill-ai-test-platform-references/` —— 两处写同一套规则会漂移，不再这么做。

`/api/guide` 的查找顺序：`APP_GUIDE_PATH`（env 指定）→ `docs/ai_guide.md` → `data/ai_guide.md`（不动镜像替换用）；
参考手册找 `docs/ai_guide_reference.md` → `data/ai_guide_reference.md`。
镜像需要这两份文件：`.dockerignore` 里的 `*.md` / `docs/*` 之后各有一条 `!` 放行，Dockerfile 再 COPY 一次。
`tests/smoke_api.py` 断言开场手册 < 9k 字符、参考手册 < 40k，超了就让构建失败——防止手册无限膨胀。

## API 速查

所有 API 需请求头：`X-API-Token: <token>`

| 操作 | 方法与路径 |
|---|---|
| 连通性检查 | GET /api/ping |
| AI 开场手册（规则唯一真相源） | GET /api/guide （返回 docs/ai_guide.md 原文 + part/path/chars） |
| AI 参考手册（按需查） | GET /api/guide?part=reference （返回 docs/ai_guide_reference.md 原文） |
| 项目列表 | GET /api/projects |
| 项目环境/账号 | GET /api/projects/{id}/environments 、/accounts（只读：账号的增删改只在网页「环境与账号」里做） |
| 读文档/用例 | GET /api/docs?project_id=1 、GET /api/cases?...&fields=summary |
| 读接口清单/单个（字段可裁剪） | GET /api/interfaces?...&fields=meta｜contract｜full 、GET /api/interfaces/{id} |
| 覆盖矩阵（冷启动找空白） | GET /api/coverage?project_id=1&module=侧边栏-素材（另带 `totals.interface_coverage`、`ui`、`gaps`：零用例模块 / 零 UI 用例模块；`?ui=full` 展开页面明细） |
| **登记 / 查询测试目标** | POST/GET /api/test-targets（具体风险、六种生成策略、目标状态） |
| **按缺口派活**（零覆盖模块 / 零 UI 模块） | POST /api/test-targets/from-gaps {project_id, limit?, include: api\|ui\|both}（按指纹去重，幂等） |
| **领取下一个新目标** | POST /api/test-targets/next {project_id, strategy?, generation_batch_id?}（无目标时返回 gap_hints） |
| **目标反馈 / 批次收尾** | POST /api/test-targets/{id}/feedback 、POST /api/generation-batches/{id}/finish |
| **多个模块一起读** | `/api/interfaces`、`/api/cases`、`/api/coverage` 支持重复键 `?module=A&module=B`（并集）；coverage 另支持 `?group=侧边栏`（整块） |
| 模块词表 | GET /api/modules?project_id=1 |
| 提交用例（免审，直接生效） | POST /api/cases {project_id, interface_id 或 interface_ids, title, dims, ...} |
| 改用例（补维度/换锚点） | PUT /api/cases/{id} |
| 提交文档（免审，直接生效） | POST /api/docs {project_id, dtype, title, content, evidence} |
| 回填执行结果 | POST /api/cases/{id}/executions {result: pass/fail/blocked, actual_result, evidence} |
| 提 Bug（待审核，必须带证据） | POST /api/bugs {project_id, title, module, severity, steps, evidence} |
| 提交接口（一接口一记录，免审） | POST /api/interfaces {project_id, module, name, method, path, host?, ...} |
| 复测更新接口（自动维护 verify_status） | PUT /api/interfaces/{id} |
| 补充/修正 Bug（重新待审核） | PUT /api/bugs/{id}（evidence_append 追加证据，保留历史） |
| 上传证据文件（截图等，白名单+50MB） | POST /api/upload （multipart 表单，字段 file） |
| 导出 OpenAPI 活文档 | GET /api/projects/{id}/openapi.json （全量；可信度看每条的 description 首行或 x-verify-status；网页只给下载入口，导入 Apifox/Postman/IDE 使用） |
| **建一轮执行**（P1） | POST /api/runs {project_id, scope, reason, kind?}（kind：regression/selfcheck/diagnostic） |
| **批次列表 / 详情** | GET /api/runs?project_id=&status= 、GET /api/runs/{id}?with_cases=1 |
| **runner 认领 / 心跳 / 收尾** | POST /api/runs/{id}/claim {runner_id} 、POST /api/runs/{id}/heartbeat 、POST /api/runs/{id}/finish |
| **手动收掉一轮（僵尸兜底）** | POST /api/runs/{id}/cancel {note}（running/queued → failed） |
| **项目鉴权配置** | GET/PUT/DELETE /api/projects/{id}/settings/auth |

规则提醒（给 AI）：接口必须附真实请求/响应数据包作为 evidence；文档/接口/用例提交即生效，不要等审核。

## AI 持续生成新用例

平台用 `test_targets` 持久化待探索风险，用 `generation_batches` 记录每轮生成。AI 领取目标后提交带 `target_id`、`generation_batch_id`、`novelty` 的新用例；服务端按测试行为指纹查重，执行结果自动回写目标，失败目标可继续派生 `failure_driven` 子目标。完整工作流和提示词规则只维护在 `docs/ai_guide.md`（开场）与 `docs/ai_guide_reference.md`（细节）。

验证：`python tests/verify_generation.py`（使用独立空库，不读取或修改真实 `data/app.db`）。

## 执行引擎（P1，按需启动）

平台自己**不执行**用例；执行交给 `runner`，它只通过上面的公开 API 读写，不碰数据库。
设计见 `docs/部署与执行引擎设计.md` §6。

### 一条用例要能自动执行，必须带 checks

`steps_json` 的每一步，除了给人看的 `expect`，再加一组机读断言 `checks`：

```json
{"kind": "api", "steps": [{
  "action": "用错误密码登录",
  "request": {"method": "POST", "path": "/admin-api/system/auth/login",
              "headers": {"tenant-id": "163"},
              "body": {"username": "xxx", "password": "wrong"}},
  "expect": "code != 0 且不返回 accessToken",
  "checks": [{"src": "status", "op": "eq", "value": 200},
             {"src": "body", "path": "$.code", "op": "ne", "value": 0},
             {"src": "body", "path": "$.data.accessToken", "op": "absent"}]
}]}
```

- `src`：`status` / `body` / `headers` / `duration_ms`
- `op`：`eq / ne / contains / not_contains / present / absent / gt / lt / regex / in`
- `path`：简化 jsonpath，`$.data.list[0].id`；不写 path 时 body 按**原文**匹配
- **任何一步没有 checks，整条用例被跳过**（`summary.skipped`），不拿 `expect` 猜

步骤之间可以取值：`request` 的 headers / query / body 里写
`{{steps.<步骤号>.<字段路径>}}`（如 `{{steps.1.data.accessToken}}`）或
`{{account.username}}` / `{{account.password}}`。整串是一个占位符时保留原类型。

存量用例大多只有文本步骤，P1 不会自动跑；要跑先 `PUT /api/cases/<id>` 补 `steps_json.checks`。

### 配项目鉴权（每个项目一次）

```bash
curl -X PUT http://127.0.0.1:8501/api/projects/1/settings/auth \
  -H "X-API-Token: $TOKEN" -H "Content-Type: application/json" -d '{
  "value": {"type": "login", "method": "POST",
            "path": "/admin-api/system/auth/login",
            "headers": {"tenant-id": "163"},
            "body": {"username": "{{username}}", "password": "{{password}}", "clientType": "h5"},
            "token_path": "$.data.accessToken"}}'
```

`type=login` 会用项目账号换 token；账号默认取项目第一条，可用 `account_id` 指定。
小程序这类拿不到登录流程的，用 `{"type":"static","static_headers":{"Authorization":"Bearer xxx","tenant-id":"163"}}`。

### 建一轮 → 起 runner → 看结果

```bash
# 1. 建一轮（scope 四选一：case_ids / batch / module / group）
curl -X POST http://127.0.0.1:8501/api/runs \
  -H "X-API-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"project_id":1,"scope":{"batch":"接口回归-会员侧"},"reason":"发布前回归"}'

# 2. 显式起 runner（默认不在 compose 里启动，避免以为它一直在跑）
RUNNER_TOKEN=atk_xxx docker compose -f deploy/docker-compose.yml --profile runner up -d runner

# 本地跑一轮就退出：
PLATFORM_URL=http://127.0.0.1:8501 API_TOKEN=atk_xxx RUN_ONCE=1 python -m runner

# 本机常驻（不依赖 AI 会话，建了 run 就自动执行）：双击 start_runner.bat
```

> 服务器出网 443 常被静默丢包，只有内网 IP 通。所以 compose 给 runner 留了 `extra_hosts`：
> 用 `UI_HOST` / `UI_HOST_IP` 把页面域名指到内网 IP。URL 仍按域名加载（静态资源是绝对路径、
> Cookie 绑域名、证书签给域名），别把地址直接换成 IP，否则证书和 Cookie 都对不上。
> 起 runner 之前先确认"它能不能访问被测系统"：`DIAG_TARGET=<你的域名> bash deploy/diag_443.sh`；
> 不通时 UI 用例在 `goto` 阶段记 blocked（不是 fail），API 用例同样会 blocked。
> runner 镜像基于 Playwright 官方镜像，浏览器已内置，不需要另装。

读结果：`GET /api/runs/<id>` 给 `summary {total,pass,fail,blocked,skipped}` 与全部 executions；
每步的完整请求/响应在 packets 里（`linked_type=execution`、`linked_id=该次执行 id`）。

看进度：列表与详情都带 `progress {total,done,pass,fail,blocked,left}`（按 executions 现算）和
`stalled`（`running` 且 180 秒无心跳）。`summary` 只在 finish/cancel 时是终值，跑到一半它的
pass/fail 恒为 0——问"跑完没、跑到哪"要看 `progress`，不要读 `summary`。
`GET /api/runs?status=stalled` 筛卡住的轮次；`POST /api/runs/{id}/cancel {note}` 收尾（note 必填），
收尾后不能再回填/心跳。runner 关窗口不再留僵尸：runner 侧有 `finally`+SIGINT 兜底。

轮次类型 `kind` 与状态正交：`regression` 回归 / `selfcheck` 自检 / `diagnostic` 诊断，缺省回归。
自检和诊断轮不能当回归基线看——列表按类型筛选，历史 16 条已用 `scripts/backfill_run_kind.py` 回填。

网页端：项目页「运行」tab 是只读列表（类型、状态、进度、执行者、卡住标记），点进 `/runs/<id>` 看明细、
还没跑到的用例、跑不了的原因，以及唯一的操作按钮「收尾为 failed」。

状态机只有 `queued → running → done/failed`（`queued`/`running` 可直接 `failed` = 取消）。
`claim` 是原子抢占，第二个 runner 拿到 409；一个 run 内串行执行。

用例的锚点与多接口关联：`interface_id` 是主锚点（决定 module 归属），`interface_ids` 是这条用例覆盖的全部接口
（例：一条"分页边界"用例同时挂 3 个列表接口）。`GET /api/cases?interface_id=N` 按关联表匹配，
`GET /api/coverage` 会把同一条用例计入每个关联接口的覆盖情况。

结构化步骤（可选，接口类用例推荐）：`POST /api/cases` 传 `steps_json`，平台校验后自动渲染出人看的
`steps` 文本（只维护一份数据）。回填执行结果时可传 `step_results`，总结果由分步结果推导，
传了 `result` 但与推导值矛盾会被 400 拒绝。

```json
{"project_id":1,"interface_id":3,"title":"...","dims":["异常"],
 "steps_json":{"kind":"api","steps":[
   {"action":"用错误密码调登录","request":{"method":"POST","path":"/admin-api/system/auth/login",
     "headers":{"tenant-id":"163"},"body":{"username":"...","password":"wrong"}},
    "expect":"code != 0 且不返回 accessToken"}]}}
```

文档写入规范（服务端强制校验，违反会被 400 拒绝并记录审计）：
1. dtype 必须取自：test_plan 测试计划 / test_scheme 测试方案 / test_report 测试报告 / page 页面说明 / flow 业务流程 / analysis 分析报告 / record 过程记录 / general 通用文档。interface 已废弃：接口文档 = 目录树/OpenAPI（由 /api/interfaces 自动生成）。
2. **Bug 的复现记录、撤回说明、复核结论、证据补充等不是文档**，不得 POST /api/docs；应写入该 Bug：PUT /api/bugs/<id> 更新 evidence，或 POST /api/upload（multipart，字段 file，带 linked_type=bug、linked_id=Bug ID）上传截图/抓包。标题含"复现/撤回/复核结论/补充说明"等词会被直接拒绝。
3. test_plan / test_scheme / test_report 是结构化交付物，正文不少于 200 字且应含完整章节（背景/范围/用例/结论等），一句话"文档"会被拒绝。
4. 一时拿不准归类的分析性内容用 analysis 或 record，不要全塞 general。

## 接口文档的域名处理

域名是接口的**属性**，不是目录树的固定层级：

- `path` 只写路径（如 `/admin-api/system/auth/login`）。带 `https://域名` 会被 400 拒绝——域名混进路径会让树无法按段分层。
- 同一域名（= 项目环境 `base_url`）的接口，`host` 留空；只有该接口与项目其他接口**不同域名**时才填 `host`（`https://api.example.com`，不带路径和结尾斜杠）。
- 目录树默认只按路径分段；项目里 `distinct` 域名 ≥ 2 时才自动在最上层长出域名层，并在页头提示。单域名项目不会多这一层。
- 页头常显"服务地址"（可复制，多环境时可切换），接口详情页显示"完整地址"。OpenAPI 里域名进 `servers`（独立域名的接口用 operation 级 `servers`），`paths` 始终只有路径。


---

## 数据包证据 packets（2026-10-22）

### 为什么加这一层

原来一次实测的报文塞在 `evidence` 一个文本框里，服务端只判 `bool(text.strip())`。
实测后果：161 条接口全部 `verified`，但只有 22% 含「请求行 + 状态码 + 响应体」，
最短的一条是 10 个字符 `GET -> 200`；另有 16 条接口、37 条执行记录的响应体被截断在
半个 JSON 中间（最长一条正好 20000 字符，停在 `{'dictTy`）。

现在请求与响应分字段入库，响应体超过 8KB 落盘到 `data/uploads/packets/`，**永不截断**。
`evidence` 保留，但只作为一句人读摘要，不再参与验证判定。

### POST /api/packets —— 提交一次实测

```json
{
  "project_id": 2,
  "linked_type": "interface",      // interface / bug / execution
  "linked_id": 137,
  "label": "带 tenant-id 正常查询",
  "request": {
    "method": "GET",
    "url": "https://test.example.com/admin-api/x/list?pageNo=1",
    "query": {"pageNo": 1},
    "headers": {"tenant-id": "163", "Authorization": "Bearer xxx"},
    "body": ""
  },
  "response": {
    "status": 200,
    "duration_ms": 210,
    "headers": {"Content-Type": "application/json"},
    "body": "{\"code\":0,\"data\":[]}"
  }
}
```

`headers` 三种写法都收：`{k:v}`、`[[k,v],...]`、`"Key: Value"` 多行文本。
`body` 传对象会自动转 JSON 字符串。`captured_at` 可省，默认入库时刻。

返回 201：

```json
{
  "id": 12, "completeness": "full", "missing": "",
  "stored": "file", "resp_body_file": "packets/ab12cd34ef567890-114471.txt",
  "resp_chars": 114471, "resp_bytes": 331902, "sha256": "…",
  "verify_status": "verified"
}
```

`completeness` 由服务端算，不接受自报：

| 级别 | 条件 |
|---|---|
| `full` | 请求方法 + 请求地址 + 响应状态码 + 响应体，四样齐（204/304/HEAD 允许无体） |
| `partial` | 缺任一项。返回里 `missing` 说明缺什么，`verify_status` 不会变成 verified |

只缺请求头/响应头仍算 `full`，但 `missing` 里会带上提示。

### verify_status 的新判定

| 操作 | 结果 |
|---|---|
| 提交 `completeness=full` 的数据包（挂 interface） | `verified`，刷新 `verified_at` |
| 提交 `partial` 的数据包 | 状态不变，回 `hint` |
| 只改 `evidence` 文本 | 状态**不变**（不升级、不降级，存量不受影响） |
| 改契约字段（module/name/method/path/host/req_*/resp_example/error_codes） | `changed` |
| 显式传 `verify_status` | 以调用方为准（仅用于从外部导入历史数据） |

`POST /api/interfaces` 和 `PUT /api/interfaces/<id>` 都支持内联 `packet` 字段，
省掉"先建接口再挂包"两次往返；服务端会覆盖 `project_id` / `linked_type` / `linked_id`。

### 读取

- `GET /api/packets?linked_type=interface&linked_id=137` —— 列表，不带报文正文
- `GET /api/packets/<id>` —— 默认给响应体**前 2000 字符**，并明确回
  `body_truncated_for_display: true`、`preview_chars`、`resp_chars_actual`（真实总长）
- `GET /api/packets/<id>?body=full` —— 全量原文（落盘的从文件读）
- `GET /api/packets/<id>?body=none` —— 只要元信息
- `GET /api/packets/<id>/raw` —— **原始报文**：请求行 + 全部请求头 + 请求体 + 状态行 +
  全部响应头 + 响应体，纯文本、**不裁头不截体**（大响应从落盘文件读全文）。
  头和体都是入库时抓到的原样，筛过/摘过的内容不在这里补
- `GET /api/packets/<id>/download` —— 下载响应体原文（只有响应，不含请求）
- `DELETE /api/packets/<id>` —— 删包，落盘文件一并清理

### 页面

接口详情页、Bug 详情页、用例的执行记录里都会渲染数据包：左边请求（方法/地址/头/体），
右边响应（状态/头/体）。响应体超过 20000 字符时页面只渲染前段，并**显式写明**
「预览只显示前 20000 字符，本条共 N 字符」+ 下载入口，同时标注存储未截断。

左右分栏是"对照着看"的视图，**证据本体是原始报文**：每个包底部有
「原始报文」（新窗口打开纯文本）、「复制原文」（整段进剪贴板）、「下载 .http」，
给的都是同一份未裁剪的请求段 + 响应段；「只下响应体」是旧能力，只发响应。

存量数据不受影响：2026-10-22 之前录的接口仍是原状态，但详情页会明确提示
「这条标着已验证，但库里没有原始报文，无法复核」。
