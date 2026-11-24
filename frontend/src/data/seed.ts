import type {
  AiSummary,
  Defect,
  Exchange,
  Finding,
  HttpMethod,
  OpenApiDoc,
  Project,
  Requirement,
  Run,
  RunCase,
  RunStatus,
  RunStats,
  TestCase,
} from '../types'

const json = (value: unknown) => JSON.stringify(value, null, 2)

export const PROJECTS: Project[] = [
  {
    id: 'shop-api',
    name: '交易服务',
    key: 'SHOP-API',
    repo: 'shop/shop-api',
    environment: 'staging-cn-east',
    owner: '交易产品组',
    updatedAt: '2026-11-24T09:13:00+08:00',
  },
  {
    id: 'member-api',
    name: '会员中心',
    key: 'MEMBER-API',
    repo: 'shop/member-api',
    environment: 'staging-cn-east',
    owner: '会员产品组',
    updatedAt: '2026-11-23T10:30:00+08:00',
  },
]

/** 给种子数据补上项目归属，避免在每条记录里重复书写 */
function withProject<T>(
  projectId: string,
  items: T[],
): Array<T & { projectId: string }> {
  return items.map((item) => ({ ...item, projectId }))
}

interface ExchangeExtra {
  reqHeaders?: Record<string, string>
  respHeaders?: Record<string, string>
  error?: string
}

function ex(
  index: number,
  method: HttpMethod,
  path: string,
  status: number,
  elapsedMs: number,
  reqBody: unknown,
  respBody: unknown,
  extra: ExchangeExtra = {},
): Exchange {
  const requestId = `req-${String(index + 1).padStart(2, '0')}-${path
    .split('/')
    .filter(Boolean)
    .pop() ?? 'call'}`
  return {
    index,
    method,
    url: `https://api.staging.shop.dev${path}`,
    status,
    elapsedMs,
    request: {
      headers: [
        { name: 'accept', value: 'application/json' },
        { name: 'content-type', value: 'application/json' },
        { name: 'x-request-id', value: requestId },
        ...Object.entries(extra.reqHeaders ?? {}).map(([name, value]) => ({
          name,
          value,
        })),
      ],
      body: json(reqBody),
    },
    response: {
      status,
      headers: [
        { name: 'content-type', value: 'application/json' },
        { name: 'x-request-id', value: requestId },
        ...Object.entries(extra.respHeaders ?? {}).map(([name, value]) => ({
          name,
          value,
        })),
      ],
      body: json(respBody),
    },
    error: extra.error,
  }
}

const SHOP_REQUIREMENTS: Array<Omit<Requirement, 'projectId'>> = [
  {
    id: 'REQ-ORDER-01',
    title: '订单提交与库存锁定',
    version: 'v2.3',
    tags: ['订单中心', '库存', 'P0'],
    owner: '交易产品组',
    updatedAt: '2026-11-21T17:40:00+08:00',
    operationIds: [
      'op-create-order',
      'op-get-order',
      'op-lock-inventory',
      'op-cancel-order',
    ],
    caseNodeids: [
      'tests/test_order.py::test_create_order_success',
      'tests/test_order.py::test_create_order_out_of_stock',
      'tests/test_order.py::test_order_idempotent_retry',
      'tests/test_inventory.py::test_lock_inventory_concurrent',
    ],
    contentMd: `# 订单提交与库存锁定

> 版本 **v2.3** · 归属：订单中台 · 更新：2026-11-21

## 1. 背景

大促期间下单峰值达到日常的 12 倍。现有链路在库存不足时仍会生成订单，导致负库存和人工补偿。本期对提交订单与库存锁定做契约化改造。

## 2. 目标

- 库存不足时快速失败，不产生订单
- 同一 SKU 的并发锁定不突破可用库存
- 同一订单重复提交保持幂等

## 3. 功能需求

### FR-1 创建订单

- 入参：SKU、数量、用户 ID
- 库存充足时返回 **201** 与 order_id
- 订单金额由服务端按当前价格计算，不接受客户端传入

### FR-2 库存锁定

- 锁定请求必须携带 order_id，便于回滚与对账
- 同一订单重复提交必须幂等，不得重复扣减
- 并发锁定同一 SKU 时，必须基于当前可用库存做原子校验

### FR-3 缺货处理

- 可用库存不足时返回 **HTTP 409**，错误码 **OUT_OF_STOCK**
- 不得创建订单，不得写入锁定记录

### FR-4 取消与回滚

- 取消订单时释放已锁定库存
- 回滚操作必须按 order_id 幂等

## 4. 验收标准

| 编号 | 场景 | 期望结果 |
| --- | --- | --- |
| AC-01 | 库存充足，提交订单 | 201，库存扣减正确 |
| AC-02 | 两个请求并发锁定同一 SKU | 仅一个成功，另一个 409 |
| AC-03 | 库存为 0，提交订单 | 409 OUT_OF_STOCK，无订单产生 |
| AC-04 | 相同幂等键重复提交 | 返回同一个 order_id |

## 5. 关联接口

- **POST /v1/orders**：创建订单
- **POST /v1/inventory/lock**：锁定库存
- **DELETE /v1/orders/{orderId}**：取消订单并回滚库存

## 6. 风险与依赖

- 依赖库存服务提供行级锁或乐观锁支持
- 取消订单的回滚需要与库存服务保持同一事务边界
- 大促期间需要额外压测并发锁定场景

## 7. 变更记录

| 版本 | 日期 | 变更 |
| --- | --- | --- |
| v2.3 | 2026-11-21 | 补充 AC-02 并发验收标准 |
| v2.2 | 2026-11-08 | 增加 order_id 必填约束 |
`,
  },
  {
    id: 'REQ-PAY-02',
    title: '支付回调与幂等',
    version: 'v1.8',
    tags: ['支付网关', '幂等', 'P0'],
    owner: '支付平台组',
    updatedAt: '2026-11-19T11:20:00+08:00',
    operationIds: [
      'op-create-payment',
      'op-payment-callback',
      'op-get-payment',
      'op-create-refund',
    ],
    caseNodeids: [
      'tests/test_payment.py::test_payment_callback_idempotent',
      'tests/test_payment.py::test_payment_amount_mismatch',
      'tests/test_payment.py::test_refund_full',
    ],
    contentMd: `# 支付回调与幂等

> 版本 **v1.8** · 归属：支付平台组 · 更新：2026-11-19

## 1. 背景

支付渠道回调存在重复投递，历史上出现过重复入账。网关重试窗口为 24 小时，服务端必须自行保证幂等。

## 2. 功能需求

### FR-1 回调验签与幂等

- 回调必须携带 **X-Idempotency-Key**
- 服务端按幂等键去重，重复回调返回 200 且不重复入账
- 响应必须回显 **X-Idempotency-Key**，供网关对账

### FR-2 金额校验

- 回调金额必须与订单应付金额一致
- 不一致返回 **400**，错误码 **AMOUNT_MISMATCH**

### FR-3 退款

- 支持全额退款，退款单必须关联原支付单
- 重复退款请求按幂等键去重

## 3. 验收标准

| 编号 | 场景 | 期望 |
| --- | --- | --- |
| AC-01 | 重复回调同一幂等键 | 仅入账一次，响应回显幂等键 |
| AC-02 | 回调金额不一致 | 400 AMOUNT_MISMATCH |
| AC-03 | 全额退款后再次发起 | 返回原退款单，不重复退款 |

## 4. 关联接口

- **POST /v1/payments/callback**
- **POST /v1/payments**
- **POST /v1/refunds**

## 5. 风险

- 幂等记录至少保留 7 天，覆盖网关 24 小时重试窗口
- 预发环境缺少网关重试模拟，需要额外构造重复回调
`,
  },
  {
    id: 'REQ-USER-03',
    title: '登录风控与会话',
    version: 'v3.1',
    tags: ['用户中心', '风控'],
    owner: '用户平台组',
    updatedAt: '2026-11-16T09:35:00+08:00',
    operationIds: [],
    caseNodeids: [
      'tests/test_user.py::test_login_risk_control',
      'tests/test_user.py::test_session_expired',
    ],
    contentMd: `# 登录风控与会话

> 版本 **v3.1** · 归属：用户平台组 · 更新：2026-11-16

## 1. 背景

预发与生产共用风控策略，登录接口在并发场景下会触发限流。客户端缺少退避重试，导致流水线偶发失败。

## 2. 功能需求

### FR-1 登录风控

- 单设备 1 分钟内最多 20 次登录尝试
- 超限返回 **429**，并在响应头携带 **retry-after**
- 客户端应做指数退避重试

### FR-2 会话有效期

- 会话 2 小时无操作自动过期
- 过期后访问受保护接口返回 **401 SESSION_EXPIRED**

## 3. 验收标准

| 编号 | 场景 | 期望 |
| --- | --- | --- |
| AC-01 | 正常登录 | 200，返回 session_id 与 risk_level |
| AC-02 | 超过频率阈值 | 429 RATE_LIMITED |
| AC-03 | 会话过期后访问 | 401 SESSION_EXPIRED |

## 4. 说明

登录接口暂未纳入 OpenAPI 契约，关联用例的 operation 字段为空，需要在接口文档补齐后建立关联。
`,
  },
]

