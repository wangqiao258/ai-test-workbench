# AI 使用手册 · 参考（接口字典 / 用例 / Bug / runs / 错误码）

> **开场不要读本文件。** 开场规则在 `docs/ai_guide.md`；这里只放"要用时来查"的细节。
> 平台入口：`GET /api/guide?part=reference`（带 `X-API-Token`）。按小节标题找，不要整篇塞进上下文。

## API 明细

所有请求：`Content-Type: application/json` + `X-API-Token` 头（上传例外，用 multipart）。

### 连通性

`GET /api/ping` → `{"ok": true, "actor": "...", "time": "..."}`

### 手册自身

`GET /api/guide` → `{"guide": "<本文件全文>", "path": "<实际读取的路径>", "chars": <字符数>}`
读不到返回 503。它是本地手册的兜底出口——本地读不到时才用它；两边字符数不一致以本地为准
（读取顺序见开头「两个出口」）。

### 项目（只读；项目由用户在网页创建）

- `GET /api/projects`
- `GET /api/projects/{id}/environments` → `[{id, name, base_url, notes}]`
- `GET /api/projects/{id}/accounts` → `[{id, env_id, label, username, password, role, notes}]`

### 文档（只写叙述性内容；接口一律走 /api/interfaces）

- 读：`GET /api/docs?project_id={id}`（可选 `&dtype=`；旧参数 `&status=` 已无意义，会被忽略）

- 写：`POST /api/docs`

  ```json
  {"project_id": 1, "dtype": "flow", "title": "登录鉴权机制",
   "content": "Markdown 正文...", "evidence": "请求/响应摘要"}
  ```

  `dtype` 取值（服务端强制校验）：`test_plan` / `test_scheme` / `test_report` / `page` / `flow` / `analysis` / `record` / `general`。**`interface` 已废弃**（接口文档 = 目录树/OpenAPI，由接口记录自动生成），提交会被 400 拒绝。
  返回 `{"id": N, "dtype": "flow"}` —— 提交即生效（文档免审）。**文档没有 PUT**，改内容只能重新 POST。

  **写入红线（违反会被 400 拒绝并记审计）：**

  1. Bug 的复现记录、撤回说明、复核结论、证据补充**不是文档**：写 `PUT /api/bugs/<id>` 的 `evidence_append`，或 `POST /api/upload`（`linked_type=bug`）。标题含"复现/撤回/复核结论/补充说明"会被直接拒绝。
  2. test_plan / test_scheme / test_report 正文不少于 200 字且含完整章节（背景/范围/用例/结论）。
  3. 拿不准归类的分析内容用 `analysis` 或 `record`，不要全塞 `general`。

### 接口（一接口一记录，结构化；提交即生效，免审）

- 读清单：`GET /api/interfaces?project_id={id}&fields=meta`，可选过滤 `&module=A&module=B`（重复键 = 多选）、`&path_prefix=/app-api/video`、`&method=GET`、`&limit=50&offset=0`（有 limit 时响应头 `X-Total-Count` 给总数；旧参数 `&status=` 已无意义）
- 读单个：`GET /api/interfaces/{id}`（默认 `contract` 档）
- 字段档位 `fields`：
  - `meta`：id / 模块 / 名称 / 方法 / 路径 / 验证状态
  - `contract`（默认）：id / project_id / 模块 / 名称 / 方法 / 路径 / host / **req_params** / resp_example / error_codes / notes / verify_status —— **不含 req_headers**，要请求头必须用 full
  - `full`：全部字段，含 evidence 与请求头
- 写：`POST /api/interfaces`

  ```json
  {"project_id": 1, "module": "登录", "name": "账号密码登录",
   "method": "POST", "path": "/admin-api/system/auth/login", "host": "",
   "req_headers": [{"name":"tenant-id","required":true,"desc":"租户ID","example":"163"}],
   "req_params": [{"name":"username","type":"string","required":true,"desc":"用户名","example":"zhangsan"},
                  {"name":"password","type":"string","required":true,"desc":"密码","example":"Test@123"}],
   "resp_example": "{\"code\":0,\"data\":{\"accessToken\":\"8c879d13d486...\"}}",
   "error_codes": [{"code":400,"desc":"验证码不能为空（未传clientType时）"}],
   "notes": "传 clientType=h5 跳过验证码",
   "evidence": "一句话摘要：错误密码返回 400",
   "packet": {"request": {"method": "POST", "url": "/admin-api/system/auth/login"},
              "response": {"status": 400, "body": "{\"code\":400,...}"}}}
  ```
  - `packet` 内联时不用写 `linked_type` / `linked_id` / `project_id`（服务端按新建的接口填）；建接口与存报文在同一个事务里，省一次往返。
  - **只带 `evidence` 不再置 verified**：返回 `verify_status=unverified` 并附 `evidence_note` 提示；不带证据同样为 `unverified`。要 verified 就交完整 packet。
  - 返回 `{"id": N, "verify_status": "..."}`，带 packet 时多一个 `packet` 字段（含 completeness）。
- **path 与 host 的规矩（服务端强制校验）**：
  - `path` 只写路径，如 `/admin-api/system/auth/login`。**写 `https://域名/...` 会被 400 拒绝**（域名塞进路径会让目录树无法按段分层）。
  - `host` 留空 = 与项目环境 base_url 同域名，这是绝大多数情况。
  - 只有"这条接口和项目里其他接口不同域名"时才填 `host`，格式 `https://api.example.com`（不带路径、不带结尾斜杠）。
  - 目录树按 path 分段，域名不进层级；项目出现第二个域名时，树才自动长出域名层。
