import type {
  AiSummary,
  Defect,
  DefectStatus,
  Exchange,
  Finding,
  FindingStatus,
  FindingType,
  HttpMethod,
  RunCase,
  RunStatus,
  Severity,
  TestCase,
  Verdict,
} from '../../types'
import { fetchJson } from './client'
import type {
  BackendAnalysis,
  BackendCase,
  BackendDefect,
  BackendExchange,
  BackendFinding,
  BackendRunCase,
  BackendRunCaseDetail,
} from './contracts'

/**
 * 运行、用例、证据交换、finding、defect 与分析。
 */

export function mapExchange(exchange: BackendExchange): Exchange {
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

export function mapRunCaseMeta(item: BackendRunCase): RunCase {
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

export function mapCase(
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
    framework: item.framework ?? '',
    tags: item.tags ?? [],
    requirementIds: item.requirementIds ?? [],
    operationIds: item.operationIds ?? [],
    lastRunId: item.lastRunId ? runIdByUuid.get(item.lastRunId) ?? '' : '',
    lastStatus: (item.lastStatus ?? 'skipped') as RunStatus,
    lastDurationMs: item.lastDurationMs ?? 0,
    archivedAt: item.archivedAt ?? undefined,
  }
}

export function mapFinding(
  projectId: string,
  item: BackendFinding,
): Finding {
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

export function mapDefect(projectId: string, item: BackendDefect): Defect {
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
