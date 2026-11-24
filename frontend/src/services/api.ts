import type {
  AiSummary,
  AppData,
  Defect,
  DefectStatus,
  Exchange,
  Finding,
  FindingStatus,
  FindingType,
  HttpMethod,
  OpenApiDoc,
  Operation,
  OperationParam,
  OperationResponse,
  Project,
  Requirement,
  Run,
  RunCase,
  RunRequest,
  RunRequestStatus,
  RunStatus,
  SchemaField,
  Severity,
  TestCase,
  Verdict,
} from '../types'
import {
  DEFECTS,
  FINDINGS,
  OPENAPI_DOCS,
  PROJECTS,
  REQUIREMENTS,
  RUNS,
  SUMMARIES,
  TEST_CASES,
} from '../data/seed'

/**
 * 数据出入口。
 * API_MODE='mock' 时使用前端种子数据；'http' 时对接真实后端。
 * 组件层只依赖 AppData，后端字段差异全部在本文件内转换。
 */
export const API_MODE: 'mock' | 'http' = 'http'
export const BASE_URL = '/api/v1'
export const REQUIRES_AUTH = API_MODE === 'http'
const STORAGE_KEY = 'ai-test-workbench:v2'
const TOKEN_KEY = 'ai-test-workbench:token'

interface Persisted {
  findings: Finding[]
  defects: Defect[]
}

interface BackendUser {
  id: string
  email: string
  displayName: string
}

export interface Session {
  user: BackendUser
}

export interface CreateProjectInput {
  key: string
  name: string
  repo?: string
  environment?: string
  owner?: string
}

interface LoginResponse {
  accessToken: string
  tokenType: string
  user: BackendUser
  projects: BackendProject[]
}

interface BackendProject {
  id: string
  key: string
  name: string
  repo: string
  environment: string
  owner: string
  updatedAt: string
  role: string
}

interface BackendRun {
  id: string
  externalId: string
  startedAt: string
  durationMs: number
  branch: string
  commit: string
  environment: string
  stats: Run['stats']
}

interface BackendRunCase {
  nodeid: string
  name?: string | null
  file?: string | null
  status: string
  durationMs: number
  error?: string | null
  exchangeCount: number
}

interface BackendExchangeSummary {
  index: number
  method: string
  url: string
  status?: number | null
  elapsedMs: number
  error?: string | null
  hasRequestBody: boolean
  hasResponseBody: boolean
}

interface BackendRunCaseDetail {
  nodeid: string
  name?: string | null
  file?: string | null
  status: string
  durationMs: number
  error?: string | null
  logs: string[]
  exchanges: BackendExchangeSummary[]
}

interface BackendHeader {
  name: string
  value: string
}

interface BackendExchangeSide {
  headers: BackendHeader[]
  body?: string | null
}

interface BackendExchange {
  index: number
  method: string
  url: string
  status?: number | null
  elapsedMs: number
  request: BackendExchangeSide
  response: BackendExchangeSide & { status?: number | null }
  error?: string | null
}

interface BackendAnalysis {
  runId: string
  analyzer: string
  model: string
  generatedAt: string
  summary: string
  findingCount: number
}

interface BackendCase {
  nodeid: string
  name?: string | null
  file?: string | null
  tags?: string[]
  requirementIds?: string[]
  operationIds?: string[]
  lastRunId?: string | null
  lastStatus?: string | null
  lastDurationMs?: number | null
  lastRunAt?: string | null
}

interface BackendRequirement {
  id: string
  title: string
  version: string
  tags: string[]
  owner: string
  updatedAt: string
  contentMd: string
  operationIds: string[]
  caseNodeids: string[]
}

interface BackendOperation {
  id: string
  docId: string
  method: string
  path: string
  summary: string
  tag: string
  description: string
  params: OperationParam[]
  requestBody?: SchemaField[] | null
  responses: OperationResponse[]
  requirementIds: string[]
  caseNodeids: string[]
}

interface BackendDoc {
  id: string
  title: string
  version: string
  baseUrl: string
  updatedAt: string
  description: string
  operations: BackendOperation[]
}