const MEMBER_REQUIREMENTS: Array<Omit<Requirement, 'projectId'>> = [
  {
    id: 'REQ-MEMBER-01',
    title: '会员等级与权益查询',
    version: 'v1.4',
    tags: ['会员', '权益', 'P1'],
    owner: '会员产品组',
    updatedAt: '2026-11-20T15:10:00+08:00',
    operationIds: [
      'op-member-profile',
      'op-member-benefits',
      'op-member-level',
    ],
    caseNodeids: [
      'tests/test_member.py::test_profile_detail',
      'tests/test_member.py::test_benefits_consistency',
      'tests/test_member.py::test_level_upgrade_idempotent',
    ],
    contentMd: `# 会员等级与权益查询

> 版本 **v1.4** · 归属：会员产品组 · 更新：2026-11-20

## 1. 背景

会员中心需要为 App、小程序与客服后台提供统一的等级、积分与权益数据。本期补齐查询接口与等级变更的幂等约束。

## 2. 功能需求

### FR-1 会员详情

- 按 member_id 返回等级、积分与状态
- 会员不存在或已注销返回 **404 MEMBER_NOT_FOUND**

### FR-2 权益列表

- 权益按等级返回，顺序保持稳定
- 同一权益不得重复下发

### FR-3 等级变更

- 等级变更必须携带幂等键
- 相同幂等键重复提交返回同一结果，不重复发放升级礼包

## 3. 验收标准

| 编号 | 场景 | 期望 |
| --- | --- | --- |
| AC-01 | 查询有效会员 | 200，等级与积分正确 |
| AC-02 | 查询不存在会员 | 404 MEMBER_NOT_FOUND |
| AC-03 | 重复提交升级请求 | 仅升级一次，响应幂等键一致 |

## 4. 关联接口

- **GET /v1/members/{memberId}**
- **GET /v1/members/{memberId}/benefits**
- **POST /v1/members/{memberId}/level**

## 5. 风险

- 等级变更需要与积分、优惠券服务保持最终一致
- 权益缓存 TTL 为 5 分钟，验收时需要等待缓存刷新
`,
  },
]

export const REQUIREMENTS: Requirement[] = [
  ...withProject('shop-api', SHOP_REQUIREMENTS),
  ...withProject('member-api', MEMBER_REQUIREMENTS),
]

