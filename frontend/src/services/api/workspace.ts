import type {
  AiSummary,
  AppData,
  Defect,
  Finding,
  OpenApiDoc,
  Project,
  Requirement,
  Run,
  TestCase,
} from '../../types'
import { fetchAllPages, fetchJson } from './client'
import type {
  BackendCase,
  BackendDefect,
  BackendDoc,
  BackendFinding,
  BackendProject,
  BackendRequirement,
  BackendRun,
  BackendRunCase,
} from './contracts'
import { mapDoc, mapRequirement } from './assets'
import { mapProject } from './projects'
import {
  mapCase,
  mapDefect,
  mapFinding,
  mapRunCaseMeta,
} from './runs'

/**
 * 工作区初始化：拉取全部项目及其需求、契约、用例、运行、finding 与 defect。
 */

export interface ProjectBundle {
  project: Project
  requirements: Requirement[]
  openapi: OpenApiDoc[]
  cases: TestCase[]
  runs: Run[]
  findings: Finding[]
  defects: Defect[]
  summaries: Record<string, AiSummary>
}

async function loadProject(project: BackendProject): Promise<ProjectBundle> {
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

/** 切页时只刷新当前项目，避免重新拉取全部项目。 */
export async function refreshProject(projectId: string): Promise<ProjectBundle> {
  const projects = await fetchJson<BackendProject[]>('/projects')
  const project = projects.find((item) => item.id === projectId)
  if (!project) {
    throw new Error('项目不存在或无权访问')
  }
  return loadProject(project)
}
