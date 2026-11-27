import type {
  OperationParam,
  OperationResponse,
  ProjectToken,
  Run,
  SchemaField,
} from '../../types'

/**
 * 后端 DTO 与共享类型。
 * 仅用于 api 子模块之间的字段映射，不对外导出。
 */

export interface BackendUser {
  id: string
  email: string
  displayName: string
}

export interface LoginResponse {
  accessToken: string
  tokenType: string
  user: BackendUser
  projects: BackendProject[]
}

export interface BackendProjectEntry {
  name: string
  url: string
  note: string
}

export interface BackendProject {
  id: string
  name: string
  entries: BackendProjectEntry[]
  testRepoUrl: string
  testRepoRef: string
  updatedAt: string
  role: string
}

export interface BackendToken {
  id: string
  name: string
  prefix: string
  token?: string | null
  scopes: string[]
  status: ProjectToken['status']
  lastUsedAt?: string | null
  expiresAt?: string | null
  createdAt: string
}

export interface BackendProjectSecret {
  key: string
  description: string
  value?: string | null
  expiresAt?: string | null
  lastUsedAt?: string | null
  updatedAt: string
  expired: boolean
}

export interface BackendRun {
  id: string
  externalId: string
  startedAt: string
  durationMs: number
  branch: string
  commit: string
  environment: string
  stats: Run['stats']
}

export interface BackendRunCase {
  nodeid: string
  name?: string | null
  file?: string | null
  status: string
  durationMs: number
  error?: string | null
  exchangeCount: number
}

export interface BackendExchangeSummary {
  index: number
  method: string
  url: string
  status?: number | null
  elapsedMs: number
  error?: string | null
  hasRequestBody: boolean
  hasResponseBody: boolean
}

export interface BackendRunCaseDetail {
  nodeid: string
  name?: string | null
  file?: string | null
  status: string
  durationMs: number
  error?: string | null
  logs: string[]
  exchanges: BackendExchangeSummary[]
}

export interface BackendHeader {
  name: string
  value: string
}

export interface BackendExchangeSide {
  headers: BackendHeader[]
  body?: string | null
}

export interface BackendExchange {
  index: number
  method: string
  url: string
  status?: number | null
  elapsedMs: number
  request: BackendExchangeSide
  response: BackendExchangeSide & { status?: number | null }
  error?: string | null
}

export interface BackendAnalysis {
  runId: string
  analyzer: string
  model: string
  generatedAt: string
  summary: string
  findingCount: number
}

export interface BackendCase {
  nodeid: string
  name?: string | null
  file?: string | null
  specPath?: string | null
  framework?: string
  tags?: string[]
  requirementIds?: string[]
  operationIds?: string[]
  lastRunId?: string | null
  lastStatus?: string | null
  lastDurationMs?: number | null
  lastRunAt?: string | null
  archivedAt?: string | null
}

export interface BackendRequirement {
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

export interface BackendOperation {
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

export interface BackendDoc {
  id: string
  title: string
  version: string
  baseUrl: string
  updatedAt: string
  description: string
  operations: BackendOperation[]
}

export interface BackendFinding {
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

export interface BackendDefect {
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

export interface Page<T> {
  items: T[]
  page: number
  pageSize: number
  total: number
}