const SHOP_OPENAPI_DOCS: Array<Omit<OpenApiDoc, 'projectId'>> = [
  {
    id: 'DOC-ORDER',
    title: '订单服务 API',
    version: 'v1.12.0',
    baseUrl: 'https://api.staging.shop.dev',
    updatedAt: '2026-11-20T10:00:00+08:00',
    description: '订单创建、查询、取消与库存锁定接口。所有请求与响应均为 application/json。',
    operations: [
      {
        id: 'op-create-order',
        docId: 'DOC-ORDER',
        method: 'POST',
        path: '/v1/orders',
        summary: '创建订单',
        tag: '订单',
        description: '校验库存并创建订单。库存不足时返回 409，不得生成订单。',
        params: [],
        requestBody: [
          { name: 'sku', type: 'string', required: true, description: '商品 SKU' },
          { name: 'quantity', type: 'integer', required: true, description: '购买数量，最小 1' },
          { name: 'user_id', type: 'string', required: true, description: '下单用户 ID' },
        ],
        responses: [
          {
            status: 201,
            description: '订单创建成功',
            fields: [
              { name: 'order_id', type: 'string', required: true, description: '订单号' },
              { name: 'status', type: 'string', required: true, description: '订单状态，CREATED' },
              { name: 'total', type: 'integer', required: true, description: '订单金额，单位分' },
            ],
          },
          {
            status: 409,
            description: '库存不足',
            fields: [
              { name: 'code', type: 'string', required: true, description: 'OUT_OF_STOCK' },
              { name: 'message', type: 'string', required: true, description: '错误说明' },
            ],
          },
        ],
        requirementIds: ['REQ-ORDER-01'],
        caseNodeids: [
          'tests/test_order.py::test_create_order_success',
          'tests/test_order.py::test_create_order_out_of_stock',
          'tests/test_order.py::test_order_idempotent_retry',
        ],
      },
      {
        id: 'op-get-order',
        docId: 'DOC-ORDER',
        method: 'GET',
        path: '/v1/orders/{orderId}',
        summary: '查询订单详情',
        tag: '订单',
        description: '按订单号查询订单与库存锁定状态。',
        params: [
          {
            name: 'orderId',
            in: 'path',
            type: 'string',
            required: true,
            description: '订单号',
          },
        ],
        responses: [
          {
            status: 200,
            description: '订单详情',
            fields: [
              { name: 'order_id', type: 'string', required: true, description: '订单号' },
              { name: 'status', type: 'string', required: true, description: '订单状态' },
              { name: 'locked', type: 'boolean', required: true, description: '库存是否仍处于锁定状态' },
            ],
          },
        ],
        requirementIds: ['REQ-ORDER-01'],
        caseNodeids: [],
      },
      {
        id: 'op-lock-inventory',
        docId: 'DOC-ORDER',
        method: 'POST',
        path: '/v1/inventory/lock',
        summary: '锁定库存',
        tag: '库存',
        description: '按 order_id 锁定库存。同一订单重复调用必须幂等，并发调用不得突破可用库存。',
        params: [],
        requestBody: [
          { name: 'sku', type: 'string', required: true, description: '商品 SKU' },
          { name: 'quantity', type: 'integer', required: true, description: '锁定数量' },
          { name: 'order_id', type: 'string', required: true, description: '关联订单号' },
        ],
        responses: [
          {
            status: 200,
            description: '锁定成功',
            fields: [
              { name: 'lock_id', type: 'string', required: true, description: '锁定记录 ID' },
              { name: 'remaining', type: 'integer', required: true, description: '锁定后的剩余可用库存' },
            ],
          },
          {
            status: 409,
            description: '库存不足',
            fields: [
              { name: 'code', type: 'string', required: true, description: 'OUT_OF_STOCK' },
              { name: 'remaining', type: 'integer', required: true, description: '当前可用库存' },
            ],
          },
        ],
        requirementIds: ['REQ-ORDER-01'],
        caseNodeids: [
          'tests/test_order.py::test_create_order_out_of_stock',
          'tests/test_inventory.py::test_lock_inventory_concurrent',
        ],
      },
      {
        id: 'op-cancel-order',
        docId: 'DOC-ORDER',
        method: 'DELETE',
        path: '/v1/orders/{orderId}',
        summary: '取消订单',
        tag: '订单',
        description: '取消订单并释放已锁定库存，按 order_id 保证幂等。',
        params: [
          {
            name: 'orderId',
            in: 'path',
            type: 'string',
            required: true,
            description: '订单号',
          },
        ],
        responses: [
          { status: 204, description: '取消成功', fields: [] },
        ],
        requirementIds: ['REQ-ORDER-01'],
        caseNodeids: [],
      },
    ],
  },
  {
    id: 'DOC-PAY',
    title: '支付服务 API',
    version: 'v2.4.0',
    baseUrl: 'https://api.staging.shop.dev',
    updatedAt: '2026-11-18T15:10:00+08:00',
    description: '支付创建、渠道回调、查询与退款接口。回调需按幂等键去重。',
    operations: [
      {
        id: 'op-create-payment',
        docId: 'DOC-PAY',
        method: 'POST',
        path: '/v1/payments',
        summary: '创建支付单',
        tag: '支付',
        description: '按订单创建支付单，金额由服务端从订单读取。',
        params: [],
        requestBody: [
          { name: 'order_id', type: 'string', required: true, description: '订单号' },
          { name: 'channel', type: 'string', required: true, description: '支付渠道' },
        ],
        responses: [
          {
            status: 201,
            description: '支付单创建成功',
            fields: [
              { name: 'payment_id', type: 'string', required: true, description: '支付单号' },
              { name: 'status', type: 'string', required: true, description: 'PENDING' },
            ],
          },
        ],
        requirementIds: ['REQ-PAY-02'],
        caseNodeids: [],
      },
      {
        id: 'op-payment-callback',
        docId: 'DOC-PAY',
        method: 'POST',
        path: '/v1/payments/callback',
        summary: '支付渠道回调',
        tag: '支付',
        description: '接收渠道支付结果。必须按 X-Idempotency-Key 去重，并在响应中回显该请求头。',
        params: [
          {
            name: 'X-Idempotency-Key',
            in: 'header',
            type: 'string',
            required: true,
            description: '渠道幂等键，24 小时内唯一',
          },
        ],
        requestBody: [
          { name: 'payment_id', type: 'string', required: true, description: '支付单号' },
          { name: 'status', type: 'string', required: true, description: 'SUCCESS / FAILED' },
          { name: 'amount', type: 'integer', required: true, description: '渠道实收金额，单位分' },
        ],
        responses: [
          {
            status: 200,
            description: '回调已处理',
            fields: [
              { name: 'received', type: 'boolean', required: true, description: '是否已接收' },
            ],
          },
          {
            status: 400,
            description: '金额不一致',
            fields: [
              { name: 'code', type: 'string', required: true, description: 'AMOUNT_MISMATCH' },
            ],
          },
        ],
        requirementIds: ['REQ-PAY-02'],
        caseNodeids: [
          'tests/test_payment.py::test_payment_callback_idempotent',
          'tests/test_payment.py::test_payment_amount_mismatch',
        ],
      },
      {
        id: 'op-get-payment',
        docId: 'DOC-PAY',
        method: 'GET',
        path: '/v1/payments/{paymentId}',
        summary: '查询支付单',
        tag: '支付',
        description: '按支付单号查询支付状态。',
        params: [
          {
            name: 'paymentId',
            in: 'path',
            type: 'string',
            required: true,
            description: '支付单号',
          },
        ],
        responses: [
          {
            status: 200,
            description: '支付单详情',
            fields: [
              { name: 'payment_id', type: 'string', required: true, description: '支付单号' },
              { name: 'status', type: 'string', required: true, description: '支付状态' },
            ],
          },
        ],
        requirementIds: ['REQ-PAY-02'],
        caseNodeids: [],
      },
      {
        id: 'op-create-refund',
        docId: 'DOC-PAY',
        method: 'POST',
        path: '/v1/refunds',
        summary: '发起退款',
        tag: '退款',
        description: '按原支付单发起全额退款，重复请求按幂等键去重。',
        params: [],
        requestBody: [
          { name: 'payment_id', type: 'string', required: true, description: '原支付单号' },
          { name: 'amount', type: 'integer', required: true, description: '退款金额，单位分' },
          { name: 'reason', type: 'string', required: false, description: '退款原因' },
        ],
        responses: [
          {
            status: 201,
            description: '退款已受理',
            fields: [
              { name: 'refund_id', type: 'string', required: true, description: '退款单号' },
              { name: 'status', type: 'string', required: true, description: 'ACCEPTED' },
            ],
          },
        ],
        requirementIds: ['REQ-PAY-02'],
        caseNodeids: ['tests/test_payment.py::test_refund_full'],
      },
    ],
  },
]

