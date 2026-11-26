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
  ProjectSecret,
  ProjectToken,
  Requirement,
  Run,
  RunCase,
  RunStatus,
  SchemaField,
  Severity,
  TestCase,
  Verdict,
} from '../types'

/**
 * 数据出入口：只对接真实后端。
 * 组件层只依赖 AppData，后端字段差异全部在本文件内转换。
 */
export const BASE_URL = '/api/v1'
const TOKEN_KEY = 'ai-test-workbench:token'

interface BackendUser {
  id: string
  email: string
  displayName: string
}

export interface Session {
  user: BackendUser
}

export interface CreateProjectInput {
  name: string
  baseUrl?: string
}

interface LoginResponse {
  accessToken: string
  tokenType: string
  user: BackendUser
  projects: BackendProject[]
}

interface BackendProject {
  id: string
  name: string
  baseUrl: string
  updatedAt: string
  role: string
}

interface BackendToken {
  id: string
  name: string
  prefix: string
  scopes: string[]
  status: ProjectToken['status']
  lastUsedAt?: string | null
  expiresAt?: string | null
  createdAt: string
}

export interface TokenScopeMeta {
  id: string
  label: string
  description: string
}

export interface TokenPresetMeta {
  id: string
  label: string
  hint: string
  scopes: string[]
}

export interface TokenMeta {
  scopes: TokenScopeMeta[]
  presets: TokenPresetMeta[]
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
  specPath?: string | null
  tags?: string[]
  requirementIds?: string[]
  operationIds?: string[]
  lastRunId?: string | null
  lastStatus?: string | null
  lastDurationMs?: number | null
  lastRunAt?: string | null
  archivedAt?: string | null
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

async function request(path: string, init?: RequestInit): Promise<Response> {
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
  return response
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await request(path, init)
  return (await response.json()) as T
}

async function fetchAllPages<T>(
  path: string,
  pageSize = 100,
  maxPages = 20,
): Promise<T[]> {
  const items: T[] = []
  const separator = path.includes('?') ? '&' : '?'
  for (let page = 1; page <= maxPages; page += 1) {
    const data = await fetchJson<Page<T>>(
      `${path}${separator}page=${page}&page_size=${pageSize}`,
    )
    items.push(...data.items)
    if (items.length >= data.total || data.items.length === 0) break
  }
  return items
}

export async function login(email: string, password: string): Promise<Session> {
  const result = await fetchJson<LoginResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
  localStorage.setItem(TOKEN_KEY, result.accessToken)
  return { user: result.user }
}

export async function fetchSession(): Promise<Session> {
  const result = await fetchJson<{ user: BackendUser }>('/auth/me')
  return { user: result.user }
}

export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  await fetchJson<{ status: string }>('/auth/change-password', {
    method: 'POST',
    body: JSON.stringify({ currentPassword, newPassword }),
  })
}

function mapProject(project: BackendProject): Project {
  return {
    id: project.id,
    name: project.name,
    baseUrl: project.baseUrl,
    updatedAt: project.updatedAt,
    role: project.role,
  }
}

function mapToken(token: BackendToken): ProjectToken {
  return {
    id: token.id,
    name: token.name,
    prefix: token.prefix,
    scopes: token.scopes,
    status: token.status,
    lastUsedAt: token.lastUsedAt ?? undefined,
    expiresAt: token.expiresAt ?? undefined,
    createdAt: token.createdAt,
  }
}

export interface CreateTokenInput {
  name: string
  scopes: string[]
}

export async function listProjectTokens(
  projectId: string,
): Promise<ProjectToken[]> {
  const rows = await fetchJson<BackendToken[]>(`/projects/${projectId}/tokens`)
  return rows.map(mapToken)
}

export async function fetchTokenMeta(): Promise<TokenMeta> {
  return fetchJson<TokenMeta>('/meta/token-scopes')
}

export async function createProjectToken(
  projectId: string,
  input: CreateTokenInput,
): Promise<{ token: ProjectToken; secret: string }> {
  const result = await fetchJson<BackendToken & { token: string }>(
    `/projects/${projectId}/tokens`,
    { method: 'POST', body: JSON.stringify(input) },
  )
  return { token: mapToken(result), secret: result.token }
}

