# AI 使用手册：AI 协同测试工作台

> 这份文档是给 AI 看的操作手册。平台部署在内网服务器：用户管项目、审 Bug。
> **执行归属**：测试由 `runner` 执行（发请求、跑断言、回填），你只做分析与判定。
> P1 已上线；能自动执行的是"每一步都带 `checks`"的用例，条数以 `GET /api/coverage`
> 和首页数据质量徽标为准（不要记死数字）。runner 跑在本机还是服务器，取决于谁能访问被测系统。
> 详见下方「角色与执行边界」。
>
> **规则只写在两份文件里，别处不抄。** 本文件是开场必读（约 5k 字符）；接口字典、用例、Bug、
> runs、错误码等细节在 `docs/ai_guide_reference.md`（约 24k 字符），**按需取，不要整篇啃**。
> 两个出口内容相同：
> - 平台接口：`GET /api/guide`（本文件）、`GET /api/guide?part=reference`（参考手册）
> - 代码仓库：`docs/ai_guide.md`、`docs/ai_guide_reference.md`
>
> Skill `ai-test-platform` 只做入口路由（地址、Token、开场动作），不复述任何规则。
> 改规则只能改这两份文件——不要在各处抄一份，那会让规则慢慢漂移。读取顺序：**本地优先**
> （开发机上永远最新），本地不存在时才走接口；两边 `chars` 不一致以本地为准。
>
> **怎么读**：开场只读本文件（「基本信息」「角色与执行边界」「铁律」「标准工作流程」四节）。
> 需要接口字段、用例写法、Bug 规则、错误码时，再去参考手册里找对应小节——它是查的，不是读的。
>
> **本手册是平台级通用手册，不绑定某个项目**：文中的接口路径、模块名、条数、字符数
> 都是示例或量级，换项目按实际替换；规则（选点顺序、准入、查重、证据）与项目无关。
> 项目特有的模块名、空接口分布、账号，一律现场用 `/api/*` 查，不要抄示例。

## 基本信息

- 平台地址：由 skill `ai-test-platform` 或 `PLATFORM_URL` 环境变量给出；本地默认 `http://127.0.0.1:8501`，不要猜
- 认证方式：所有 API 请求带请求头 `X-API-Token: <Token>`
- Token 来源：先读项目目录 `ai-test-platform/data/api-token.txt`（服务器上是容器内 `/app/data/api-token.txt`）；没有或 401 就向用户要，不要猜
- 连接失败：报给用户

## 角色与执行边界

| 角色 | 职责 | 边界 |
|---|---|---|
| **你（AI）** | 分析师：出方案（用例 / 断言 / 掩码，全是数据）、发起任务、读结果下结论、提 Bug | P1 起不亲手执行、不写执行代码 |
| **平台** | 账本（接口 / 用例 / 执行 / Bug / 证据）+ 手脚（P1 的 runner） | 不做测试决策 |
| **用户** | 唯一质量门：审 Bug、拍板方向、给授权与凭据 | 不做执行、不逐条审用例 |

**当前实现状态 = P1 已上线。** 执行由 `runner` 完成，
不是你自己一个个发 HTTP。runner 可以在本机跑（`python -m runner`），也可以在服务器容器里跑
（`docker compose --profile runner up -d runner`）——**跑在哪由"谁能访问被测系统"决定**：
本项目服务器出公网受限，连不上被测系统的 443，所以当前在本机执行。

回答"能不能跑 / 在不在跑 / 跑到哪了"这类问题，必须守住三条：

1. **不说"平台是记录库"**。它是账本 + 质量门：packet 完整性判定（`completeness=full` 才 verified）、覆盖矩阵、审核流、OpenAPI 活文档。说成"记录库"，后续行为会退化成"跑完一次性灌结果"，证据质量直接掉档。
2. **说清是谁在跑**。执行 = runner（发请求、跑断言、回填），你负责建 run 与判读结果。runner 默认不常驻，别笼统说"服务器在后台跑"；要说"runner 在本机/服务器执行，我是发起方"。
3. **必须交代位置与前提**。跑不了的常见原因有两个：用例缺 `checks`（进 skipped）、凭证过期（`vars.memberToken` / `vars.staffToken` 失效会整批变红）。先查这两项，再下结论。

## 铁律（违反等于工作作废）

1. **证据 = 完整数据包**：不得根据代码注释、字段名猜测接口行为。每条接口结论必须来自真实报文，写入 `POST /api/packets`（或在 `POST /api/interfaces` 内联 `packet`）。只有 `completeness=full` 的数据包才把接口置为 `verified`；`evidence` 只是一句人读摘要，不参与验证判定。
2. **审核流**：**只有 Bug 进待审核**（误报成本是开发白干）。**文档、接口、用例全部免审**，POST/PUT 即刻生效，不要等"审核通过"。接口可信度只看 `verify_status`：完整数据包 → `verified`；只改契约字段 → `changed`（下次生成用例前应复测）；只补 notes → 状态不动。**不要自己传 `verify_status`**（仅用户明确要求补录历史数据时例外）。
3. **一接口一记录**：接口信息必须写 `POST /api/interfaces`（结构化字段），禁止把多个接口堆进一篇文档。文档（/api/docs）只放机制说明、业务流程等叙述性内容。
4. **证据保留原文（不脱敏）**：用户明确要求 Token、password 等敏感值在 evidence/文档中保留原文，保证可复现。代价是这些明文会存在平台库里——因此**只能留在本平台内**，不得转发到邮件、外部文档或任何第三方系统。
5. **账号获取**：执行测试需要地址、账号、密码时，先读项目的环境和账号（见下），**不要问用户**；读不到才问。
6. **Bug 必须带证据**：完整请求/响应作为数据包挂在 Bug 上（`linked_type=bug`）；UI 问题先 `POST /api/upload` 传截图，把返回 url 写进 evidence。
7. **只检测不破坏**：安全类验证仅限授权范围内的检测，不做漏洞利用、不提取真实数据。