interface BackendFinding {
  id: string
  runId: string
  runExternalId: string
  nodeid: string
  type: string
  title: string
  summary: string
  rootCause: string
  impact: string
  confidence: number
  suggestedSeverity: string
  exchangeIndex?: number | null
  requirementId?: string | null
  operationId?: string | null
  status: string
  note?: string | null
  judgedAt?: string | null
  defectId?: string | null
  createdAt: string
}

interface BackendRunRequest {
  id: string
  status: string
  reason: string
  specPaths: string[]
  yamlHash: string
  requestedBy?: string | null
  runExternalId?: string | null
  logPath?: string | null
  exitCode?: number | null
  error?: string | null
  createdAt: string
  startedAt?: string | null
  finishedAt?: string | null
}

interface BackendDefect {
  id: string
  title: string
  severity: string
  status: string
  findingId?: string | null
  runId?: string | null
  runExternalId?: string | null
  nodeid: string
  requirementId?: string | null
  operationId?: string | null
  exchangeIndex?: number | null
  evidenceSummary: string
  source: string
  decision: { verdict: string; note: string; at: string }
  version: number
  createdAt: string
  updatedAt: string
}

interface Page<T> {
  items: T[]
  page: number
  pageSize: number
  total: number
}

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T
const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

function readPersisted(): Persisted | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<Persisted>
    if (!Array.isArray(parsed.findings) || !Array.isArray(parsed.defects)) {
      return null
    }
    return {
      findings: parsed.findings,
      defects: parsed.defects,
    }
  } catch {
    return null
  }
}

function writePersisted(value: Persisted) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(value))
  } catch {
    // localStorage 写入失败时保持内存态可用，不阻断界面。
  }
}

function baseline(): Persisted {
  return (
    readPersisted() ?? {
      findings: clone(FINDINGS),
      defects: clone(DEFECTS),
    }
  )
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function hasToken(): boolean {
  return Boolean(getToken())
}

export function logout(): void {
  try {
    localStorage.removeItem(TOKEN_KEY)
  } catch {
    // 忽略存储不可用的场景。
  }
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  headers.set('content-type', 'application/json')
  const token = getToken()
  if (token) headers.set('authorization', `Bearer ${token}`)

  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers,
  })
  if (!response.ok) {
    let message = `请求失败：${response.status} ${response.statusText}`
    try {
      const body = (await response.json()) as {
        error?: { message?: string }
      }
      if (body.error?.message) message = body.error.message
    } catch {
      // 非 JSON 错误响应时保留默认提示。
    }
    if (response.status === 401 && !path.startsWith('/auth/login')) {
      logout()
      window.dispatchEvent(new Event('workbench:unauthorized'))
    }
    throw new Error(message)
  }
  return (await response.json()) as T
}

async function fetchAllPages<T>(
  path: string,
  pageSize = 100,
  maxPages = 20,
): Promise<T[]> {
  const items: T[] = []
  for (let page = 1; page <= maxPages; page += 1) {
    const data = await fetchJson<Page<T>>(
      `${path}?page=${page}&page_size=${pageSize}`,
    )
    items.push(...data.items)
    if (items.length >= data.total || data.items.length === 0) break
  }
  return items
}

export async function login(email: string, password: string): Promise<Session> {
  if (API_MODE !== 'http') throw new Error('当前为 Mock 模式，无需登录')
  const result = await fetchJson<LoginResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
  localStorage.setItem(TOKEN_KEY, result.accessToken)
  return { user: result.user }
}

export async function fetchSession(): Promise<Session> {
  if (API_MODE !== 'http') throw new Error('当前为 Mock 模式')
  const result = await fetchJson<{ user: BackendUser }>('/auth/me')
  return { user: result.user }
}

export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  if (API_MODE !== 'http') throw new Error('Mock 模式不支持修改密码')
  await fetchJson<{ status: string }>('/auth/change-password', {
    method: 'POST',
    body: JSON.stringify({ currentPassword, newPassword }),
  })
}