- 改：`PUT /api/interfaces/{id}`
  - 本次带了**完整 packet** → `verified`，刷新 `verified_at`
  - 只改契约字段（module/name/method/path/host/req_*/resp_example/error_codes）且无 packet → `changed`
  - 只补 `notes`、只改 evidence 摘要 → 状态不动（也不会把 verified 降级）
  - 返回 `{"id": N, "verify_status": "...", "verified_at": "..."}`
  - **`changed` 的接口，在生成新用例或下结论前先复测**，别拿旧契约当事实。
- **`verified` 不可自封（曾出过"全量 verified、实际只有几条有报文"的事故）**：
  POST/PUT 显式传 `verify_status=verified` 一律 **400**，提示去交 packet。
  合法自选值只剩 `unverified` / `changed`。存量治理用 `scripts/backfill_verify_status.py`
  （预览默认，`--apply` 落库）。

### 数据包（证据的唯一载体）

`POST /api/packets`

```json
{"project_id": 1, "linked_type": "interface", "linked_id": 3, "label": "正确密码登录",
 "request": {"method": "POST", "url": "/admin-api/system/auth/login",
             "query": {}, "headers": {"tenant-id": "163", "Content-Type": "application/json"},
             "body": "{\"username\":\"13800000000\",\"password\":\"Test@123\"}"},
 "response": {"status": 200, "headers": {"content-type": "application/json"},
              "body": "{\"code\":0,\"data\":{\"accessToken\":\"...\"}}", "duration_ms": 123},
 "captured_at": "2026-10-23 10:00:00"}
```

- `linked_type` ∈ `interface` / `bug` / `execution`；`linked_id` 必须存在且属于 `project_id`（服务端会校验，不一致返回 400）。
- `request.method` 限 GET/POST/PUT/PATCH/DELETE/HEAD/OPTIONS；`request.url` 需 `http(s)://` 绝对地址或以 `/` 开头；`response.status` 为 100-599 的整数。
- **完整度由服务端算**（`completeness` + `missing`）：请求方法、请求地址、状态码、响应体四样齐 = `full`；HEAD 请求或 204/304 允许空响应体；缺请求头/响应头只记提示，不降级。
- 响应体超过 8192 字符自动落盘 `data/uploads/packets/`（内容寻址、**永不截断**），库里只存 `resp_body_file` 引用。
- 只有当 `linked_type=interface` 且 `completeness=full` 时才把接口置 `verified`；不完整包**不改动**接口状态，返回里的 `verify_status` 是回读的库值，不要按本次包推断。不完整时返回 `hint` 说明缺口。
- 读：`GET /api/packets?project_id=&linked_type=&linked_id=&completeness=`
- 读单条：`GET /api/packets/{id}?body=preview|full|none`（默认 preview，响应体只给前 2000 字符并标 `body_truncated_for_display`；`full` 给原文；`none` 只要元信息）。响应同时带 `resp_chars_actual` 与渲染好的 `text`。
- 下载原文：`GET /api/packets/{id}/download`（只有响应体）
- 原始报文：`GET /api/packets/{id}/raw` —— text/plain，请求行 + **全部**请求头 + 请求体 +
  状态行 + **全部**响应头 + 响应体，不筛头、不截体。要复核或要把报文贴给别人，用这一条。
- **网页上的呈现**：接口/Bug/用例/执行详情页直接把这段原生报文渲染在
  `<pre>` 里（与 `/raw` 同一份文本，头按入库顺序、body 不改一个字符），上面一行元信息
  （状态/字符数/耗时/抓包时间/抓包人/sha256/完整性），不再拆双栏、不表格化头字段。
  响应体超 20000 字符时页面只渲染前段并明示总长 + 给 .http 下载；存储永远全量。
- 删除误录：`DELETE /api/packets/{id}`（落盘文件一并清理）

### OpenAPI 活文档（自动生成，只读）

- 项目的 OpenAPI 文档由 interfaces 表自动生成，随接口记录实时更新，**不需要也不能手工维护**。
- 下载：`GET /api/projects/{id}/openapi.json`（全量导出；旧参数 `?status=approved` 已无意义）
- 网页只给下载入口（项目页「接口」tab 头部「导出：openapi.json」），不再内置 Swagger 页面：
  需要渲染就导入 Apifox / Postman / IDE。AI 自己别读全量文档，按模块取
  `/api/interfaces?module=...&fields=contract` 更省上下文。
- 每条 operation 的 `description` 首行就是可信度（「**可信度：已验证**（实测于 …）」），展开即见。
- 扩展字段：`x-interface-id`、`x-verify-status`、`x-verified-at`、`x-evidence`、`x-error-codes`。机器判断可信度看 `x-verify-status`。
- 域名处理：`paths` 里只有路径；环境 base_url 进 `servers`；某条接口填了 `host` 时，该 operation 带独立 `servers`，不会把域名拼进 path。

### 持续生成（测试目标池 + 反馈闭环）

**目标不是无限增加用例数，而是持续增加已验证的新风险。** `dims_missing` 只用于冷启动，
不能表达具体参数、角色、数据状态、流程转换和失败相邻场景。持续生成一律使用下面的目标闭环。

六种 `strategy`：

