import type { Project, ProjectSecret, ProjectToken } from '../../types'
import { fetchJson, request } from './client'
import type {
  BackendProject,
  BackendProjectSecret,
  BackendToken,
} from './contracts'

/**
 * 项目、访问令牌、测试凭据与 AI 规则。
 */

export interface CreateProjectInput {
  name: string
  baseUrl?: string
}

export interface UpdateProjectInput {
  name?: string
  baseUrl?: string
  testRepoUrl?: string
  testRepoRef?: string
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

export interface CreateTokenInput {
  name: string
  scopes: string[]
}

export interface UpsertSecretInput {
  value: string
  description?: string
  expiresAt?: string | null
}

export interface AgentRules {
  rules: string[]
  defaults: string[]
  isCustom: boolean
}

export function mapProject(project: BackendProject): Project {
  return {
    id: project.id,
    name: project.name,
    baseUrl: project.baseUrl,
    testRepoUrl: project.testRepoUrl ?? '',
    testRepoRef: project.testRepoRef ?? '',
    updatedAt: project.updatedAt,
    role: project.role,
  }
}

function mapToken(token: BackendToken): ProjectToken {
  return {
    id: token.id,
    name: token.name,
    prefix: token.prefix,
    token: token.token ?? null,
    scopes: token.scopes,
    status: token.status,
    lastUsedAt: token.lastUsedAt ?? undefined,
    expiresAt: token.expiresAt ?? undefined,
    createdAt: token.createdAt,
  }
}

function mapSecret(item: BackendProjectSecret): ProjectSecret {
  return {
    key: item.key,
    description: item.description,
    value: item.value ?? null,
    expiresAt: item.expiresAt ?? undefined,
    lastUsedAt: item.lastUsedAt ?? undefined,
    updatedAt: item.updatedAt,
    expired: item.expired,
  }
}

export async function createProject(
  input: CreateProjectInput,
): Promise<Project> {
  const project = await fetchJson<BackendProject>('/projects', {
    method: 'POST',
    body: JSON.stringify(input),
  })
  return mapProject(project)
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

export async function fetchAgentRules(projectId: string): Promise<AgentRules> {
  return fetchJson<AgentRules>(`/projects/${projectId}/agent-rules`)
}

export async function saveAgentRules(
  projectId: string,
  rules: string[],
): Promise<AgentRules> {
  return fetchJson<AgentRules>(`/projects/${projectId}/agent-rules`, {
    method: 'PUT',
    body: JSON.stringify({ rules }),
  })
}

export async function resetAgentRules(projectId: string): Promise<AgentRules> {
  return fetchJson<AgentRules>(`/projects/${projectId}/agent-rules`, {
    method: 'DELETE',
  })
}