const MEMBER_OPENAPI_DOCS: Array<Omit<OpenApiDoc, 'projectId'>> = [
  {
    id: 'DOC-MEMBER',
    title: '会员中心 API',
    version: 'v1.4.0',
    baseUrl: 'https://api.staging.shop.dev',
    updatedAt: '2026-11-20T15:20:00+08:00',
    description:
      '会员等级、积分与权益查询，以及等级变更。等级变更按幂等键去重。',
    operations: [
      {
        id: 'op-member-profile',
        docId: 'DOC-MEMBER',
        method: 'GET',
        path: '/v1/members/{memberId}',
        summary: '查询会员详情',
        tag: '会员',
        description: '按会员号返回等级、积分与账号状态。',
        params: [
          {
            name: 'memberId',
            in: 'path',
            type: 'string',
            required: true,
            description: '会员号，例如 M-88120',
          },
        ],
        responses: [
          {
            status: 200,
            description: '会员详情',
            fields: [
              { name: 'member_id', type: 'string', required: true, description: '会员号' },
              { name: 'level', type: 'string', required: true, description: 'GOLD / PLATINUM' },
              { name: 'points', type: 'integer', required: true, description: '积分余额' },
              { name: 'status', type: 'string', required: true, description: 'ACTIVE / CLOSED' },
            ],
          },
          {
            status: 404,
            description: '会员不存在',
            fields: [
              { name: 'code', type: 'string', required: true, description: 'MEMBER_NOT_FOUND' },
            ],
          },
        ],
        requirementIds: ['REQ-MEMBER-01'],
        caseNodeids: ['tests/test_member.py::test_profile_detail'],
      },
      {
        id: 'op-member-benefits',
        docId: 'DOC-MEMBER',
        method: 'GET',
        path: '/v1/members/{memberId}/benefits',
        summary: '查询会员权益',
        tag: '权益',
        description: '按当前等级返回权益列表，顺序稳定且不重复。',
        params: [
          {
            name: 'memberId',
            in: 'path',
            type: 'string',
            required: true,
            description: '会员号',
          },
        ],
        responses: [
          {
            status: 200,
            description: '权益列表',
            fields: [
              { name: 'level', type: 'string', required: true, description: '会员等级' },
              { name: 'benefits', type: 'array', required: true, description: '权益数组，按优先级排序' },
            ],
          },
        ],
        requirementIds: ['REQ-MEMBER-01'],
        caseNodeids: ['tests/test_member.py::test_benefits_consistency'],
      },
      {
        id: 'op-member-level',
        docId: 'DOC-MEMBER',
        method: 'POST',
        path: '/v1/members/{memberId}/level',
        summary: '变更会员等级',
        tag: '会员',
        description: '升级会员等级；相同幂等键重复提交返回同一结果。',
        params: [
          {
            name: 'memberId',
            in: 'path',
            type: 'string',
            required: true,
            description: '会员号',
          },
          {
            name: 'x-idempotency-key',
            in: 'header',
            type: 'string',
            required: true,
            description: '幂等键，24 小时内有效',
          },
        ],
        requestBody: [
          { name: 'level', type: 'string', required: true, description: '目标等级' },
        ],
        responses: [
          {
            status: 200,
            description: '变更成功或幂等返回',
            fields: [
              { name: 'member_id', type: 'string', required: true, description: '会员号' },
              { name: 'level', type: 'string', required: true, description: '变更后的等级' },
            ],
          },
          {
            status: 409,
            description: '等级流转非法',
            fields: [
              { name: 'code', type: 'string', required: true, description: 'LEVEL_TRANSITION_DENIED' },
            ],
          },
        ],
        requirementIds: ['REQ-MEMBER-01'],
        caseNodeids: ['tests/test_member.py::test_level_upgrade_idempotent'],
      },
    ],
  },
]

export const OPENAPI_DOCS: OpenApiDoc[] = [
  ...withProject('shop-api', SHOP_OPENAPI_DOCS),
  ...withProject('member-api', MEMBER_OPENAPI_DOCS),
]

const SHOP_TEST_CASES: Array<Omit<TestCase, 'projectId'>> = [
  {
    nodeid: 'tests/test_order.py::test_create_order_success',
    name: 'test_create_order_success',
    file: 'tests/test_order.py',
    tags: ['订单', '冒烟'],
    requirementIds: ['REQ-ORDER-01'],
    operationIds: ['op-create-order'],
    lastRunId: 'RUN-1124-0912',
    lastStatus: 'passed',
    lastDurationMs: 142,
  },
  {
    nodeid: 'tests/test_order.py::test_create_order_out_of_stock',
    name: 'test_create_order_out_of_stock',
    file: 'tests/test_order.py',
    tags: ['订单', '库存', '异常流'],
    requirementIds: ['REQ-ORDER-01'],
    operationIds: ['op-create-order', 'op-lock-inventory'],
    lastRunId: 'RUN-1124-0912',
    lastStatus: 'failed',
    lastDurationMs: 221,
  },
  {
    nodeid: 'tests/test_order.py::test_order_idempotent_retry',
    name: 'test_order_idempotent_retry',
    file: 'tests/test_order.py',
    tags: ['订单', '幂等'],
    requirementIds: ['REQ-ORDER-01'],
    operationIds: ['op-create-order'],
    lastRunId: 'RUN-1124-0912',
    lastStatus: 'passed',
    lastDurationMs: 187,
  },
  {
    nodeid: 'tests/test_inventory.py::test_lock_inventory_concurrent',
    name: 'test_lock_inventory_concurrent',
    file: 'tests/test_inventory.py',
    tags: ['库存', '并发', 'P0'],
    requirementIds: ['REQ-ORDER-01'],
    operationIds: ['op-lock-inventory'],
    lastRunId: 'RUN-1124-0912',
    lastStatus: 'failed',
    lastDurationMs: 305,
  },
  {
    nodeid: 'tests/test_payment.py::test_payment_callback_idempotent',
    name: 'test_payment_callback_idempotent',
    file: 'tests/test_payment.py',
    tags: ['支付', '回调', '幂等'],
    requirementIds: ['REQ-PAY-02'],
    operationIds: ['op-payment-callback'],
    lastRunId: 'RUN-1124-0912',
    lastStatus: 'passed',
    lastDurationMs: 512,
  },
  {
    nodeid: 'tests/test_payment.py::test_payment_amount_mismatch',
    name: 'test_payment_amount_mismatch',
    file: 'tests/test_payment.py',
    tags: ['支付', '异常流'],
    requirementIds: ['REQ-PAY-02'],
    operationIds: ['op-payment-callback'],
    lastRunId: 'RUN-1124-0912',
    lastStatus: 'passed',
    lastDurationMs: 198,
  },
  {
    nodeid: 'tests/test_payment.py::test_refund_full',
    name: 'test_refund_full',
    file: 'tests/test_payment.py',
    tags: ['支付', '退款'],
    requirementIds: ['REQ-PAY-02'],
    operationIds: ['op-create-refund'],
    lastRunId: 'RUN-1124-0912',
    lastStatus: 'passed',
    lastDurationMs: 233,
  },
  {
    nodeid: 'tests/test_user.py::test_login_risk_control',
    name: 'test_login_risk_control',
    file: 'tests/test_user.py',
    tags: ['用户', '风控', '不稳定'],
    requirementIds: ['REQ-USER-03'],
    operationIds: [],
    lastRunId: 'RUN-1124-0912',
    lastStatus: 'passed',
    lastDurationMs: 156,
  },
  {
    nodeid: 'tests/test_user.py::test_session_expired',
    name: 'test_session_expired',
    file: 'tests/test_user.py',
    tags: ['用户', '会话'],
    requirementIds: ['REQ-USER-03'],
    operationIds: [],
    lastRunId: 'RUN-1124-0912',
    lastStatus: 'passed',
    lastDurationMs: 118,
  },
  {
    nodeid: 'tests/test_report.py::test_daily_report_aggregation',
    name: 'test_daily_report_aggregation',
    file: 'tests/test_report.py',
    tags: ['报表', '离线'],
    requirementIds: [],
    operationIds: [],
    lastRunId: 'RUN-1124-0912',
    lastStatus: 'skipped',
    lastDurationMs: 0,
  },
]