| 策略 | 什么时候用 | 目标示例 |
|---|---|---|
| `breadth` | 找尚未覆盖的接口、规则和模块 | 某接口没有任何异常场景 |
| `interface_depth` | 深挖单接口 | 某参数跨边界、错误码、鉴权、幂等 |
| `flow` | 多接口和状态转换 | 创建后重复提交、中途失败后恢复 |
| `data_state` | 数据前置状态 | 空、重复、过期、大数据量、他人数据 |
| `failure_driven` | 围绕失败做相邻探索 | 同输入换角色、重复、并发或相邻边界 |
| `change_driven` | 契约、文档、真实响应发生变化 | 新字段、新错误码、新流程分支 |

0. **没有目标时先按缺口派活**：`POST /api/test-targets/from-gaps`

   ```json
   {"project_id": 1, "limit": 10, "include": "both"}
   ```

   按覆盖缺口批量登记：零用例模块优先（P1），其次零 UI 用例模块（P1）。
   `include` 取 `api` / `ui` / `both`（默认 both），`limit` 默认 8、上限 20。
   同缺口已登记过就跳过，`skipped` 里带 `duplicate_of`——不要为凑数 `force`。
   返回的 `created` 直接走下面的 `next` 领取。

1. **登记目标**：`POST /api/test-targets`

   ```json
   {"project_id": 1, "interface_id": 3, "title": "密码超过上限",
    "intent": "验证密码长度超过契约上限时被拒绝且不创建会话",
    "strategy": "interface_depth", "priority": "P1",
    "source_ref": "req_params.password.maxLength"}
   ```

   `title + intent` 必填，`intent` 必须是一个具体风险，不能只写“补边界”。锚点用
   `interface_id / doc_id / parent_target_id / module` 至少一个；`source_ref` 指向参数、文档段落或历史证据。
   相同来源和意图返回 `409 + duplicate_of`。失败扩展传 `parent_target_id=失败目标id`，会继承其锚点。
   查询：`GET /api/test-targets?project_id=1&status=open&strategy=interface_depth`；详情含已生成用例。

2. **原子领取**：`POST /api/test-targets/next`

   ```json
   {"project_id": 1, "strategy": "interface_depth"}
   ```

   首次不用传批次，响应会返回 `generation_batch_id`；同一轮后续领取带上它。平台按
   `P0 → P3、尝试次数少者优先` 原子领取，两个 AI 会话不会拿到同一个 open 目标。
   返回的 `failure_hints` 是失败扩展线索，`blocked_targets` 是尚未覆盖的阻塞目标。
   没有可领取目标时返回 `target: null`，不要重复生成已有用例充数。

3. **生成真正的新用例**：`POST /api/cases` 在原有字段上增加：

   ```json
   {"target_id": 8, "generation_batch_id": 2,
    "novelty": "已有用例只测错误密码，本条新增长度上边界并验证不创建会话"}
   ```

   目标必须先由当前 API 身份通过该批次领取；`generation_strategy` 由目标带入。
   `novelty` 必填，写清新规则、新输入状态、新角色或新流程，不接受“标题不同”作为新意。
   新用例能交给 runner 的必须直接写 `steps_json.checks`，不要生成后再补。

4. **处理生成失败**：`POST /api/test-targets/{id}/feedback`

   - `{"outcome":"duplicate","note":"duplicate_of 及原因"}`：目标暂缓，不再反复领取；
   - `{"outcome":"invalid","note":"缺什么上下文"}`：重新放回 open，补齐资料后再试；
   - `{"outcome":"deferred","note":"为什么暂缓"}`：明确暂缓；
   - `{"outcome":"reopen"}`：重新打开 deferred / blocked 目标。

5. **执行反馈与下一轮**：回填 execution 后平台自动汇总目标下**每条用例的最近一次结果**：
   任一 fail → 目标仍为 generated；任一 blocked 且无 fail → blocked；全部 pass → covered；
   还有未执行用例时不能提前 covered。修改目标用例的步骤、前置条件、锚点或预期会重新要求验证。
   对 fail 目标登记 `failure_driven` 子目标，不要原样再生成；对 blocked 先补环境/数据或设计替代验证。

6. **结束生成批次**：`POST /api/generation-batches/{id}/finish`；`GET /api/generation-batches/{id}` 看统计。
   收尾会释放已领取但未生成用例的目标，避免会话中断后永久占用。目标没有审核流，用例仍然提交即生效。

### 广度补齐（把空白接口变成目标）

适用：项目刚接入、或某个模块长期没动过。**产出是测试目标，不是给每个接口写一条"正常流"。**
没有用例的接口不等于都值得测——按风险选点，别按条数铺。

1. **取空白（一次只处理一个模块，控制上下文）**：
   `GET /api/coverage?project_id={id}&module=<模块>`，看 `n_cases=0` 的接口及其 `verify_status`。
2. **选点顺序（与项目无关，按风险）**：
   - 有副作用的操作优先（写、删除、状态变更、登录/鉴权），纯查询靠后；
   - 被其他用例或流程依赖的接口优先（在既有 `steps` / `interface_ids` 里出现过）；
   - `verify_status=changed` 的空白接口最先测（契约变过，旧结论不可用）；
   - 同一模块的空白查询接口合并成一条用例（分页越界 + 越权 + 关键参数边界），
     用 `interface_ids` 挂全部关联接口，不要一个接口一条。
3. **目标写风险，不写"正常流"**：
   - 反例：「测试 `{模块}` 列表正常查询」——这不是风险，是烟测；
   - 正例：「非本机构管理员调用该列表不返回其他机构数据」（越权）；
   - 正例：「`pageSize` 超过契约上限时按上限截断而不是全量返回」（边界）。