function mapProject(project: BackendProject): Project {
  return {
    id: project.id,
    key: project.key,
    name: project.name,
    repo: project.repo,
    environment: project.environment,
    owner: project.owner,
    updatedAt: project.updatedAt,
    role: project.role,
  }
}

export async function createProject(input: CreateProjectInput): Promise<Project> {
  if (API_MODE !== 'http') throw new Error('Mock 模式不支持新建项目')
  const project = await fetchJson<BackendProject>('/projects', {
    method: 'POST',
    body: JSON.stringify(input),
  })
  return mapProject(project)
}

function mapExchange(exchange: BackendExchange): Exchange {
  const status = exchange.status ?? exchange.response.status ?? 0
  return {
    index: exchange.index,
    method: exchange.method as HttpMethod,
    url: exchange.url,
    status,
    elapsedMs: exchange.elapsedMs,
    request: {
      headers: exchange.request.headers ?? [],
      body: exchange.request.body ?? '',
    },
    response: {
      status: exchange.response.status ?? status,
      headers: exchange.response.headers ?? [],
      body: exchange.response.body ?? '',
    },
    error: exchange.error ?? undefined,
  }
}

function mapRunCase(
  nodeid: string,
  detail: BackendRunCaseDetail,
  exchanges: Exchange[],
): RunCase {
  return {
    nodeid,
    status: detail.status as RunStatus,
    durationMs: detail.durationMs,
    error: detail.error ?? undefined,
    logs: detail.logs,
    exchanges,
  }
}

function mapCase(
  projectId: string,
  item: BackendCase,
  runIdByUuid: Map<string, string>,
): TestCase {
  return {
    projectId,
    nodeid: item.nodeid,
    name: item.name ?? item.nodeid.split('::').pop() ?? item.nodeid,
    file: item.file ?? item.nodeid.split('::')[0],
    tags: item.tags ?? [],
    requirementIds: item.requirementIds ?? [],
    operationIds: item.operationIds ?? [],
    lastRunId: item.lastRunId ? runIdByUuid.get(item.lastRunId) ?? '' : '',
    lastStatus: (item.lastStatus ?? 'skipped') as RunStatus,
    lastDurationMs: item.lastDurationMs ?? 0,
  }
}

function mapRequirement(projectId: string, item: BackendRequirement): Requirement {
  return {
    projectId,
    id: item.id,
    title: item.title,
    version: item.version,
    tags: item.tags,
    owner: item.owner,
    updatedAt: item.updatedAt,
    contentMd: item.contentMd,
    operationIds: item.operationIds,
    caseNodeids: item.caseNodeids,
  }
}

function mapOperation(operation: BackendOperation): Operation {
  return {
    id: operation.id,
    docId: operation.docId,
    method: operation.method as HttpMethod,
    path: operation.path,
    summary: operation.summary,
    tag: operation.tag,
    description: operation.description,
    params: operation.params ?? [],
    requestBody: operation.requestBody ?? undefined,
    responses: operation.responses ?? [],
    requirementIds: operation.requirementIds ?? [],
    caseNodeids: operation.caseNodeids ?? [],
  }
}

function mapDoc(projectId: string, doc: BackendDoc): OpenApiDoc {
  return {
    projectId,
    id: doc.id,
    title: doc.title,
    version: doc.version,
    baseUrl: doc.baseUrl,
    updatedAt: doc.updatedAt,
    description: doc.description,
    operations: (doc.operations ?? []).map(mapOperation),
  }
}

function mapFinding(projectId: string, item: BackendFinding): Finding {
  return {
    projectId,
    id: item.id,
    runId: item.runExternalId || item.runId,
    nodeid: item.nodeid,
    type: item.type as FindingType,
    title: item.title,
    summary: item.summary,
    rootCause: item.rootCause,
    impact: item.impact,
    confidence: item.confidence,
    suggestedSeverity: item.suggestedSeverity as Severity,
    exchangeIndex: item.exchangeIndex ?? undefined,
    requirementId: item.requirementId ?? undefined,
    operationId: item.operationId ?? undefined,
    status: item.status as FindingStatus,
    note: item.note ?? undefined,
    judgedAt: item.judgedAt ?? undefined,
    defectId: item.defectId ?? undefined,
    createdAt: item.createdAt,
  }
}