const MEMBER_TEST_CASES: Array<Omit<TestCase, 'projectId'>> = [
  {
    nodeid: 'tests/test_member.py::test_profile_detail',
    name: 'test_profile_detail',
    file: 'tests/test_member.py',
    tags: ['会员', '冒烟'],
    requirementIds: ['REQ-MEMBER-01'],
    operationIds: ['op-member-profile'],
    lastRunId: 'RUN-M2411-1030',
    lastStatus: 'passed',
    lastDurationMs: 96,
  },
  {
    nodeid: 'tests/test_member.py::test_benefits_consistency',
    name: 'test_benefits_consistency',
    file: 'tests/test_member.py',
    tags: ['会员', '权益'],
    requirementIds: ['REQ-MEMBER-01'],
    operationIds: ['op-member-benefits'],
    lastRunId: 'RUN-M2411-1030',
    lastStatus: 'passed',
    lastDurationMs: 112,
  },
  {
    nodeid: 'tests/test_member.py::test_level_upgrade_idempotent',
    name: 'test_level_upgrade_idempotent',
    file: 'tests/test_member.py',
    tags: ['会员', '等级', '幂等'],
    requirementIds: ['REQ-MEMBER-01'],
    operationIds: ['op-member-level'],
    lastRunId: 'RUN-M2411-1030',
    lastStatus: 'passed',
    lastDurationMs: 164,
  },
]

export const TEST_CASES: TestCase[] = [
  ...withProject('shop-api', SHOP_TEST_CASES),
  ...withProject('member-api', MEMBER_TEST_CASES),
]

const EVIDENCE: Record<string, Exchange[]> = {
  'tests/test_order.py::test_create_order_success': [
    ex(
      0,
      'POST',
      '/v1/orders',
      201,
      142,
      { sku: 'SKU-1001', quantity: 2, user_id: 'U-2201' },
      {
        order_id: 'ORD-20261124-0001',
        status: 'CREATED',
        total: 59800,
        currency: 'CNY',
      },
    ),
  ],
  'tests/test_order.py::test_create_order_out_of_stock': [
    ex(
      0,
      'POST',
      '/v1/inventory/lock',
      200,
      98,
      { sku: 'SKU-1001', quantity: 1, order_id: 'ORD-20261124-0007' },
      { lock_id: 'LCK-7781', sku: 'SKU-1001', remaining: 0 },
    ),
    ex(
      1,
      'POST',
      '/v1/orders',
      201,
      121,
      { sku: 'SKU-1001', quantity: 1, user_id: 'U-2207' },
      { order_id: 'ORD-20261124-0007', status: 'CREATED', total: 29900 },
    ),
  ],
  'tests/test_order.py::test_order_idempotent_retry': [
    ex(
      0,
      'POST',
      '/v1/orders',
      201,
      187,
      { sku: 'SKU-1002', quantity: 1, user_id: 'U-2203' },
      { order_id: 'ORD-20261124-0003', status: 'CREATED', total: 12900 },
      { reqHeaders: { 'idempotency-key': 'idem-9f31c2' } },
    ),
    ex(
      1,
      'POST',
      '/v1/orders',
      201,
      96,
      { sku: 'SKU-1002', quantity: 1, user_id: 'U-2203' },
      { order_id: 'ORD-20261124-0003', status: 'CREATED', total: 12900 },
      { reqHeaders: { 'idempotency-key': 'idem-9f31c2' } },
    ),
  ],
  'tests/test_inventory.py::test_lock_inventory_concurrent': [
    ex(
      0,
      'POST',
      '/v1/inventory/lock',
      200,
      141,
      { sku: 'SKU-1001', quantity: 1, order_id: 'ORD-20261124-0011' },
      { lock_id: 'LCK-9001', sku: 'SKU-1001', remaining: 1 },
    ),
    ex(
      1,
      'POST',
      '/v1/inventory/lock',
      200,
      146,
      { sku: 'SKU-1001', quantity: 1, order_id: 'ORD-20261124-0012' },
      { lock_id: 'LCK-9002', sku: 'SKU-1001', remaining: 1 },
    ),
    ex(
      2,
      'GET',
      '/v1/inventory/SKU-1001',
      200,
      37,
      {},
      { sku: 'SKU-1001', stock: 1, locked: 2, available: -1 },
    ),
  ],
  'tests/test_payment.py::test_payment_callback_idempotent': [
    ex(
      0,
      'POST',
      '/v1/payments/callback',
      200,
      512,
      { payment_id: 'PAY-8891', status: 'SUCCESS', amount: 29900 },
      { received: true },
      { reqHeaders: { 'x-idempotency-key': 'cb-7712-a' } },
    ),
    ex(
      1,
      'POST',
      '/v1/payments/callback',
      200,
      87,
      { payment_id: 'PAY-8891', status: 'SUCCESS', amount: 29900 },
      { received: true },
      { reqHeaders: { 'x-idempotency-key': 'cb-7712-a' } },
    ),
  ],
  'tests/test_payment.py::test_payment_amount_mismatch': [
    ex(
      0,
      'POST',
      '/v1/payments/callback',
      400,
      198,
      { payment_id: 'PAY-8892', status: 'SUCCESS', amount: 39800 },
      { code: 'AMOUNT_MISMATCH', message: 'callback amount does not match order' },
      { reqHeaders: { 'x-idempotency-key': 'cb-8892-a' } },
    ),
  ],
  'tests/test_payment.py::test_refund_full': [
    ex(
      0,
      'POST',
      '/v1/refunds',
      201,
      233,
      { payment_id: 'PAY-8891', amount: 29900, reason: '用户取消' },
      { refund_id: 'RFD-2201', status: 'ACCEPTED' },
    ),
  ],
  'tests/test_user.py::test_login_risk_control': [
    ex(
      0,
      'POST',
      '/v1/auth/login',
      200,
      156,
      { account: 'tester@example.com', device_id: 'D-7712' },
      { session_id: 'SES-7712', risk_level: 'low' },
    ),
  ],
  'tests/test_user.py::test_session_expired': [
    ex(
      0,
      'GET',
      '/v1/auth/session',
      401,
      118,
      {},
      { code: 'SESSION_EXPIRED', message: 'session is no longer valid' },
    ),
  ],
  'tests/test_report.py::test_daily_report_aggregation': [
    ex(
      0,
      'GET',
      '/v1/reports/daily?date=2026-11-23',
      200,
      204,
      {},
      {
        date: '2026-11-23',
        orders: 1284,
        gmv: 38420000,
        timezone: 'Asia/Shanghai',
      },
    ),
  ],
  'tests/test_member.py::test_profile_detail': [
    ex(
      0,
      'GET',
      '/v1/members/M-88120',
      200,
      96,
      {},
      {
        member_id: 'M-88120',
        level: 'GOLD',
        points: 12800,
        status: 'ACTIVE',
      },
    ),
  ],
  'tests/test_member.py::test_benefits_consistency': [
    ex(
      0,
      'GET',
      '/v1/members/M-88120/benefits',
      200,
      112,
      {},
      {
        level: 'GOLD',
        benefits: [
          { code: 'FREE_SHIPPING', remaining: 6 },
          { code: 'BIRTHDAY_COUPON', remaining: 1 },
        ],
      },
    ),
  ],
  'tests/test_member.py::test_level_upgrade_idempotent': [
    ex(
      0,
      'POST',
      '/v1/members/M-88120/level',
      200,
      164,
      { level: 'PLATINUM' },
      { member_id: 'M-88120', level: 'PLATINUM' },
      {
        reqHeaders: { 'x-idempotency-key': 'mup-5521' },
        respHeaders: { 'x-idempotency-key': 'mup-5521' },
      },
    ),
    ex(
      1,
      'POST',
      '/v1/members/M-88120/level',
      200,
      88,
      { level: 'PLATINUM' },
      { member_id: 'M-88120', level: 'PLATINUM' },
      {
        reqHeaders: { 'x-idempotency-key': 'mup-5521' },
        respHeaders: { 'x-idempotency-key': 'mup-5521' },
      },
    ),
  ],
}