4. **每轮 5~10 个目标**，走上面的目标闭环（登记 → 领取 → 生成 → 执行）。
   不要为了"把空白接口清零"而 `force` 重复用例；同一接口的多条断言合并进一条用例的 `checks`。

### 用例（锚点 + 覆盖维度 + 服务端查重）

- 读清单：`GET /api/cases?project_id={id}`，可选 `&module=A&module=B`（多选）、`&interface_id=N`（主锚点 + 关联表都匹配）、`&doc_id=`、`&target_id=`、`&generation_batch_id=`、`&unlinked=1`（只看没挂接口的）、`&with_links=1`（附带 interface_ids）、`&fields=summary`（id/模块/标题/预期/锚点/维度/生成目标，不含 steps）、`&priority=`、`&batch=`、`&limit=&offset=`。旧参数 `&status=` 会被忽略。
- 读单条（执行前拿 steps）：`GET /api/cases/{id}`
- 写：`POST /api/cases`

  ```json
  {"project_id": 1, "interface_id": 3, "title": "错误密码登录被拒绝",
   "preconditions": "账号已存在", "priority": "P1", "dims": ["异常"],
   "steps_json": {"kind": "api", "steps": [
     {"action": "用错误密码调登录接口",
      "request": {"method": "POST", "path": "/admin-api/system/auth/login",
                  "headers": {"tenant-id": "163"},
                  "body": {"username": "13800000000", "password": "wrong"}},
      "expect": "code != 0，不返回 accessToken"}]}}
  ```
  - 也可以用纯文本 `steps`（老写法仍支持）。**给了 `steps_json` 就不要再写 `steps`**：平台会自动渲染文本，只维护一份数据。
  - `steps_json` 规则（服务端校验，违反 400）：`kind ∈ api|ui|mixed`；每步 `action` 必填、`expect` 必填；`request.method` 限 GET/POST/PUT/DELETE/PATCH/HEAD/OPTIONS；`request.path` 只写路径；**`request` 与 `ui` 一步只能二选一**；`ui` 动作见下面「UI 用例（kind=ui）」；最多 50 步。
  - 接口类用例**强烈建议**写 `steps_json`，执行时照着发请求，不用从自然语言里猜参数。写 headers 前先 `GET /api/interfaces/{id}?fields=full`（contract 档不含请求头）。
  - **要交给 runner 自动跑，每步还必须给 `checks`**（机读断言）。没有 checks 的用例 runner 一律跳过，不拿 `expect` 猜。格式与运算符见下面「执行批次（runs）」。存量用例补 checks 用 `PUT /api/cases/{id}`。
- **锚点规则（服务端强制）**：`interface_id`（接口类）/ `doc_id`（页面、流程类，指向 docs 的 page/flow）/ `module`（跨切面、安全类），三者至少一个，否则 400。
- **一条用例可覆盖多个接口**：`interface_ids: [12, 13, 107]` 写全量关联，`interface_id` 只是主锚点（决定 module 归属）。覆盖矩阵会把这条用例在每个关联接口下都算一次。
- **module 由接口派生**：给了 `interface_id` 时 `module` 取该接口的模块，手填值会被忽略。
- **dims 覆盖维度**（数组，可多值，只能取这些值）：
  `正常` `边界` `异常` `鉴权` `越权` `幂等` `并发` `兼容` `性能` `安全`
- **查重**：先在整个项目比对测试行为指纹（锚点、前置条件、请求/UI、输入与断言），再比对标题（归一化后相似度 ≥0.85 或完全相同）。重复返回 `409 + duplicate_kind(intent/title) + duplicate_of + existing_title + existing_anchor + existing_dims`：
  - `existing_dims` 是那条已有用例覆盖的维度——**同一测试行为换个 dims 不算新覆盖**，别为此 force；
  - 换标题但行为相同也会被 `intent` 查重；不同业务输入、前置状态或断言会形成不同指纹；
  - 目标用例确认重复 → `POST /api/test-targets/{target_id}/feedback {"outcome":"duplicate"}`；
  - 只是给已有用例补维度 → `PUT /api/cases/{duplicate_of}` 改 `dims`；
  - 只有确认是不同风险才重发并带 `"force": true` + `"force_reason": "<为什么行为不同>"`。
    **force 是唯一能跳过查重的口子，服务端会把"放过了哪条 + 理由"写进操作日志**
    （`action=api_create_case_force`），用户能在网页「操作日志」里看到——不得用它绕过持续生成查重。
- 改：`PUT /api/cases/{id}`，可改 `title/preconditions/steps/steps_json/expected/priority/dims/doc_id/batch/interface_id/interface_ids`。只传 `steps_json` 时会自动重渲染 `steps`（同时传了 `steps` 则以你传的为准）；传 `interface_ids` 表示整体替换关联，只传 `interface_id` 表示换主锚点、其余关联保留。
- `priority`：P0/P1/P2/P3。用例没有审核状态，提交/修改即生效。

### 覆盖矩阵（冷启动参考，不代表完整覆盖）

`GET /api/coverage?project_id={id}`，三种取范围方式（互斥，先命中先用）：

- `?module=A&module=B` —— 指定模块（重复键 = 多选）
- `?group=侧边栏` —— 整块（等于 `侧边栏-*` 全部模块，比手拼 13 个模块名省事）
- 都不传 —— 全项目（只适合总览）

可加 `&only_missing=1` 只看还没用例的接口，`&ui=full` 展开页面级 UI 明细。

