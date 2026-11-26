import type {
  HttpMethod,
  OpenApiDoc,
  Operation,
  Requirement,
} from '../../types'
import { fetchJson, request } from './client'
import type {
  BackendDoc,
  BackendOperation,
  BackendRequirement,
} from './contracts'

/**
 * 需求、OpenAPI 契约、接口与 pytest 规格文件。
 */

export interface RequirementInput {
  externalId: string
  title?: string
  version?: string
  tags?: string[]
  owner?: string
  contentMd?: string
}

export interface OpenApiImportInput {
  externalId: string
  content: string
  title?: string
  version?: string
  baseUrl?: string
}

export interface OperationInput {
  method?: HttpMethod
  path?: string
  summary?: string
  tag?: string
  description?: string
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

export function mapRequirement(
  projectId: string,
  item: BackendRequirement,
): Requirement {
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

export function mapOperation(operation: BackendOperation): Operation {
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

export function mapDoc(projectId: string, doc: BackendDoc): OpenApiDoc {
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