function mapDefect(projectId: string, item: BackendDefect): Defect {
  return {
    projectId,
    id: item.id,
    title: item.title,
    severity: item.severity as Severity,
    status: item.status as DefectStatus,
    findingId: item.findingId ?? undefined,
    runId: item.runExternalId ?? '',
    nodeid: item.nodeid,
    requirementId: item.requirementId ?? undefined,
    operationId: item.operationId ?? undefined,
    exchangeIndex: item.exchangeIndex ?? undefined,
    evidenceSummary: item.evidenceSummary,
    source: 'AI 审判',
    decision: {
      verdict: item.decision.verdict as Verdict,
      note: item.decision.note,
      at: item.decision.at,
    },
    createdAt: item.createdAt,
    updatedAt: item.updatedAt,
  }
}

function mapRunRequest(item: BackendRunRequest): RunRequest {
  return {
    id: item.id,
    status: item.status as RunRequestStatus,
    reason: item.reason,
    specPaths: item.specPaths ?? [],
    yamlHash: item.yamlHash,
    runExternalId: item.runExternalId ?? undefined,
    logPath: item.logPath ?? undefined,
    exitCode: item.exitCode ?? undefined,
    error: item.error ?? undefined,
    createdAt: item.createdAt,
    startedAt: item.startedAt ?? undefined,
    finishedAt: item.finishedAt ?? undefined,
  }
}

export interface CreateRunRequestInput {
  reason?: string
  specPaths?: string[]
}

export async function createRunRequest(
  projectId: string,
  input: CreateRunRequestInput,
): Promise<RunRequest> {
  if (API_MODE !== 'http') throw new Error('Mock 模式不支持触发运行')
  const result = await fetchJson<BackendRunRequest>(
    `/projects/${projectId}/run-requests`,
    {
      method: 'POST',
      body: JSON.stringify(input),
    },
  )
  return mapRunRequest(result)
}

export async function listRunRequests(
  projectId: string,
): Promise<RunRequest[]> {
  if (API_MODE !== 'http') throw new Error('Mock 模式不支持运行任务')
  const page = await fetchJson<Page<BackendRunRequest>>(
    `/projects/${projectId}/run-requests?page=1&page_size=10`,
  )
  return page.items.map(mapRunRequest)
}

export async function fetchRunRequest(
  projectId: string,
  id: string,
): Promise<RunRequest> {
  if (API_MODE !== 'http') throw new Error('Mock 模式不支持运行任务')
  const result = await fetchJson<BackendRunRequest>(
    `/projects/${projectId}/run-requests/${id}`,
  )
  return mapRunRequest(result)
}