响应里另有三段缺口，冷启动先读它们再决定取哪个模块：

- `totals.interface_coverage`：有用例的接口 ÷ 总接口（0~1）；`totals.ui_cases` 是 UI 用例数；
- `gaps.modules_without_cases` / `gaps.modules_without_ui`：零用例模块、零 UI 用例模块（含接口数）；
- `ui.modules`：每个模块的 `ui_cases`、`page_docs`、`ui_dims_covered` / `ui_dims_missing`。

UI 用例的判定看 `steps_json` 里有没有 `ui` 步骤，**不看 dims**：给一个模块补多少维度都不会让它的 UI 覆盖变成 1。
`?module=` / `?group=` 会把这三段一起收窄，所以按模块取时也能看到该模块自己的缺口。

```json
{
  "project_id": 1, "modules": ["侧边栏-素材"], "group": null,
  "dim_vocabulary": ["正常", "边界", "异常", "鉴权", "越权", "幂等", "并发", "兼容", "性能", "安全"],
  "totals": {"interfaces": 14, "interfaces_with_cases": 5,
             "interfaces_without_cases": 9, "cases": 8},
  "interfaces": [
    {"id": 12, "module": "侧边栏-素材", "name": "素材分页(搜索)", "method": "GET",
     "path": "/admin-api/sidebar/wecom/material/page", "verify_status": "verified",
     "n_cases": 2, "dims_covered": ["正常", "边界"],
     "dims_missing": ["异常", "鉴权", "越权", "…"],
     "cases": [{"id": 11, "title": "素材按名称搜索可正确过滤", "expected": "…", "dims": ["正常","边界"]}]}
  ],
  "unlinked_cases": [{"id": 23, "module": "安全", "title": "CORS 不应反射任意来源", "dims": ["安全"]}]
}
```

用法：带 `module` 或 `group` 一次只取一片（单模块约 4 千字符）；`unlinked_cases` 是挂在 module 上的跨切面用例，写之前扫一眼避免重复。`dims` 是用例声明的粗粒度标签，一个维度有用例不代表该维度所有风险已验证；持续生成必须继续读取测试目标池。

### 模块词表

`GET /api/modules?project_id={id}` → `[{"name": "侧边栏-素材", "interfaces": 14, "cases": 8}]`
module 是项目级受控词表（唯一来源是 `interfaces.module`），提交接口时会自动登记。

### 执行结果（直接生效，不需审核）

`POST /api/cases/{case_id}/executions`

```json
{"result": "fail", "actual_result": "错误密码仍返回了 token",
 "step_results": [{"no": 1, "result": "pass", "actual": "返回 401，未发 token"},
                  {"no": 2, "result": "fail", "actual": "正确密码也返回 401"}],
 "evidence": "请求: ...\n响应: ..."}
```

`result`：`pass` / `fail` / `blocked`。

- 用例有 `steps_json` 时，**推荐按步回填 `step_results`**（`no` 必须是用例里存在的步骤号，否则 400）；
  只给 `step_results` 不给 `result`，平台会推导：任一 fail → fail，有 blocked 无 fail → blocked，否则 pass。
- 同时给 `result` 又与推导值矛盾 → 400，别硬凑结论。
- 用例关联 `target_id` 时，响应还带 `target {id,status,last_result}`；平台按该目标全部用例的最近结果自动更新覆盖状态。失败后到下一次 `test-targets/next` 的 `failure_hints` 继续扩展，不要重复提交同一行为。
  读历史：`GET /api/cases/{case_id}/executions`

### 执行批次（runs，P1）

平台自己不跑用例；执行由 runner 做（服务器 `docker compose --profile runner up -d runner`，
本地 `python -m runner`）。你负责**产出可执行的用例**、**发起一轮**、**读结果下结论**。

**checks（机读断言）**——`steps_json` 每步的 `checks` 数组：

- `src`：API 步骤用 `status` / `body` / `headers` / `duration_ms`；
  UI 步骤用 `url` / `title` / `text` / `element`（取页面快照，op 完全通用）
- **跨类型写错当场 400**：API 步骤写 `text`、UI 步骤写 `status` 都过不了校验
- `op`：`eq` `ne` `contains` `not_contains` `present` `absent` `gt` `lt` `regex` `in`
- `path`：简化 jsonpath，`$.data.list[0].id`；不写 path 时 `body` 按**原文**匹配
- 只有 `present` / `absent` 不需要 `value`
- **任何一步没有 checks，整条用例被跳过**（进 `summary.skipped`）——不要把它算成"跑过了"

```json
"checks": [{"src": "status", "op": "eq", "value": 200},
           {"src": "body", "path": "$.code", "op": "ne", "value": 0},
           {"src": "body", "path": "$.data.accessToken", "op": "absent"}]
```

**UI 用例（`kind: "ui"`）**——执行由 runner 里的 Playwright 完成。

**写之前先有页面事实，不要从字段名猜页面。** `ui.target` 的文本必须是人打开页面真能看到的字
（uni-app 编译后是 `<uni-view>`，role 常抓不到，先按文本定位）。没有页面文档就先补一篇：

```json
{"project_id": 1, "dtype": "page", "title": "侧边栏-学习 页面结构与交互",
 "content": "地址 /pages/study/index；关键元素：搜索框、课程列表、新建按钮；交互：进入→列表→点课程→详情"}
```

用例用 `doc_id` 锚到这篇文档（页面/流程类用例的锚点）。覆盖矩阵的 `ui.modules[].page_docs`
和 `ui_cases` 会跟着变，所以「先补文档再写用例」这件事是可以被检查出来的。