## 标准工作流程

```
1. GET  /api/projects                     → 找到目标项目 id（找不到就问用户）
2. GET  /api/projects/{id}/environments   → 拿 base_url（选用户指定的环境）
3. GET  /api/projects/{id}/accounts       → 拿账号密码（明文，勿外发）
4. GET  /api/docs?project_id={id}                     → 读背景/流程/历史结论
   GET  /api/interfaces?project_id={id}&fields=meta   → 接口清单（轻，按需读单个契约）
5. 冷启动先看覆盖矩阵和已有目标；持续生成必须走测试目标闭环：
   GET  /api/coverage?project_id={id}&module={模块} → 找初始空白，不把 dims 当作全部覆盖
   GET  /api/coverage?project_id={id} → 看 gaps（零用例模块）与 ui（零 UI 用例模块），这是两份独立缺口
   GET  /api/test-targets?project_id={id}&status=open → 看已经登记、还没生成的风险
   没有 open 目标时用 POST /api/test-targets/from-gaps 按缺口派生目标，不要自己拍脑袋选题
6. 按固定顺序取活，不允许只挑接口写：
   ① 零用例模块 → ② 零 UI 用例模块的页面链路 → ③ 已有模块的缺失维度
   本轮 5~10 个目标里至少 2 个要落在 UI 或零覆盖模块；只给已有模块补 dims 不算新一轮覆盖。
   UI 用例需要页面事实（地址、关键元素文本、交互），没有就先补一篇 page 文档再写用例，
   不要凭字段名猜页面长什么样。
   把文档规则、参数约束、流程转换、数据状态、历史失败转成具体测试目标：
   POST /api/test-targets → 登记一个明确的新风险；相同意图会返回 duplicate_of
7. 每轮 5~10 个目标为上限，逐个领取并生成：
   POST /api/test-targets/next → 原子领取目标，保存返回的 generation_batch_id
   POST /api/cases → 带 target_id + generation_batch_id + novelty + 锚点 + steps_json.checks
   → 换标题但测试行为相同也会被查重；不要为凑数量使用 force
     （真要用必须带 force_reason，服务端会把"放过了哪条 + 理由"记进操作日志）
8. 执行本轮新用例并读反馈：
   建 run 由 runner 执行，或不能自动执行时按现有规则手工实测并回填
   → pass/fail/blocked 自动回写目标；全部关联用例通过才是 covered
   → 下一次 next 返回 failure_hints / blocked_targets，据此登记新的 failure_driven 子目标
9. 本轮结束：POST /api/generation-batches/{id}/finish → 看新增用例与执行统计
   - 没有 open 目标时，从变更接口/文档、真实响应和有效 Bug 登记新目标；没有新风险就停止本轮，禁止换说法凑数
   - 梳理接口 → POST /api/interfaces（带 packet）；发现问题 → POST /api/bugs（挂证据）
10. 工作汇报：本轮新增覆盖目标、有效新用例、重复/阻塞数、失败派生目标、待审核 Bug
```

### 读数据的分片纪律（上下文预算）

接口表带报文的全量体积随条数线性涨，是最容易把上下文撑爆的地方。**不要记死数字**：
体积只跟"你项目里有多少条"有关，用下面的单条成本乘一下就有数了，动手前也可以直接调一次
`fields=meta` 看返回字符数。

| 目的                             | 怎么读                                                              | 单条成本（估算）            |
| -------------------------------- | ------------------------------------------------------------------- | --------------------------- |
| 看有哪些接口                     | `GET /api/interfaces?project_id={id}&fields=meta`（可加 `&module=`） | 约 200 B/条                 |
| 拿某个接口的契约                 | `GET /api/interfaces/{id}`（默认 contract 档）                      | 中位约 0.5 KB/条            |
| **要请求头**（写 steps_json 用） | `GET /api/interfaces/{id}?fields=full`                              | 单条 1 ~ 7 KB               |
| 复核历史数据包                   | `GET /api/packets?linked_type=interface&linked_id=N` 再按 id 读单条 | 单条元信息很小              |
| 判断"这条用例写过没有"           | `GET /api/coverage?...` 或 `GET /api/cases?...&fields=summary`      | 约 0.5 KB/条                |
| 执行前拿步骤                     | `GET /api/cases/{id}`                                               | 单条                        |
| 全部用例正文                     | 不建议；只有整体盘点才 `fields=full`                                | 约 4 KB/条                  |

## 参考手册（按需取，开场不要读）

接口字典、数据包、OpenAPI、持续生成、广度补齐、用例、覆盖矩阵、模块词表、执行结果、runs、
Bug、数据质量、上传、排版、错误码都在另一份文件里：

- 仓库：`docs/ai_guide_reference.md`
- 平台：`GET /api/guide?part=reference`（带 `X-API-Token`）

读哪节看任务：写/改用例或查接口字段 → 接口字典；提 Bug → Bug；起 runner → 执行批次；
写 UI 用例（goto/click/fill/wait、uiBaseUrl、失败截图与 blocked 语义）→「UI 用例」；
收到 4xx/409 → 错误码；找下一个测试目标 → 持续生成 + 广度补齐 + 覆盖矩阵（gaps/ui）。

