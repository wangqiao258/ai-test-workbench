import { useMemo, useState, type ReactNode } from 'react'
import type { AppData, NavState, Navigate, ToastTone } from '../types'
import { api } from '../services/api'
import type {
  OpenApiImportInput,
  OperationInput,
  RequirementInput,
} from '../services/api'
import { renderMarkdown } from '../utils/markdown'
import { ConfirmDialog } from './ui'
import {
  DocSettingsDialog,
  OpenApiImportDialog,
  OperationDialog,
  RequirementDialog,
} from './AssetDialogs'
import { AssetsEmptyView, AssetsHeader } from './assets/AssetsShell'
import { RequirementSection } from './assets/RequirementSection'
import { OpenApiList } from './assets/OpenApiList'
import { OperationDetail } from './assets/OperationDetail'
import { OpenApiRail } from './assets/OpenApiRail'

interface Props {
  data: AppData
  nav: NavState
  navigate: Navigate
  canEdit: boolean
  onRefresh: (patch?: Partial<NavState>) => Promise<void>
  onToast: (text: string, tone?: ToastTone) => void
}

type DialogKey = 'requirement-new' | 'requirement-edit' | 'openapi-import' | 'doc-edit' | 'operation-edit'

export function AssetsView({
  data,
  nav,
  navigate,
  canEdit,
  onRefresh,
  onToast,
}: Props) {
  const [mode, setMode] = useState<'render' | 'source'>('render')
  const [opSearch, setOpSearch] = useState('')
  const [dialog, setDialog] = useState<DialogKey | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<'requirement' | 'doc' | null>(null)

  const requirement =
    data.requirements.find((item) => item.id === nav.requirementId) ??
    data.requirements[0]
  const doc =
    data.openapi.find((item) => item.id === nav.docId) ?? data.openapi[0]
  const operation = doc
    ? doc.operations.find((item) => item.id === nav.operationId) ??
      doc.operations[0]
    : undefined

  const rendered = useMemo(
    () => renderMarkdown(requirement?.contentMd ?? ''),
    [requirement],
  )

  const linkedOperations = useMemo(
    () =>
      data.openapi
        .flatMap((item) => item.operations)
        .filter((item) => requirement?.operationIds.includes(item.id)),
    [data.openapi, requirement],
  )
  const linkedCases = useMemo(
    () =>
      data.cases.filter(
        (item) =>
          !item.archivedAt && requirement?.caseNodeids.includes(item.nodeid),
      ),
    [data.cases, requirement],
  )

  const opGroups = useMemo(() => {
    if (!doc) return []
    const keyword = opSearch.trim().toLowerCase()
    const filtered = doc.operations.filter((item) => {
      if (!keyword) return true
      return `${item.path} ${item.summary} ${item.tag}`
        .toLowerCase()
        .includes(keyword)
    })
    const groups = new Map<string, typeof filtered>()
    filtered.forEach((item) => {
      groups.set(item.tag, [...(groups.get(item.tag) ?? []), item])
    })
    return Array.from(groups.entries())
  }, [doc, opSearch])

  const opRequirement = data.requirements.find((item) =>
    operation?.requirementIds.includes(item.id),
  )
  const opCases = data.cases.filter(
    (item) =>
      !item.archivedAt && operation?.caseNodeids.includes(item.nodeid),
  )
  const totalOperations = data.openapi.reduce(
    (acc, item) => acc + item.operations.length,
    0,
  )
  const hasRequirements = data.requirements.length > 0
  const hasDocs = data.openapi.length > 0

  const saveRequirement = async (input: RequirementInput) => {
    if (dialog === 'requirement-edit' && requirement) {
      await api.updateRequirement(nav.projectId, requirement.id, {
        title: input.title,
        version: input.version,
        owner: input.owner,
        tags: input.tags,
        contentMd: input.contentMd,
      })
      onToast('需求已更新', 'success')
    } else {
      await api.upsertRequirement(nav.projectId, input)
      onToast('需求已导入', 'success')
    }
    setDialog(null)
    await onRefresh({
      assetTab: 'requirements',
      requirementId: input.externalId,
    })
  }

  const removeRequirement = async () => {
    if (!requirement) return
    await api.deleteRequirement(nav.projectId, requirement.id)
    setConfirmDelete(null)
    onToast('需求已删除', 'info')
    await onRefresh({ assetTab: 'requirements' })
  }

  const importOpenApi = async (input: OpenApiImportInput) => {
    const imported = await api.importOpenApiDoc(nav.projectId, input)
    setDialog(null)
    onToast(`已导入 ${imported.operations.length} 个接口`, 'success')
    await onRefresh({
      assetTab: 'openapi',
      docId: imported.id,
      operationId: imported.operations[0]?.id ?? '',
    })
  }

  const saveDoc = async (input: {
    title?: string
    version?: string
    baseUrl?: string
    description?: string
  }) => {
    if (!doc) return
    const updated = await api.updateOpenApiDoc(nav.projectId, doc.id, input)
    setDialog(null)
    onToast('契约文档已更新', 'success')
    await onRefresh({
      assetTab: 'openapi',
      docId: updated.id,
      operationId: operation?.id ?? updated.operations[0]?.id ?? '',
    })
  }

  const removeDoc = async () => {
    if (!doc) return
    await api.deleteOpenApiDoc(nav.projectId, doc.id)
    setConfirmDelete(null)
    onToast('契约文档已删除', 'info')
    await onRefresh({ assetTab: 'openapi', docId: '', operationId: '' })
  }

  const saveOperation = async (input: OperationInput) => {
    if (!operation) return
    const updated = await api.updateOperation(
      nav.projectId,
      operation.id,
      input,
    )
    setDialog(null)
    onToast('接口已更新', 'success')
    await onRefresh({
      assetTab: 'openapi',
      docId: doc?.id ?? '',
      operationId: updated.id,
    })
  }

  const renderDialogs = () => (
    <>
      <RequirementDialog
        open={dialog === 'requirement-new' || dialog === 'requirement-edit'}
        initial={dialog === 'requirement-edit' ? requirement : null}
        onCancel={() => setDialog(null)}
        onSubmit={saveRequirement}
      />
      <OpenApiImportDialog
        open={dialog === 'openapi-import'}
        onCancel={() => setDialog(null)}
        onSubmit={importOpenApi}
      />
      <DocSettingsDialog
        open={dialog === 'doc-edit'}
        initial={doc ?? null}
        onCancel={() => setDialog(null)}
        onSubmit={saveDoc}
      />
      <OperationDialog
        open={dialog === 'operation-edit'}
        initial={operation ?? null}
        onCancel={() => setDialog(null)}
        onSubmit={saveOperation}
      />
      <ConfirmDialog
        open={confirmDelete === 'requirement'}
        title="删除这份需求？"
        description="需求正文会从项目资产中移除，已关联的用例标记将一并清理，操作不可撤销。"
        confirmText="确认删除"
        onCancel={() => setConfirmDelete(null)}
        onConfirm={() => {
          void removeRequirement()
        }}
      />
      <ConfirmDialog
        open={confirmDelete === 'doc'}
        title="删除这份契约文档？"
        description="文档及其全部接口会从项目中移除，已关联的用例标记将一并清理，操作不可撤销。"
        confirmText="确认删除"
        onCancel={() => setConfirmDelete(null)}
        onConfirm={() => {
          void removeDoc()
        }}
      />
    </>
  )

  const renderEmptyView = (
    title: string,
    description: string,
    action?: ReactNode,
  ) => (
    <AssetsEmptyView
      title={title}
      description={description}
      action={action}
      assetTab={nav.assetTab}
      canEdit={canEdit}
      hasRequirements={hasRequirements}
      hasDocs={hasDocs}
      requirementCount={data.requirements.length}
      operationCount={totalOperations}
      navigate={navigate}
      onOpenRequirement={() => setDialog('requirement-new')}
      onOpenOpenApi={() => setDialog('openapi-import')}
      dialogs={renderDialogs()}
    />
  )

  if (!hasRequirements && !hasDocs) {
    return renderEmptyView(
      '还没有需求或 OpenAPI 文档',
      '点击右上角导入需求 Markdown 或 OpenAPI 文档，导入后即可在这里查看和编辑。',
      canEdit ? (
        <div className="empty-actions">
          <button
            type="button"
            className="btn"
            onClick={() => setDialog('requirement-new')}
          >
            导入需求
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setDialog('openapi-import')}
          >
            导入 OpenAPI
          </button>
        </div>
      ) : undefined,
    )
  }

  if (nav.assetTab === 'requirements' && !requirement) {
    return renderEmptyView(
      '还没有需求文档',
      '当前项目只有接口契约。点击右上角导入需求，或切换到「接口契约」查看接口。',
      canEdit ? (
        <div className="empty-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setDialog('requirement-new')}
          >
            导入需求
          </button>
        </div>
      ) : undefined,
    )
  }

  if (nav.assetTab === 'openapi' && (!doc || !operation)) {
    return renderEmptyView(
      '还没有可查看的接口',
      '当前项目还没有接口契约。点击右上角导入 OpenAPI 文档（支持 JSON / YAML），或切换到「需求文档」。',
      canEdit ? (
        <div className="empty-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setDialog('openapi-import')}
          >
            导入 OpenAPI
          </button>
        </div>
      ) : undefined,
    )
  }

  return (
    <div className="view">
      <AssetsHeader
        assetTab={nav.assetTab}
        canEdit={canEdit}
        requirementCount={data.requirements.length}
        operationCount={totalOperations}
        docId={doc?.id ?? ''}
        operationId={operation?.id ?? ''}
        navigate={navigate}
        onOpenRequirement={() => setDialog('requirement-new')}
        onOpenOpenApi={() => setDialog('openapi-import')}
      />

      {nav.assetTab === 'requirements' ? (
        requirement ? (
          <RequirementSection
            requirements={data.requirements}
            requirement={requirement}
            rendered={rendered}
            mode={mode}
            onModeChange={(value) => setMode(value)}
            canEdit={canEdit}
            linkedOperations={linkedOperations}
            linkedCases={linkedCases}
            navigate={navigate}
            onEdit={() => setDialog('requirement-edit')}
            onDelete={() => setConfirmDelete('requirement')}
          />
        ) : null
      ) : doc && operation ? (
        <div className="assets-body">
          <OpenApiList
            docs={data.openapi}
            doc={doc}
            operation={operation}
            canEdit={canEdit}
            opSearch={opSearch}
            onSearchChange={(value) => setOpSearch(value)}
            opGroups={opGroups}
            navigate={navigate}
            onEditDoc={() => setDialog('doc-edit')}
            onDeleteDoc={() => setConfirmDelete('doc')}
          />
          <OperationDetail
            doc={doc}
            operation={operation}
            canEdit={canEdit}
            onEditOperation={() => setDialog('operation-edit')}
          />
          <OpenApiRail
            doc={doc}
            requirement={opRequirement}
            cases={opCases}
            navigate={navigate}
          />
        </div>
      ) : null}

      {renderDialogs()}
    </div>
  )
}