动作用 `ui` 字段，只有四个：

| `do` | 必填 | 说明 |
|---|---|---|
| `goto` | `url` | 只写路径（如 `/pages/index/index`），域名取 `vars.uiBaseUrl`，没配才退回 API 地址（见下） |
| `click` | `target` | 点元素 |
| `fill` | `target` + `value` | 填输入框，`value` 可用 `{{account.username}}` 模板 |
| `wait` | `target` 或 `ms` | 等元素出现 / 等固定毫秒 |

`target` 三选一（只能给一种）：

- `"登录"` 字符串等价于 `{"text": "登录"}` —— 按可见文本找，**默认用这个**
- `{"role": "button", "name": "登录"}`
- `{"css": ".login-btn"}`

被测前端是 uni-app 编译的 H5（`<uni-view>` / `<uni-button>` 这类自定义标签），
这些标签没有隐式 ARIA role，`role` 未必抓得到。**先试文本**，文本重名点错了才退到 css。

```json
{"kind": "ui", "steps": [
  {"no": 1, "action": "打开系统首页", "ui": {"do": "goto", "url": "/pages/index/index"},
   "expect": "进入待办列表",
   "checks": [{"src": "text", "op": "contains", "value": "待办"}]},
  {"no": 2, "action": "点登录", "ui": {"do": "click", "target": "登录"},
   "expect": "不再停在登录页",
   "checks": [{"src": "url", "op": "not_contains", "value": "/login"}]}
]}
```

`element` 的 `path` 写 target 的那个词（跟 `ui.target` 同一份字符串），
用来断言元素还在 / 不见了：`{"src": "element", "path": "登录", "op": "absent"}`。

三条 UI 专有口径：

- **不产生数据包**。packet 是 HTTP 报文，页面操作没有报文；硬塞会让 `/packets`
  里出现语义错误的状态码。页面证据进 `step_results[].evidence`。
- **失败截图**存 `data/uploads/ui/run<run>-case<case>-step<n>.png`，文件名写进 evidence。
- **元素没出现 = blocked，不是 fail**。这是"这条没验成"，不是"功能有问题"——
  记成 fail 就是假缺陷。页面真跳错、断言不过才是 fail。

执行前提三条：每步都有 `ui` 和 `checks`；runner 容器在跑且能从它访问到页面
（`deploy/Dockerfile.runner` 基于 playwright 官方镜像，浏览器已内置，不要另装；自建 runner 才需要自己装）；
UI 地址（`vars.uiBaseUrl`，缺省退回 API 地址）能打开页面。

**页面地址单独配：`vars.uiBaseUrl`，别假设环境 `base_url` 就是页面地址。**

- 实际生效顺序（`runner/__main__.py`）：API 用 `vars.baseUrl` → 环境 `base_url`；
  UI 用 `vars.uiBaseUrl` → 上面那个 API 地址。换地址不用改表。
- 前后端分开部署很常见（API 在 `:8000`、页面在 `:8002`，或 API 走 IP、页面走域名），
  只配一个地址必然有一半跑不了：
  `PUT /api/projects/<id>/settings/vars`
  `{"value": {"baseUrl": "http://<api-host>:8000", "uiBaseUrl": "http://<web-host>:8002"}}`
- 两种配法都踩过：环境 `base_url` 写内网 IP 想绕出网，裸 IP 打 HTTPS 会超时（`Page.goto` 15s）；
  域名则靠 runner 容器的 `extra_hosts` 指到内网 IP（见 `deploy/docker-compose.yml`），
  URL 仍是域名，证书 SNI / Cookie 域 / 静态资源相对路径才对。
- 只认一条：**配给浏览器的地址，必须是 runner 机器上真能打开页面的那个**。配错时在
  `goto` 阶段就 blocked，不会假 fail。

`goto` 一次是秒级（远端机器比本机慢），一条 UI 用例控制在 10 步内，别写大流程。

**步骤间取值**：request 的 `headers` / `query` / `body` 里可写
`{{steps.<步骤号>.<字段路径>}}`（取第 N 步响应 JSON 的字段，如
`{{steps.1.data.accessToken}}`）和 `{{account.username}}` / `{{account.password}}`。
整串就是一个占位符时保留原类型（数字仍是数字）。
"登录拿 token 再调业务接口"这类用例必须靠它，否则每步只能独立。

**发起一轮** `POST /api/runs`：

```json
{"project_id": 1, "name": "接口回归 第3轮", "reason": "发布前回归",
 "scope": {"batch": "接口回归-会员侧"}}
```

`scope` 四选一，不能组合：`{"case_ids":[1,2]}` / `{"batch":"..."}` /
`{"module":["a","b"]}` / `{"group":"侧边栏"}`。

**轮次类型 `kind`**（缺省 `regression`）：

- `regression` 回归——正经跑用例，结论要能当基线
- `selfcheck` 自检——只为验平台/管道（回填验证、脚本自检、部署后自检）
- `diagnostic` 诊断——排查网络/部署，可能一条都没跑到被测系统

**起名前先想清楚属于哪一种**：自检轮混进回归列表，会让"这周回归了几次、红了几条"变成假数。
`GET /api/runs?kind=selfcheck` 可单独筛；网页「运行」tab 有对应下拉。

**看板口径（只改网页，不改 API）**：