async function loadProject(project: BackendProject): Promise<{
  project: Project
  requirements: Requirement[]
  openapi: OpenApiDoc[]
  cases: TestCase[]
  runs: Run[]
  findings: Finding[]
  defects: Defect[]
  summaries: Record<string, AiSummary>
}> {
  const projectId = project.id
  const [requirements, docs, cases, runs, findings, defects] = await Promise.all(
    [
      fetchJson<BackendRequirement[]>(`/projects/${projectId}/requirements`),
      fetchJson<BackendDoc[]>(`/projects/${projectId}/openapi`),
      fetchAllPages<BackendCase>(`/projects/${projectId}/cases`),
      fetchAllPages<BackendRun>(`/projects/${projectId}/runs`, 50, 5),
      fetchAllPages<BackendFinding>(`/projects/${projectId}/findings`),
      fetchAllPages<BackendDefect>(`/projects/${projectId}/defects`),
    ],
  )

  const runIdByUuid = new Map(runs.map((item) => [item.id, item.externalId]))
  const hydrated = await Promise.all(
    runs.map(async (run) => {
      const runCases = await fetchJson<BackendRunCase[]>(
        `/projects/${projectId}/runs/${run.id}/cases`,
      )
      const mappedCases = await Promise.all(
        runCases.map(async (runCase) => {
          try {
            const detail = await fetchJson<BackendRunCaseDetail>(
              `/projects/${projectId}/runs/${run.id}/cases/${runCase.nodeid}`,
            )
            const exchanges = await Promise.all(
              detail.exchanges.map(async (summary) => {
                const exchange = await fetchJson<BackendExchange>(
                  `/projects/${projectId}/runs/${run.id}/cases/${runCase.nodeid}/exchanges/${summary.index}`,
                )
                return mapExchange(exchange)
              }),
            )
            return mapRunCase(runCase.nodeid, detail, exchanges)
          } catch {
            return {
              nodeid: runCase.nodeid,
              status: runCase.status as RunStatus,
              durationMs: runCase.durationMs,
              error: runCase.error ?? undefined,
              logs: [],
              exchanges: [],
            } satisfies RunCase
          }
        }),
      )

      const mappedRun: Run = {
        projectId,
        id: run.externalId,
        startedAt: run.startedAt,
        durationMs: run.durationMs,
        environment: run.environment,
        branch: run.branch,
        commit: run.commit,
        stats: run.stats,
        cases: mappedCases,
      }

      let summary: AiSummary | undefined
      try {
        const analysis = await fetchJson<BackendAnalysis>(
          `/projects/${projectId}/runs/${run.id}/analysis`,
        )
        summary = {
          runId: run.externalId,
          text: analysis.summary,
          generatedAt: analysis.generatedAt,
          analyzer: analysis.analyzer,
          model: analysis.model,
        }
      } catch {
        summary = undefined
      }
      return { run: mappedRun, summary }
    }),
  )

  return {
    project: mapProject(project),
    requirements: requirements.map((item) => mapRequirement(projectId, item)),
    openapi: docs.map((item) => mapDoc(projectId, item)),
    cases: cases.map((item) => mapCase(projectId, item, runIdByUuid)),
    runs: hydrated.map((item) => item.run),
    findings: findings.map((item) => mapFinding(projectId, item)),
    defects: defects.map((item) => mapDefect(projectId, item)),
    summaries: Object.fromEntries(
      hydrated
        .filter(
          (item): item is { run: Run; summary: AiSummary } =>
            item.summary !== undefined,
        )
        .map((item) => [item.run.id, item.summary]),
    ),
  }
}

async function bootstrapHttp(): Promise<AppData> {
  const projects = await fetchJson<BackendProject[]>('/projects')
  const bundles = await Promise.all(projects.map(loadProject))
  return {
    projects: bundles.map((item) => item.project),
    requirements: bundles.flatMap((item) => item.requirements),
    openapi: bundles.flatMap((item) => item.openapi),
    cases: bundles.flatMap((item) => item.cases),
    runs: bundles.flatMap((item) => item.runs),
    findings: bundles.flatMap((item) => item.findings),
    defects: bundles.flatMap((item) => item.defects),
    summaries: Object.assign({}, ...bundles.map((item) => item.summaries)),
  }
}

function nextDefectId(defects: Defect[]): string {
  const max = defects.reduce((acc, item) => {
    const matched = /DEF-(\d+)/.exec(item.id)
    return matched ? Math.max(acc, Number(matched[1])) : acc
  }, 982)
  return `DEF-${String(max + 1).padStart(4, '0')}`
}

export async function bootstrap(): Promise<AppData> {
  if (API_MODE === 'http') {
    return bootstrapHttp()
  }

  await delay(320)
  const persisted = readPersisted()
  return {
    projects: clone(PROJECTS),
    requirements: clone(REQUIREMENTS),
    openapi: clone(OPENAPI_DOCS),
    cases: clone(TEST_CASES),
    runs: clone(RUNS),
    findings: persisted?.findings ?? clone(FINDINGS),
    defects: persisted?.defects ?? clone(DEFECTS),
    summaries: clone(SUMMARIES),
  }
}