const RUN2_CALLBACK_EVIDENCE: Exchange[] = [
  ex(
    0,
    'POST',
    '/v1/payments/callback',
    504,
    30000,
    { payment_id: 'PAY-8901', status: 'SUCCESS', amount: 29900 },
    { code: 'GATEWAY_TIMEOUT', message: 'upstream gateway timeout' },
    { reqHeaders: { 'x-idempotency-key': 'cb-8901-b' } },
  ),
]

const RUN2_LOGIN_EVIDENCE: Exchange[] = [
  ex(
    0,
    'POST',
    '/v1/auth/login',
    429,
    45,
    { account: 'tester@example.com', device_id: 'D-7712' },
    { code: 'RATE_LIMITED', message: 'too many login attempts' },
    { respHeaders: { 'retry-after': '30' } },
  ),
]

interface RunSpec {
  projectId: string
  id: string
  startedAt: string
  durationMs: number
  environment: string
  branch: string
  commit: string
  statuses: Record<string, RunStatus>
  durations: Record<string, number>
  errors?: Record<string, string>
  evidenceOverrides?: Record<string, Exchange[]>
  logsOverrides?: Record<string, string[]>
}

const RUN_SPECS: RunSpec[] = [
  {
    projectId: 'shop-api',
    id: 'RUN-1124-0912',
    startedAt: '2026-11-24T09:12:33+08:00',
    durationMs: 42600,
    environment: '预发 · staging-cn-east',
    branch: 'main',
    commit: 'a7f3c21',
    statuses: {
      'tests/test_order.py::test_create_order_out_of_stock': 'failed',
      'tests/test_inventory.py::test_lock_inventory_concurrent': 'failed',
      'tests/test_report.py::test_daily_report_aggregation': 'skipped',
    },
    durations: {
      'tests/test_order.py::test_create_order_success': 142,
      'tests/test_order.py::test_create_order_out_of_stock': 221,
      'tests/test_order.py::test_order_idempotent_retry': 187,
      'tests/test_inventory.py::test_lock_inventory_concurrent': 305,
      'tests/test_payment.py::test_payment_callback_idempotent': 512,
      'tests/test_payment.py::test_payment_amount_mismatch': 198,
      'tests/test_payment.py::test_refund_full': 233,
      'tests/test_user.py::test_login_risk_control': 156,
      'tests/test_user.py::test_session_expired': 118,
      'tests/test_report.py::test_daily_report_aggregation': 0,
    },
    errors: {
      'tests/test_order.py::test_create_order_out_of_stock':
        'AssertionError: expected 409 OUT_OF_STOCK, got 201 CREATED',
      'tests/test_inventory.py::test_lock_inventory_concurrent':
        'AssertionError: locked=2 exceeds stock=1 (available=-1)',
    },
  },
  {
    projectId: 'shop-api',
    id: 'RUN-1123-1830',
    startedAt: '2026-11-23T18:30:06+08:00',
    durationMs: 38900,
    environment: '预发 · staging-cn-east',
    branch: 'release/2026.11',
    commit: 'f09d77b',
    statuses: {
      'tests/test_payment.py::test_payment_callback_idempotent': 'error',
      'tests/test_user.py::test_login_risk_control': 'failed',
    },
    durations: {
      'tests/test_order.py::test_create_order_success': 138,
      'tests/test_order.py::test_create_order_out_of_stock': 203,
      'tests/test_order.py::test_order_idempotent_retry': 192,
      'tests/test_inventory.py::test_lock_inventory_concurrent': 288,
      'tests/test_payment.py::test_payment_callback_idempotent': 30012,
      'tests/test_payment.py::test_payment_amount_mismatch': 201,
      'tests/test_payment.py::test_refund_full': 229,
      'tests/test_user.py::test_login_risk_control': 46,
      'tests/test_user.py::test_session_expired': 112,
      'tests/test_report.py::test_daily_report_aggregation': 198,
    },
    errors: {
      'tests/test_payment.py::test_payment_callback_idempotent':
        'httpx.ReadTimeout: timed out after 30.0s while waiting for callback response',
      'tests/test_user.py::test_login_risk_control':
        'AssertionError: expected 200, got 429 RATE_LIMITED',
    },
    evidenceOverrides: {
      'tests/test_payment.py::test_payment_callback_idempotent': RUN2_CALLBACK_EVIDENCE,
      'tests/test_user.py::test_login_risk_control': RUN2_LOGIN_EVIDENCE,
    },
    logsOverrides: {
      'tests/test_payment.py::test_payment_callback_idempotent': [
        '[18:30:52] INFO  pytest_traffic_capture: --capture-traffic enabled',
        '[18:30:52] INFO  tests.test_payment: start test_payment_callback_idempotent',
        '[18:30:52] INFO  httpx: POST https://api.staging.shop.dev/v1/payments/callback',
        '[18:31:22] ERROR httpx.ReadTimeout: callback response exceeded 30s',
        '[18:31:22] WARN  已写入 HAR，响应体为空，标记 _error',
      ],
    },
  },
  {
    projectId: 'shop-api',
    id: 'RUN-1122-1510',
    startedAt: '2026-11-22T15:10:18+08:00',
    durationMs: 40100,
    environment: '预发 · staging-cn-east',
    branch: 'release/2026.11',
    commit: '3c81e0a',
    statuses: {
      'tests/test_report.py::test_daily_report_aggregation': 'skipped',
    },
    durations: {
      'tests/test_order.py::test_create_order_success': 145,
      'tests/test_order.py::test_create_order_out_of_stock': 212,
      'tests/test_order.py::test_order_idempotent_retry': 190,
      'tests/test_inventory.py::test_lock_inventory_concurrent': 297,
      'tests/test_payment.py::test_payment_callback_idempotent': 488,
      'tests/test_payment.py::test_payment_amount_mismatch': 195,
      'tests/test_payment.py::test_refund_full': 241,
      'tests/test_user.py::test_login_risk_control': 149,
      'tests/test_user.py::test_session_expired': 121,
      'tests/test_report.py::test_daily_report_aggregation': 0,
    },
  },
  {
    projectId: 'member-api',
    id: 'RUN-M2411-1030',
    startedAt: '2026-11-23T10:30:12+08:00',
    durationMs: 12640,
    environment: '预发 · staging-cn-east',
    branch: 'main',
    commit: 'b41d8e2',
    statuses: {},
    durations: {
      'tests/test_member.py::test_profile_detail': 96,
      'tests/test_member.py::test_benefits_consistency': 112,
      'tests/test_member.py::test_level_upgrade_idempotent': 164,
    },
  },
]