- 运行 tab **默认只显示 `regression`**（tab 链接带 `&kind=regression`），tab 上的数字是
  「回归轮数 / 全部轮数」；`&kind=all` 才看全部，词表外的值仍按默认回归处理。
- 自检/诊断轮在列表里灰显、详情页顶部有警示条；它们**不进**"回归了几轮、红了几条"的任何统计。
- **`GET /api/runs` 默认仍返回全部类型**（脚本与 runner 的行为不变）。所以读结果前先看 `kind`：
  诊断轮的红不能当缺陷（run 15 的 18 fail 全是 memberToken 过期，逐条 actual 都是 401），
  自检轮的绿也不能当质量结论（它只说明平台管道通）。
- `kind` 为空的历史数据一律按 `regression` 处理（网页与统计都用 `COALESCE(NULLIF(kind,''),'regression')`）。

**读结果**：`GET /api/runs?project_id={id}&status=` 看列表；
`GET /api/runs/{id}` 给 `summary {total,pass,fail,blocked,skipped}` 与每条 execution。
每步完整报文在 packets 里（`linked_type=execution`、`linked_id=该执行 id`）。

**看进度**：列表和详情都带两个派生字段，不要自己数 execution：

- `progress {total,done,pass,fail,blocked,left}`——**运行中按 executions 现算，终态读 summary**
- `stalled true/false`——`running` 且超过 180 秒没有心跳，说明 runner 已经死了

判读规矩：`summary` 只在 `finish`/`cancel` 时是终值，跑到一半它的 pass/fail 恒为 0；
**问"跑完了没、跑到哪"，看 `progress` 和 `stalled`，不要读 `summary`**。
`GET /api/runs?status=stalled` 直接筛"卡住的"。

**收尾僵尸轮**：runner 关窗口/被 Ctrl+C 后 run 会永远停在 `running`，平台**不会自动收**。
确认不再需要就 `POST /api/runs/{id}/cancel`，body `{"note":"runner 已退出"}`（note 必填）——
状态变 `failed`，summary 按已回填的执行现算，原因进 `cancel_note`。
收尾后不能再回填、不能再心跳。

**状态机**：`queued → running → done/failed`，`queued`/`running` 可直接 `failed`（取消）。
非 `running` 的 run 不接受回填（400），别在收尾后补写。

**runner 侧**：认领时上报 `runner_id`（`hostname:pid`，可用 env `RUNNER_ID` 覆盖），
每步打一次 `POST /api/runs/{id}/heartbeat`，回填 execution 时也会顺带刷新心跳。
答"这轮在哪台机器跑"看 `runner_id`。

网页端：项目页「运行」tab 是只读列表（状态/进度/执行者/僵死标记），点进去是 run 详情。
给用户报进度时用同一套口径，别只说"已运行"。

**基准轮对比 `baseline_run_id`**：`POST /api/runs` 可带
`{"baseline_run_id": 12}`（必须是同一项目已存在的 run）。详情接口会返回：

- `baseline`：基准轮基本信息
- `diff`：`{new_fail, still_fail, fixed, new_pass, not_rerun}` 五档 case id
  ——比上轮新红了哪些、一直红着哪些、修好了哪些、新过了哪些、该复跑却没跑的哪些
- `diff_cases`：这些 id 对应的标题

回答"这轮比上轮如何"时直接引 `diff`，不要自己 diff 两轮 summary。

**运行通知（webhook）**：`PUT /api/projects/{id}/settings/notify`

```json
{"value": {"webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx",
           "on": ["failed"], "format": "wecom"}}
```

- `format`：`wecom`（企业微信机器人 msgtype/text）或 `generic`（通用 JSON）
- `on`：`done` / `failed` 子集，缺省两者都发（cancel 落的是 failed）
- 只在**终态**发：finish(done/failed) 与 cancel。**stalled 不自动报警**——
  僵死轮靠列表的 `stalled` 标记人工发现（决策 #6：不做调度器）
- 发送失败只记日志，不影响收尾本身；网页设置页可"发送测试"验证连通性

**鉴权**：项目没配 auth 时 runner 只能跑免鉴权接口。
`PUT /api/projects/{id}/settings/auth` 两种形态——
`{"type":"login","method":"POST","path":"/admin-api/system/auth/login",
"headers":{"tenant-id":"163"},"body":{"username":"{{username}}","password":"{{password}}"},
"token_path":"$.data.accessToken"}`，
或 `{"type":"static","static_headers":{"Authorization":"Bearer xxx"}}`。

手工执行仍走上一节的 `POST /api/cases/{id}/executions`（不传 `run_id` 就不算进任何一轮）。

### Bug（进待审核）

`POST /api/bugs`

```json
{"project_id": 1, "case_id": 3, "interface_id": 3, "title": "错误密码可登录",
 "module": "登录", "severity": "critical",
 "steps": "1. ...", "evidence": "请求: ...\n响应: ...\n截图: /files/xxx.png"}
```

`severity`：`critical` / `major` / `normal` / `minor`。`case_id`、`interface_id` 可省略，建议关联（服务端会校验存在性）。

**提交前查重**：标题与项目里已有 Bug 归一化相似度 ≥0.85 时返回
**409 + `duplicate_of`**。确实是另一件事才带 `force=true` 重提交。
线上长期"投得多、过得少"——驳回的大头是重复与描述不清，提交前先查重、把材料写全，
是把通过率提上去的唯一办法（当前通过率看首页数据质量徽标）。

**提交时建议带两个自检字段**（都可省略，省略不影响提交）：