export async function judgeFinding(
  projectId: string,
  id: string,
  verdict: Verdict,
  note: string,
): Promise<{ finding: Finding; defect?: Defect }> {
  if (API_MODE === 'http') {
    const result = await fetchJson<{
      finding: BackendFinding
      defect?: BackendDefect | null
    }>(`/projects/${projectId}/findings/${id}/judge`, {
      method: 'POST',
      body: JSON.stringify({ verdict, note }),
    })
    return {
      finding: mapFinding(projectId, result.finding),
      defect: result.defect ? mapDefect(projectId, result.defect) : undefined,
    }
  }

  await delay(360)
  const stored = baseline()
  const target = stored.findings.find(
    (item) => item.id === id && item.projectId === projectId,
  )
  if (!target) throw new Error('未找到该 AI 发现')

  const now = new Date().toISOString()
  const status: FindingStatus =
    verdict === 'confirm'
      ? 'confirmed'
      : verdict === 'reject'
        ? 'rejected'
        : 'false-positive'

  let defect: Defect | undefined
  if (verdict === 'confirm') {
    defect = {
      projectId: target.projectId,
      id: nextDefectId(stored.defects),
      title: target.title,
      severity: target.suggestedSeverity,
      status: 'new',
      findingId: target.id,
      runId: target.runId,
      nodeid: target.nodeid,
      requirementId: target.requirementId,
      operationId: target.operationId,
      exchangeIndex: target.exchangeIndex,
      evidenceSummary: `${target.runId} / ${target.nodeid} / 第 ${
        (target.exchangeIndex ?? 0) + 1
      } 次交换`,
      source: 'AI 审判',
      decision: { verdict, note, at: now },
      createdAt: now,
      updatedAt: now,
    }
  }

  const finding: Finding = {
    ...target,
    status,
    note,
    judgedAt: now,
    defectId: defect?.id ?? target.defectId,
  }

  writePersisted({
    ...stored,
    findings: stored.findings.map((item) => (item.id === id ? finding : item)),
    defects: defect ? [defect, ...stored.defects] : stored.defects,
  })

  return { finding, defect }
}

export async function updateDefectStatus(
  projectId: string,
  id: string,
  status: DefectStatus,
): Promise<Defect> {
  if (API_MODE === 'http') {
    const result = await fetchJson<BackendDefect>(
      `/projects/${projectId}/defects/${id}`,
      {
        method: 'PATCH',
        body: JSON.stringify({ status }),
      },
    )
    return mapDefect(projectId, result)
  }

  await delay(220)
  const stored = baseline()
  const target = stored.defects.find(
    (item) => item.id === id && item.projectId === projectId,
  )
  if (!target) throw new Error('未找到该缺陷')
  const updated: Defect = {
    ...target,
    status,
    updatedAt: new Date().toISOString(),
  }
  writePersisted({
    ...stored,
    defects: stored.defects.map((item) => (item.id === id ? updated : item)),
  })
  return updated
}

export async function resetDemoData(): Promise<AppData> {
  if (API_MODE === 'http') {
    throw new Error('真实后端模式不支持重置演示数据')
  }
  await delay(240)
  localStorage.removeItem(STORAGE_KEY)
  return bootstrap()
}

export const api = {
  bootstrap,
  login,
  fetchSession,
  hasToken,
  logout,
  changePassword,
  requiresAuth: REQUIRES_AUTH,
  createProject,
  createRunRequest,
  listRunRequests,
  fetchRunRequest,
  judgeFinding,
  updateDefectStatus,
  resetDemoData,
  listRequirements: async () => delay(120).then(() => clone(REQUIREMENTS)),
  listOpenApiDocs: async () => delay(120).then(() => clone(OPENAPI_DOCS)),
  listCases: async () => delay(120).then(() => clone(TEST_CASES)),
  listRuns: async () => delay(120).then(() => clone(RUNS)),
  listFindings: async (runId?: string) =>
    delay(120).then(() =>
      clone(FINDINGS.filter((item) => !runId || item.runId === runId)),
    ),
  listDefects: async () => delay(120).then(() => clone(DEFECTS)),
}