function buildLogs(nodeid: string, status: RunStatus, error?: string): string[] {
  const name = nodeid.split('::')[1] ?? nodeid
  const logs = [
    '[run] INFO  pytest_traffic_capture: --capture-traffic enabled',
    `[run] INFO  ${nodeid.split('::')[0].replace(/\//g, '.')}: start ${name}`,
    '[run] INFO  httpx: HTTP request captured → HAR 1.2',
  ]
  if (status === 'skipped') {
    logs.push('[run] WARN  用例被标记为 skip：依赖上游报表任务')
  } else if (status === 'failed' || status === 'error') {
    logs.push(`[run] ERROR ${error ?? '用例失败'}`)
    logs.push('[run] INFO  已写入 captured_traffic/，可直接回放证据')
  } else {
    logs.push('[run] INFO  用例通过，抓包已落盘')
  }
  return logs
}

function buildRun(spec: RunSpec): Run {
  const cases: RunCase[] = TEST_CASES.filter(
    (testCase) => testCase.projectId === spec.projectId,
  ).map((testCase) => {
    const status = spec.statuses[testCase.nodeid] ?? 'passed'
    return {
      nodeid: testCase.nodeid,
      status,
      durationMs: spec.durations[testCase.nodeid] ?? 0,
      error: spec.errors?.[testCase.nodeid],
      logs:
        spec.logsOverrides?.[testCase.nodeid] ??
        buildLogs(testCase.nodeid, status, spec.errors?.[testCase.nodeid]),
      exchanges:
        spec.evidenceOverrides?.[testCase.nodeid] ??
        EVIDENCE[testCase.nodeid] ??
        [],
    }
  })

  const stats: RunStats = {
    total: cases.length,
    passed: cases.filter((item) => item.status === 'passed').length,
    failed: cases.filter((item) => item.status === 'failed').length,
    skipped: cases.filter((item) => item.status === 'skipped').length,
    error: cases.filter((item) => item.status === 'error').length,
  }

  return {
    projectId: spec.projectId,
    id: spec.id,
    startedAt: spec.startedAt,
    durationMs: spec.durationMs,
    environment: spec.environment,
    branch: spec.branch,
    commit: spec.commit,
    stats,
    cases,
  }
}

export const RUNS: Run[] = RUN_SPECS.map(buildRun)

const SHOP_FINDINGS: Array<Omit<Finding, 'projectId'>> = [
  {
    id: 'FND-001',
    runId: 'RUN-1124-0912',
    nodeid: 'tests/test_inventory.py::test_lock_inventory_concurrent',
    type: 'regression',
    title: '并发库存锁定未做原子校验，存在超卖风险',
    summary:
      '两条并发锁定请求都返回 200，locked 计数达到 2 而库存仅 1，available 变为 -1。锁定链路缺少原子性保护。',
    rootCause:
      '库存服务在读取、校验、写入之间没有加行锁或乐观版本校验，两个请求同时通过 remaining >= quantity 判断。',
    impact:
      '预发环境可稳定复现超卖，影响下单链路与库存一致性，属于发布阻塞问题。',
    confidence: 0.92,
    suggestedSeverity: 'critical',
    exchangeIndex: 1,
    requirementId: 'REQ-ORDER-01',
    operationId: 'op-lock-inventory',
    status: 'pending',
    createdAt: '2026-11-24T09:13:02+08:00',
  },
  {
    id: 'FND-002',
    runId: 'RUN-1124-0912',
    nodeid: 'tests/test_order.py::test_create_order_out_of_stock',
    type: 'spec-mismatch',
    title: '缺货场景未按验收标准返回 409',
    summary:
      '库存 remaining=0 时锁定接口仍返回 200，订单继续创建成功，与 FR-3 的 409 OUT_OF_STOCK 约定不符。',
    rootCause:
      '锁定服务把 remaining=0 当作可锁定，未返回缺货错误码；订单服务也未对锁定结果做二次校验。',
    impact:
      '缺货订单可以继续支付，形成负库存与售后补偿，直接违背需求 AC-03。',
    confidence: 0.88,
    suggestedSeverity: 'blocker',
    exchangeIndex: 0,
    requirementId: 'REQ-ORDER-01',
    operationId: 'op-lock-inventory',
    status: 'pending',
    createdAt: '2026-11-24T09:13:04+08:00',
  },
  {
    id: 'FND-003',
    runId: 'RUN-1124-0912',
    nodeid: 'tests/test_payment.py::test_payment_callback_idempotent',
    type: 'contract',
    title: '支付回调响应未回显幂等键，重试链路难以对账',
    summary:
      '请求携带 X-Idempotency-Key，响应缺少同名回显头。OpenAPI 契约要求回显，便于网关确认回调已被处理。',
    rootCause:
      '回调处理器只返回 received 字段，没有透传请求中的幂等键到响应头。',
    impact:
      '网关重试时无法确认本次回调是否已被处理，增加重复入账与人工对账成本。',
    confidence: 0.76,
    suggestedSeverity: 'major',
    exchangeIndex: 0,
    requirementId: 'REQ-PAY-02',
    operationId: 'op-payment-callback',
    status: 'pending',
    createdAt: '2026-11-24T09:13:07+08:00',
  },
  {
    id: 'FND-004',
    runId: 'RUN-1124-0912',
    nodeid: 'tests/test_payment.py::test_payment_callback_idempotent',
    type: 'duplicate',
    title: '与历史缺陷 DEF-0982 疑似重复：支付回调重复入账',
    summary:
      '本次失败特征与 DEF-0982 的重复入账路径高度相似，均发生在回调重试且幂等键未被正确回显时。',
    rootCause: '回调幂等逻辑没有覆盖网关重试场景，历史修复可能不完整。',
    impact:
      '若直接复用历史修复结论，发布后仍可能重现重复入账，需要补充回归证据。',
    confidence: 0.61,
    suggestedSeverity: 'major',
    exchangeIndex: 0,
    requirementId: 'REQ-PAY-02',
    operationId: 'op-payment-callback',
    status: 'pending',
    createdAt: '2026-11-24T09:13:09+08:00',
  },
  {
    id: 'FND-005',
    runId: 'RUN-1123-1830',
    nodeid: 'tests/test_user.py::test_login_risk_control',
    type: 'flaky',
    title: '登录风控在并发请求下返回 429，用例未做重试',
    summary:
      'run2 中该用例收到 429，run1 与更早批次均为 200，推测为环境限流阈值波动放大。',
    rootCause:
      '预发网关限流阈值被调低，用例并发度较高触发限流；客户端没有退避重试。',
    impact: '非产品缺陷，但会造成流水线不稳定与误判，需要补重试策略。',
    confidence: 0.83,
    suggestedSeverity: 'major',
    exchangeIndex: 0,
    requirementId: 'REQ-USER-03',
    status: 'confirmed',
    note: '已确认为环境限流导致的偶发失败，同时需要给用例补退避重试。',
    judgedAt: '2026-11-23T18:41:12+08:00',
    defectId: 'DEF-1007',
    createdAt: '2026-11-23T18:31:24+08:00',
  },
  {
    id: 'FND-006',
    runId: 'RUN-1123-1830',
    nodeid: 'tests/test_payment.py::test_payment_callback_idempotent',
    type: 'contract',
    title: '回调超时被判定为契约异常',
    summary:
      'AI 将 504 超时归类为契约问题，但 OpenAPI 没有约定 504 响应，证据不足以支持该结论。',
    rootCause: '网络超时导致上游网关直接返回 504，并非服务契约变更。',
    impact: '无需修改契约，建议补充超时重试与告警，避免流水线误报。',
    confidence: 0.68,
    suggestedSeverity: 'minor',
    exchangeIndex: 0,
    requirementId: 'REQ-PAY-02',
    operationId: 'op-payment-callback',
    status: 'false-positive',
    note: '预发网络抖动导致，契约本身无问题。',
    judgedAt: '2026-11-23T18:43:40+08:00',
    createdAt: '2026-11-23T18:31:30+08:00',
  },
]