- `repro_rate`：`always` / `often` / `sometimes` / `once`（必现还是偶现）
- `impact`：一句话说清影响范围（≤200 字符，如"所有用户可越权查看他人订单"）

这两个字段会展示给审核的人，也是驳回时分类的依据。

数据包挂到 Bug：先 `POST /api/bugs` 拿到 id，再 `POST /api/packets`（`linked_type=bug`、`linked_id=该 id`）；一个 Bug 可挂多条包（复现前后各一次）。

**没有 status 字段**：平台不追踪"开发修没修"（开发在公司在线表格跟进）。一条 Bug 只有两条信息：

- `review_status`：`pending` 待审核 / `approved` 通过 / `rejected` 驳回
- `reported_at`：是否已抄进公司在线表格，**由用户点网页按钮写入，AI 不要写（API 也不接受）**

四态由两者组合：

| 状态   | 判定                            | 在默认视图 |
| ------ | ------------------------------- | ---------- |
| 待审核 | pending（reported_at 通常为空） | 是         |
| 待上报 | approved + reported_at 空       | 是         |
| 已上报 | approved + reported_at 有值     | 否         |
| 已驳回 | rejected                        | 否         |

默认视图 = 未结案 = 待审核 + 待上报。注意一个边界：已上报的 Bug 被 PUT 后会变成 `pending` + `reported_at` 有值，按上表第一行仍算待审核，再次通过就回到"已上报"。读：`GET /api/bugs?project_id={id}`，可按 `&review_status=pending`、`&severity=critical`、`&module=`、`&interface_id=` 筛。

改：`PUT /api/bugs/{id}`——补材料用 `evidence_append`（追加到现有 evidence 末尾，保留历史）；也可改 title/module/severity/steps/evidence。**更新后 `review_status` 一律回到 `pending`，但 `reported_at` 不清空**：一条已上报的 Bug 补证据后会重新进审核队列，再次通过后仍是"已上报"，不需要重抄表格。若该 Bug 已在表格里，汇报时提醒用户这一条会重回待审核。

**驳回分类（用户网页操作）**：驳回时选一个原因——
`repeat`（重复）/ `unrepro`（复现不了）/ `lowharm`（危害小不影响使用）/
`misuse`（使用方式不对）/ `noevidence`（没证据）/ `other`。AI 读 Bug 时看
`reject_category` 字段，按类别改进下一轮提交，别在同一个坑里摔两次。

### 数据质量与存量治理

首页 dashboard 每个项目卡片有一行**数据质量徽标**，低于健康线变红（只提示、不拦截）：

| 徽标 | 口径 | 健康线 |
|---|---|---|
| 真实验证 | 有 `completeness=full` 数据包的接口 ÷ 总接口 | 30% |
| 可执行用例 | 带 `checks` 的用例 ÷ 总用例 | 50% |
| Bug 通过率 | approved ÷（approved + rejected） | 50% |
| 孤儿执行 | `run_id` 为空的 executions 条数 | 0 |

读这四个数用 `core/lists.py:quality_stats`（网页与看板同一口径）；
回答"项目健康吗"先看这行，别只看总量——总量飘绿掩盖不了发动机空。

**孤儿执行治理**：`python scripts/backfill_run_scope.py`（预览）/ `--apply`（落库）。
归属规则：run 的 scope 覆盖该 case、且 `started_at ≤ 执行时刻 ≤ finished_at`
（queued 没有 started_at，不算候选；多轮命中取最晚启动的）。
**归不了的保持 `run_id` 为空**，在看板继续计数、报告里逐条列出——
宁可答"不知道"，不编轮次。

### 上传证据文件（截图、har 包、日志等）

`POST /api/upload`，multipart 表单，字段名 `file`。

- 扩展名白名单：`png / jpg / jpeg / gif / webp / har / txt / json / log / pdf / mp4`，其他一律 400（可执行文件与脚本拒收）。
- 单文件上限 50MB（env `APP_MAX_UPLOAD_MB` 可调），超限返回 413 JSON。
- 带上 `linked_type`（bug/execution/doc）和 `linked_id`（对应记录 id），网页才能在该记录下直接显示。
- 返回 `{"id": N, "stored_name": "...", "url": "/files/xxx"}`，把 url 写进对应记录的 evidence。

### 文档内容排版

`content` 用 Markdown，平台会渲染。文档是给下一次会话读的交接材料，推荐结构：

```
## 结论
（先给结论，一句话能看懂；多条就分条）

## 依据
| 验证项 | 方法 | 结果 |
|---|---|---|
| 未授权访问 | 去掉 token 重放 | 401，未泄漏数据 |

## 待办 / 风险
- …
```

接口契约不要写进文档（`dtype=interface` 会被拒），一律走 `/api/interfaces`。

## 错误码

- 400：参数缺失/格式错误（path 带域名、dtype 非法、steps_json 不合法、packet 缺 method/url/status、用例没锚点）→ 按返回的 error 修正
- 401：Token 缺失/错误/被吊销 → 找用户
- 404：对象不存在
- 409：用例标题与已有用例高度相似 → 看 `duplicate_of` 与 `existing_dims`；补维度用 PUT，确实另一件事再带 `force=true` + `force_reason`（会进操作日志）。**Bug 同样查重**（相似度 ≥0.85，409 + `duplicate_of`）
- 413：上传文件超过大小上限
- 410：数据包响应体文件缺失（下载时）
- 503：`/api/guide` 找不到手册文件 → 检查镜像里是否有 `docs/ai_guide.md` / `docs/ai_guide_reference.md`