export async function revokeProjectToken(
  projectId: string,
  tokenId: string,
): Promise<void> {
  await request(`/projects/${projectId}/tokens/${tokenId}`, {
    method: 'DELETE',
  })
}

export async function purgeProjectToken(
  projectId: string,
  tokenId: string,
): Promise<void> {
  await request(`/projects/${projectId}/tokens/${tokenId}/purge`, {
    method: 'POST',
  })
}

export async function purgeRevokedProjectTokens(
  projectId: string,
): Promise<{ deleted: number }> {
  return fetchJson<{ deleted: number }>(
    `/projects/${projectId}/tokens/purge-revoked`,
    { method: 'POST' },
  )
}

interface BackendProjectSecret {
  key: string
  description: string
  expiresAt?: string | null
  lastUsedAt?: string | null
  updatedAt: string
  expired: boolean
}

function mapSecret(item: BackendProjectSecret): ProjectSecret {
  return {
    key: item.key,
    description: item.description,
    expiresAt: item.expiresAt ?? undefined,
    lastUsedAt: item.lastUsedAt ?? undefined,
    updatedAt: item.updatedAt,
    expired: item.expired,
  }
}

export interface UpsertSecretInput {
  value: string
  description?: string
  expiresAt?: string | null
}

export async function listProjectSecrets(
  projectId: string,
): Promise<ProjectSecret[]> {
  const rows = await fetchJson<BackendProjectSecret[]>(
    `/projects/${projectId}/secrets`,
  )
  return rows.map(mapSecret)
}

export async function upsertProjectSecret(
  projectId: string,
  key: string,
  input: UpsertSecretInput,
): Promise<ProjectSecret> {
  const result = await fetchJson<BackendProjectSecret>(
    `/projects/${projectId}/secrets/${encodeURIComponent(key)}`,
    { method: 'PUT', body: JSON.stringify(input) },
  )
  return mapSecret(result)
}

export async function deleteProjectSecret(
  projectId: string,
  key: string,
): Promise<void> {
  await request(`/projects/${projectId}/secrets/${encodeURIComponent(key)}`, {
    method: 'DELETE',
  })
}

export async function createProject(input: CreateProjectInput): Promise<Project> {
  const project = await fetchJson<BackendProject>('/projects', {
    method: 'POST',
    body: JSON.stringify(input),
  })
  return mapProject(project)
}

export interface UpdateProjectInput {
  name?: string
  baseUrl?: string
}

