import {
  BASE_URL,
  changePassword,
  fetchSession,
  getToken,
  hasToken,
  login,
  logout,
} from './api/client'
import {
  createProject,
  createProjectToken,
  deleteProject,
  deleteProjectSecret,
  fetchAgentRules,
  fetchTokenMeta,
  listProjectSecrets,
  listProjectTokens,
  purgeProjectToken,
  purgeRevokedProjectTokens,
  resetAgentRules,
  revokeProjectToken,
  saveAgentRules,
  updateProject,
  upsertProjectSecret,
} from './api/projects'
import {
  deleteOpenApiDoc,
  deleteRequirement,
  deleteSpec,
  fetchSpecContent,
  importOpenApiDoc,
  listSpecs,
  saveSpecContent,
  updateOpenApiDoc,
  updateOperation,
  updateRequirement,
  upsertRequirement,
} from './api/assets'
import {
  fetchRunAnalysis,
  fetchRunCaseDetail,
  judgeFinding,
  setCaseArchived,
  updateDefectStatus,
} from './api/runs'
import { bootstrap, refreshProject } from './api/workspace'

/**
 * 数据出入口门面：只对接真实后端。
 * 具体实现按域拆分在 ./api 目录，本文件保持原有公开导出不变。
 */
export { BASE_URL, getToken, hasToken, logout, login, fetchSession, changePassword }
export type { Session } from './api/client'

export {
  createProject,
  updateProject,
  deleteProject,
  fetchAgentRules,
  saveAgentRules,
  resetAgentRules,
  listProjectTokens,
  fetchTokenMeta,
  createProjectToken,
  revokeProjectToken,
  purgeProjectToken,
  purgeRevokedProjectTokens,
  listProjectSecrets,
  upsertProjectSecret,
  deleteProjectSecret,
}
export type {
  CreateProjectInput,
  UpdateProjectInput,
  TokenScopeMeta,
  TokenPresetMeta,
  TokenMeta,
  CreateTokenInput,
  UpsertSecretInput,
  AgentRules,
} from './api/projects'

export {
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
}
export type {
  RequirementInput,
  OpenApiImportInput,
  OperationInput,
  SpecFile,
  SpecContent,
  SaveSpecInput,
  SpecSaveResult,
} from './api/assets'

export {
  fetchRunCaseDetail,
  fetchRunAnalysis,
  setCaseArchived,
  judgeFinding,
  updateDefectStatus,
} from './api/runs'

export { bootstrap, refreshProject }
export type { ProjectBundle } from './api/workspace'

export const api = {
  bootstrap,
  refreshProject,
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
  fetchAgentRules,
  saveAgentRules,
  resetAgentRules,
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
