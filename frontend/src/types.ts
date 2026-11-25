export type ModuleKey = 'assets' | 'cases' | 'runs' | 'defects'
export type AssetTab = 'requirements' | 'openapi'
export type RunStatus = 'passed' | 'failed' | 'skipped' | 'error'
export type Severity = 'blocker' | 'critical' | 'major' | 'minor'
export type DefectStatus = 'new' | 'confirmed' | 'fixing' | 'fixed' | 'closed'
export type FindingType =
  | 'regression'
  | 'spec-mismatch'
  | 'contract'
  | 'duplicate'
  | 'flaky'
export type Verdict = 'confirm' | 'reject' | 'false-positive'
export type FindingStatus = 'pending' | 'confirmed' | 'rejected' | 'false-positive'
export type HttpMethod =
  | 'GET'
  | 'POST'
  | 'PUT'
  | 'PATCH'
  | 'DELETE'
  | 'HEAD'
  | 'OPTIONS'
  | 'TRACE'
export type ToastTone = 'success' | 'info' | 'danger'

export interface Project {
  id: string
  name: string
  key: string
  repo: string
  environment: string
  owner: string
  updatedAt: string
  /** 当前用户在该项目中的角色，仅真实后端返回 */
  role?: string
}

export interface Requirement {
  projectId: string
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

export interface SchemaField {
  name: string
  type: string
  required: boolean
  description: string
}

export interface OperationParam {
  name: string
  in: 'path' | 'query' | 'header'
  type: string
  required: boolean
  description: string
}

export interface OperationResponse {
  status: number
  description: string
  fields: SchemaField[]
}

export interface Operation {
  id: string
  docId: string
  method: HttpMethod
  path: string
  summary: string
  tag: string
  description: string
  params: OperationParam[]
  requestBody?: SchemaField[]
  responses: OperationResponse[]
  requirementIds: string[]
  caseNodeids: string[]
}

export interface OpenApiDoc {
  projectId: string
  id: string
  title: string
  version: string
  baseUrl: string
  updatedAt: string
  description: string
  operations: Operation[]
}

export interface TestCase {
  projectId: string
  nodeid: string
  name: string
  file: string
  tags: string[]
  requirementIds: string[]
  operationIds: string[]
  lastRunId: string
  lastStatus: RunStatus
  lastDurationMs: number
}

export interface HarHeader {
  name: string
  value: string
}

export interface Exchange {
  index: number
  method: HttpMethod
  url: string
  status: number
  elapsedMs: number
  request: {
    headers: HarHeader[]
    body: string
  }
  response: {
    status: number
    headers: HarHeader[]
    body: string
  }
  error?: string
}

export interface RunCase {
  nodeid: string
  status: RunStatus
  durationMs: number
  error?: string
  logs: string[]
  exchanges: Exchange[]
}

export interface RunStats {
  total: number
  passed: number
  failed: number
  skipped: number
  error: number
}

export interface Run {
  projectId: string
  id: string
  startedAt: string
  durationMs: number
  environment: string
  branch: string
  commit: string
  stats: RunStats
  cases: RunCase[]
}

export type RunRequestStatus =
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'canceled'

/** Runner 任务：平台只创建任务，由独立进程拉取执行 pytest 并回传结果。 */
export interface RunRequest {
  id: string
  status: RunRequestStatus
  reason: string
  specPaths: string[]
  yamlHash: string
  runExternalId?: string
  logPath?: string
  exitCode?: number
  error?: string
  createdAt: string
  startedAt?: string
  finishedAt?: string
}

export interface Finding {
  projectId: string
  id: string
  runId: string
  nodeid: string
  type: FindingType
  title: string
  summary: string
  rootCause: string
  impact: string
  confidence: number
  suggestedSeverity: Severity
  exchangeIndex?: number
  requirementId?: string
  operationId?: string
  status: FindingStatus
  note?: string
  judgedAt?: string
  defectId?: string
  createdAt: string
}

export interface Defect {
  projectId: string
  id: string
  title: string
  severity: Severity
  status: DefectStatus
  findingId?: string
  runId: string
  nodeid: string
  requirementId?: string
  operationId?: string
  exchangeIndex?: number
  evidenceSummary: string
  source: 'AI 审判'
  decision: {
    verdict: Verdict
    note: string
    at: string
  }
  createdAt: string
  updatedAt: string
}

export interface AiSummary {
  runId: string
  text: string
  generatedAt: string
  /** 写入结果的外部流水线，例如 pytest-ai-analyzer v0.4.2 */
  analyzer: string
  /** 外部流水线使用的模型，仅用于追溯，平台不调用 */
  model: string
}

export interface AppData {
  projects: Project[]
  requirements: Requirement[]
  openapi: OpenApiDoc[]
  cases: TestCase[]
  runs: Run[]
  findings: Finding[]
  defects: Defect[]
  summaries: Record<string, AiSummary>
}

export interface NavState {
  projectId: string
  module: ModuleKey
  assetTab: AssetTab
  requirementId: string
  docId: string
  operationId: string
  caseNodeid: string
  runId: string
  evidenceNodeid: string
  exchangeIndex: number
  findingId: string
  defectId: string
}

export type Navigate = (patch: Partial<NavState>) => void