export async function updateProject(
  projectId: string,
  input: UpdateProjectInput,
): Promise<Project> {
  const project = await fetchJson<BackendProject>(`/projects/${projectId}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
  return mapProject(project)
}

export async function deleteProject(projectId: string): Promise<void> {
  await request(`/projects/${projectId}`, { method: 'DELETE' })
}

export interface RequirementInput {
  externalId: string
  title?: string
  version?: string
  tags?: string[]
  owner?: string
  contentMd?: string
}

export async function upsertRequirement(
  projectId: string,
  input: RequirementInput,
): Promise<Requirement> {
  const result = await fetchJson<BackendRequirement>(
    `/projects/${projectId}/requirements`,
    { method: 'POST', body: JSON.stringify(input) },
  )
  return mapRequirement(projectId, result)
}

export async function updateRequirement(
  projectId: string,
  id: string,
  input: Partial<Omit<RequirementInput, 'externalId'>>,
): Promise<Requirement> {
  const result = await fetchJson<BackendRequirement>(
    `/projects/${projectId}/requirements/${encodeURIComponent(id)}`,
    { method: 'PATCH', body: JSON.stringify(input) },
  )
  return mapRequirement(projectId, result)
}

export async function deleteRequirement(
  projectId: string,
  id: string,
): Promise<void> {
  await request(
    `/projects/${projectId}/requirements/${encodeURIComponent(id)}`,
    { method: 'DELETE' },
  )
}

export interface OpenApiImportInput {
  externalId: string
  content: string
  title?: string
  version?: string
  baseUrl?: string
}

export async function importOpenApiDoc(
  projectId: string,
  input: OpenApiImportInput,
): Promise<OpenApiDoc> {
  const result = await fetchJson<BackendDoc>(
    `/projects/${projectId}/openapi/import`,
    { method: 'POST', body: JSON.stringify(input) },
  )
  return mapDoc(projectId, result)
}

export async function updateOpenApiDoc(
  projectId: string,
  id: string,
  input: Partial<Omit<OpenApiImportInput, 'externalId' | 'content'>> & {
    description?: string
  },
): Promise<OpenApiDoc> {
  const result = await fetchJson<BackendDoc>(
    `/projects/${projectId}/openapi/${encodeURIComponent(id)}`,
    { method: 'PATCH', body: JSON.stringify(input) },
  )
  return mapDoc(projectId, result)
}

export async function deleteOpenApiDoc(
  projectId: string,
  id: string,
): Promise<void> {
  await request(`/projects/${projectId}/openapi/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
}

export interface OperationInput {
  method?: HttpMethod
  path?: string
  summary?: string
  tag?: string
  description?: string
}

export async function updateOperation(
  projectId: string,
  id: string,
  input: OperationInput,
): Promise<Operation> {
  const result = await fetchJson<BackendOperation>(
    `/projects/${projectId}/openapi/operations/${encodeURIComponent(id)}`,
    { method: 'PATCH', body: JSON.stringify(input) },
  )
  return mapOperation(result)
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
    exchangeCount: exchanges.length,
  }
}

function mapRunCaseMeta(item: BackendRunCase): RunCase {
  return {
    nodeid: item.nodeid,
    status: item.status as RunStatus,
    durationMs: item.durationMs,
    error: item.error ?? undefined,
    logs: [],
    exchanges: [],
    exchangeCount: item.exchangeCount,
  }
}