export const FINDINGS: Finding[] = withProject('shop-api', SHOP_FINDINGS)

const SHOP_DEFECTS: Array<Omit<Defect, 'projectId'>> = [
  {
    id: 'DEF-1007',
    title: '登录风控在并发请求下返回 429，用例未做重试',
    severity: 'major',
    status: 'fixing',
    findingId: 'FND-005',
    runId: 'RUN-1123-1830',
    nodeid: 'tests/test_user.py::test_login_risk_control',
    requirementId: 'REQ-USER-03',
    exchangeIndex: 0,
    evidenceSummary:
      'RUN-1123-1830 / tests/test_user.py::test_login_risk_control / 第 1 次交换（429 RATE_LIMITED）',
    source: 'AI 审判',
    decision: {
      verdict: 'confirm',
      note: '已确认为环境限流导致的偶发失败，同时需要给用例补退避重试。',
      at: '2026-11-23T18:41:12+08:00',
    },
    createdAt: '2026-11-23T18:41:12+08:00',
    updatedAt: '2026-11-24T08:20:00+08:00',
  },
  {
    id: 'DEF-0982',
    title: '支付回调重复入账导致账实不一致',
    severity: 'blocker',
    status: 'fixed',
    runId: 'RUN-1118-1040',
    nodeid: 'tests/test_payment.py::test_payment_callback_idempotent',
    requirementId: 'REQ-PAY-02',
    operationId: 'op-payment-callback',
    exchangeIndex: 0,
    evidenceSummary:
      '历史批次 RUN-1118-1040 / 支付回调重试 / 第 2 次重复回调写入成功',
    source: 'AI 审判',
    decision: {
      verdict: 'confirm',
      note: '补丁已上线，回调按 X-Idempotency-Key 去重；本次回归继续观察幂等键回显。',
      at: '2026-11-18T14:20:00+08:00',
    },
    createdAt: '2026-11-18T11:02:00+08:00',
    updatedAt: '2026-11-21T10:12:00+08:00',
  },
]

export const DEFECTS: Defect[] = withProject('shop-api', SHOP_DEFECTS)

/**
 * 运行级分析结果由外部流水线在 pytest 之后写入，平台只读取与展示，
 * 不在页面内触发模型调用。
 */
const ANALYZER = 'pytest-ai-analyzer v0.4.2'
const ANALYZER_MODEL = 'qwen3-coder-480b'

const RUN_OBSERVATIONS: Record<string, string> = {
  'RUN-1124-0912':
    '抓包显示库存锁定链路在并发与零库存场景下都未快速失败，属于同一类契约缺口；支付回调另有幂等键未回显的问题。',
  'RUN-1123-1830':
    '回调请求 30s 内未拿到响应，登录用例受网关限流影响返回 429，更像环境与重试策略问题。',
}

const SUMMARY_GENERATED_AT: Record<string, string> = {
  'RUN-1124-0912': '2026-11-24T09:13:22+08:00',
  'RUN-1123-1830': '2026-11-23T18:31:38+08:00',
  'RUN-1122-1510': '2026-11-22T15:11:05+08:00',
  'RUN-M2411-1030': '2026-11-23T10:30:31+08:00',
}

const caseName = (nodeid: string) => nodeid.split('::')[1] ?? nodeid

function buildSummary(run: Run): AiSummary {
  const failed = run.cases.filter(
    (item) => item.status === 'failed' || item.status === 'error',
  )
  const findingCount = FINDINGS.filter((item) => item.runId === run.id).length
  const skipped = run.stats.skipped

  const overview = `本次运行 ${run.id} 共执行 ${run.stats.total} 条用例：${run.stats.passed} 通过、${run.stats.failed} 失败、${run.stats.error} 错误${
    skipped ? `、${skipped} 跳过` : ''
  }，总耗时 ${(run.durationMs / 1000).toFixed(1)}s。`

  const failures = failed.length
    ? `失败集中在 ${failed
        .map(
          (item) =>
            `${caseName(item.nodeid)}（${item.error ?? '用例失败'}）`,
        )
        .join('、')}。${RUN_OBSERVATIONS[run.id] ?? ''}`
    : `本次运行没有失败用例，抓包证据与接口契约基本一致。${
        skipped ? '跳过用例仍需补齐依赖后单独回归。' : '可以进入下一轮回归。'
      }`

  const findings = findingCount
    ? `结合需求验收标准与 OpenAPI 契约，本次写入 ${findingCount} 条发现。建议先判断阻塞项的发布影响，再评估契约类偏差。`
    : '本次没有写入需要人工审判的发现，HAR 与日志仅作为归档证据保留。'

  const source =
    '本分析由外部流水线写入，平台只负责聚合证据与人工裁决，不会在页面内调用模型。'

  return {
    runId: run.id,
    text: [overview, failures, findings, source].join('\n\n'),
    generatedAt: SUMMARY_GENERATED_AT[run.id] ?? run.startedAt,
    analyzer: ANALYZER,
    model: ANALYZER_MODEL,
  }
}

export const SUMMARIES: Record<string, AiSummary> = Object.fromEntries(
  RUNS.map((run) => [run.id, buildSummary(run)]),
)