export async function fetchRunCaseDetail(
  projectId: string,
  runId: string,
  nodeid: string,
): Promise<RunCase> {
  const detail = await fetchJson<BackendRunCaseDetail>(
    `/projects/${projectId}/runs/${runId}/cases/${nodeid}`,
  )
  const exchanges = await Promise.all(
    detail.exchanges.map(async (summary) => {
      const exchange = await fetchJson<BackendExchange>(
        `/projects/${projectId}/runs/${runId}/cases/${nodeid}/exchanges/${summary.index}`,
      )
      return mapExchange(exchange)
    }),
  )
  return mapRunCase(nodeid, detail, exchanges)
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
    specPath: item.specPath ?? undefined,
    tags: item.tags ?? [],
    requirementIds: item.requirementIds ?? [],
    operationIds: item.operationIds ?? [],
    lastRunId: item.lastRunId ? runIdByUuid.get(item.lastRunId) ?? '' : '',
    lastStatus: (item.lastStatus ?? 'skipped') as RunStatus,
    lastDurationMs: item.lastDurationMs ?? 0,
    archivedAt: item.archivedAt ?? undefined,
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

export interface SpecFile {
  path: string
  size: number
  updatedAt: string
  sha256: string
  caseCount: number
  valid: boolean
  error?: string | null
}

export interface SpecContent {
  path: string
  content: string
  sha256: string
  updatedAt: string
}

export interface SaveSpecInput {
  path: string
  content: string
  expectedSha256?: string
}

export interface SpecSaveResult {
  path: string
  sha256: string
  caseCount: number
}

export async function listSpecs(projectId: string): Promise<SpecFile[]> {
  return fetchJson<SpecFile[]>(`/projects/${projectId}/specs`)
}

export async function fetchSpecContent(
  projectId: string,
  path: string,
): Promise<SpecContent> {
  return fetchJson<SpecContent>(
    `/projects/${projectId}/specs/content?path=${encodeURIComponent(path)}`,
  )
}

export async function saveSpecContent(
  projectId: string,
  input: SaveSpecInput,
): Promise<SpecSaveResult> {
  return fetchJson<SpecSaveResult>(`/projects/${projectId}/specs/content`, {
    method: 'PUT',
    body: JSON.stringify(input),
  })
}

export async function deleteSpec(
  projectId: string,
  path: string,
): Promise<{ path: string; archivedCaseCount: number }> {
  return fetchJson(
    `/projects/${projectId}/specs?path=${encodeURIComponent(path)}`,
    { method: 'DELETE' },
  )
}

export async function setCaseArchived(
  projectId: string,
  nodeid: string,
  archived: boolean,
): Promise<{ nodeid: string; archived: boolean }> {
  return fetchJson(`/projects/${projectId}/cases`, {
    method: 'PATCH',
    body: JSON.stringify({ nodeid, archived }),
  })
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
      fetchAllPages<BackendCase>(
        `/projects/${projectId}/cases?includeArchived=true`,
      ),
      fetchAllPages<BackendRun>(`/projects/${projectId}/runs`, 50, 5),
      fetchAllPages<BackendFinding>(`/projects/${projectId}/findings`),
      fetchAllPages<BackendDefect>(`/projects/${projectId}/defects`),
    ],
  )

  const runIdByUuid = new Map(runs.map((item) => [item.id, item.externalId]))
  const hydrated = await Promise.all(
    runs.map(async (run): Promise<Run> => {
      let runCases: BackendRunCase[] = []
      try {
        runCases = await fetchJson<BackendRunCase[]>(
          `/projects/${projectId}/runs/${run.id}/cases`,
        )
      } catch {
        // 单个批次的用例读取失败时不阻塞其他批次
      }

      return {
        projectId,
        id: run.externalId,
        startedAt: run.startedAt,
        durationMs: run.durationMs,
        environment: run.environment,
        branch: run.branch,
        commit: run.commit,
        stats: run.stats,
        cases: runCases.map(mapRunCaseMeta),
      }
    }),
  )

  return {
    project: mapProject(project),
    requirements: requirements.map((item) => mapRequirement(projectId, item)),
    openapi: docs.map((item) => mapDoc(projectId, item)),
    cases: cases.map((item) => mapCase(projectId, item, runIdByUuid)),
    runs: hydrated,
    findings: findings.map((item) => mapFinding(projectId, item)),
    defects: defects.map((item) => mapDefect(projectId, item)),
    summaries: {},
  }
}

export async function fetchRunAnalysis(
  projectId: string,
  runId: string,
): Promise<AiSummary> {
  const analysis = await fetchJson<BackendAnalysis>(
    `/projects/${projectId}/runs/${runId}/analysis`,
  )
  return {
    runId,
    text: analysis.summary,
    generatedAt: analysis.generatedAt,
    analyzer: analysis.analyzer,
    model: analysis.model,
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

export async function bootstrap(): Promise<AppData> {
  return bootstrapHttp()
}

export async function judgeFinding(
  projectId: string,
  id: string,
  verdict: Verdict,
  note: string,
): Promise<{ finding: Finding; defect?: Defect }> {
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

export async function updateDefectStatus(
  projectId: string,
  id: string,
  status: DefectStatus,
): Promise<Defect> {
  const result = await fetchJson<BackendDefect>(
    `/projects/${projectId}/defects/${id}`,
    {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    },
  )
  return mapDefect(projectId, result)
}

export const api = {
  bootstrap,
  fetchRunCaseDetail,
  fetchRunAnalysis,
  login,
  fetchSession,
  hasToken,
  logout,
  changePassword,
  createProject,
  updateProject,
  deleteProject,
  listProjectTokens,
  fetchTokenMeta,
  createProjectToken,
  revokeProjectToken,
  purgeProjectToken,
  purgeRevokedProjectTokens,
  listProjectSecrets,
  upsertProjectSecret,
  deleteProjectSecret,
  upsertRequirement,
  updateRequirement,
  deleteRequirement,
  importOpenApiDoc,
  updateOpenApiDoc,
  deleteOpenApiDoc,
  updateOperation,
  listSpecs,
  fetchSpecContent,
  saveSpecContent,
  deleteSpec,
  setCaseArchived,
  judgeFinding,
  updateDefectStatus,
}
