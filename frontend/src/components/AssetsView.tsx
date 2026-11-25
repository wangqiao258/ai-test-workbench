import { useMemo, useState, type ReactNode } from 'react'
import type {
  AppData,
  NavState,
  Navigate,
  SchemaField,
  ToastTone,
} from '../types'
import { api } from '../services/api'
import type {
  OpenApiImportInput,
  OperationInput,
  RequirementInput,
} from '../services/api'
import { formatDateTime } from '../utils/format'
import { renderMarkdown } from '../utils/markdown'
import {
  ConfirmDialog,
  CopyButton,
  EmptyState,
  Icon,
  MethodTag,
  RunStatusBadge,
  Segmented,
} from './ui'
import {
  DocSettingsDialog,
  OpenApiImportDialog,
  OperationDialog,
  RequirementDialog,
} from './AssetDialogs'

interface Props {
  data: AppData
  nav: NavState
  navigate: Navigate
  canEdit: boolean
  onRefresh: (patch?: Partial<NavState>) => Promise<void>
  onToast: (text: string, tone?: ToastTone) => void
}

type DialogKey = 'requirement-new' | 'requirement-edit' | 'openapi-import' | 'doc-edit' | 'operation-edit'

function SchemaTable({ fields }: { fields: SchemaField[] }) {
  if (!fields.length) {
    return <p className="muted-line">无字段定义</p>
  }
  return (
    <table className="mini-table">
      <thead>
        <tr>
          <th style={{ width: '24%' }}>字段</th>
          <th style={{ width: '18%' }}>类型</th>
          <th style={{ width: '10%' }}>必填</th>
          <th>说明</th>
        </tr>
      </thead>
      <tbody>
        {fields.map((field) => (
          <tr key={field.name}>
            <td>
              <code className="field-name">{field.name}</code>
            </td>
            <td>
              <span className="type-pill">{field.type}</span>
            </td>
            <td>
              {field.required ? (
                <span className="required-yes">是</span>
              ) : (
                <span className="required-no">否</span>
              )}
            </td>
            <td>{field.description}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

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
      data.cases.filter((item) =>
        requirement?.caseNodeids.includes(item.nodeid),
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
  const opCases = data.cases.filter((item) =>
    operation?.caseNodeids.includes(item.nodeid),
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

  const emptyView = (
    title: string,
    description: string,
    action?: ReactNode,
  ) => (
    <div className="view">
      <header className="view-head">
        <div>
          <div className="view-kicker">ASSET LIBRARY / 01</div>
          <h1 className="view-title">需求与接口</h1>
          <p className="view-desc">
            需求以 Markdown 入库，接口按 OpenAPI 结构化展示；两者与 pytest
            用例、运行结果建立追溯关系，作为 AI 判断契约偏差的依据。
          </p>
        </div>
        {(canEdit || hasRequirements || hasDocs) && (
          <div className="view-head-actions">
            {canEdit && (
              <>
                <button
                  type="button"
                  className="btn"
                  onClick={() => setDialog('requirement-new')}
                >
                  <Icon name="file" size={14} />
                  导入需求
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => setDialog('openapi-import')}
                >
                  <Icon name="plus" size={14} />
                  导入 OpenAPI
                </button>
              </>
            )}
            {(hasRequirements || hasDocs) && (
              <Segmented
                value={nav.assetTab}
                onChange={(value) => navigate({ assetTab: value })}
                options={[
                  {
                    value: 'requirements',
                    label: '需求文档',
                    count: data.requirements.length,
                  },
                  {
                    value: 'openapi',
                    label: '接口契约',
                    count: totalOperations,
                  },
                ]}
              />
            )}
          </div>
        )}
      </header>
      <div className="view-body">
        <EmptyState icon="book" title={title} description={description} action={action} />
      </div>
      {renderDialogs()}
    </div>
  )

  if (!hasRequirements && !hasDocs) {
    return emptyView(
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
    return emptyView(
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
    return emptyView(
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
      <header className="view-head">
        <div>
          <div className="view-kicker">ASSET LIBRARY / 01</div>
          <h1 className="view-title">需求与接口</h1>
          <p className="view-desc">
            需求以 Markdown 入库，接口按 OpenAPI 结构化展示；两者与 pytest
            用例、运行结果建立追溯关系，作为 AI 判断契约偏差的依据。
          </p>
        </div>
        <div className="view-head-actions">
          {canEdit && nav.assetTab === 'requirements' && (
            <button
              type="button"
              className="btn"
              onClick={() => setDialog('requirement-new')}
            >
              <Icon name="file" size={14} />
              导入需求
            </button>
          )}
          {canEdit && nav.assetTab === 'openapi' && (
            <button
              type="button"
              className="btn"
              onClick={() => setDialog('openapi-import')}
            >
              <Icon name="file" size={14} />
              导入 OpenAPI
            </button>
          )}
          <Segmented
            value={nav.assetTab}
            onChange={(value) =>
              navigate({
                assetTab: value,
                ...(value === 'openapi'
                  ? {
                      docId: doc?.id ?? '',
                      operationId: operation?.id ?? '',
                    }
                  : {}),
              })
            }
            options={[
              {
                value: 'requirements',
                label: '需求文档',
                count: data.requirements.length,
              },
              { value: 'openapi', label: '接口契约', count: totalOperations },
            ]}
          />
        </div>
      </header>

      {nav.assetTab === 'requirements' ? (
        requirement ? (
        <div className="assets-body">
          <div className="asset-list">
            <div className="asset-list-head">
              <span>需求文档</span>
              <span className="count-pill">{data.requirements.length}</span>
            </div>
            <div className="asset-list-scroll">
              {data.requirements.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={`asset-item ${
                    item.id === requirement.id ? 'is-active' : ''
                  }`}
                  onClick={() =>
                    navigate({
                      assetTab: 'requirements',
                      requirementId: item.id,
                    })
                  }
                >
                  <div className="asset-item-top">
                    <span className="mono-id">{item.id}</span>
                    <span className="asset-version">{item.version}</span>
                  </div>
                  <div className="asset-item-title">{item.title}</div>
                  <div className="asset-item-meta">
                    {item.tags.slice(0, 2).map((tag) => (
                      <span className="tag" key={tag}>
                        {tag}
                      </span>
                    ))}
                    <span className="asset-time">
                      {formatDateTime(item.updatedAt)}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </div>

          <div className="doc-pane">
            <div className="doc-toolbar">
              <div className="doc-breadcrumb">
                <span className="mono-id">{requirement.id}</span>
                <span className="dot-sep" />
                <span>{requirement.owner}</span>
                <span className="dot-sep" />
                <span>更新于 {formatDateTime(requirement.updatedAt)}</span>
              </div>
              <div className="doc-toolbar-actions">
                {canEdit && (
                  <>
                    <button
                      type="button"
                      className="btn btn-ghost btn-xs"
                      onClick={() => setDialog('requirement-edit')}
                    >
                      <Icon name="file" size={13} />
                      编辑
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost btn-xs"
                      onClick={() => setConfirmDelete('requirement')}
                    >
                      <Icon name="x" size={13} />
                      删除
                    </button>
                  </>
                )}
                <Segmented
                  size="sm"
                  value={mode}
                  onChange={(value) => setMode(value)}
                  options={[
                    { value: 'render', label: '渲染' },
                    { value: 'source', label: 'Markdown 源码' },
                  ]}
                />
              </div>
            </div>
            <div className="doc-scroll">
              <div className="doc-body">
                <div className="doc-headline">
                  <div className="doc-tags">
                    {requirement.tags.map((tag) => (
                      <span className="tag tag-strong" key={tag}>
                        {tag}
                      </span>
                    ))}
                  </div>
                  <span className="source-note">
                    {mode === 'render'
                      ? 'Markdown 渲染视图'
                      : '原始 Markdown · 入库格式'}
                  </span>
                </div>
                {mode === 'render' ? (
                  <article
                    className="md"
                    dangerouslySetInnerHTML={{ __html: rendered }}
                  />
                ) : (
                  <pre className="doc-source">
                    <code>{requirement.contentMd}</code>
                  </pre>
                )}
              </div>
            </div>
          </div>

          <aside className="doc-rail">
            <section className="rail-section">
              <div className="rail-title">
                关联接口
                <span className="count-pill">{linkedOperations.length}</span>
              </div>
              {linkedOperations.length ? (
                linkedOperations.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className="rail-link"
                    onClick={() =>
                      navigate({
                        module: 'assets',
                        assetTab: 'openapi',
                        docId: item.docId,
                        operationId: item.id,
                      })
                    }
                  >
                    <MethodTag method={item.method} />
                    <code>{item.path}</code>
                    <Icon name="arrowRight" size={13} />
                  </button>
                ))
              ) : (
                <p className="rail-empty">暂无关联接口</p>
              )}
            </section>

            <section className="rail-section">
              <div className="rail-title">
                关联用例
                <span className="count-pill">{linkedCases.length}</span>
              </div>
              {linkedCases.length ? (
                linkedCases.map((item) => (
                  <button
                    key={item.nodeid}
                    type="button"
                    className="rail-case"
                    onClick={() =>
                      navigate({ module: 'cases', caseNodeid: item.nodeid })
                    }
                  >
                    <RunStatusBadge status={item.lastStatus} />
                    <span className="rail-case-name">{item.name}</span>
                  </button>
                ))
              ) : (
                <p className="rail-empty">暂无关联用例</p>
              )}
            </section>

            <section className="rail-section">
              <div className="rail-title">归属与版本</div>
              <dl className="meta-list">
                <div>
                  <dt>负责人</dt>
                  <dd>{requirement.owner}</dd>
                </div>
                <div>
                  <dt>版本</dt>
                  <dd>{requirement.version}</dd>
                </div>
                <div>
                  <dt>更新时间</dt>
                  <dd>{formatDateTime(requirement.updatedAt)}</dd>
                </div>
              </dl>
            </section>
          </aside>
        </div>
        ) : null
      ) : doc && operation ? (
        <div className="assets-body">
          <div className="asset-list">
            <div className="asset-list-head">
              <span>接口契约</span>
              <span className="count-pill">{doc.operations.length}</span>
            </div>
            <div className="doc-switch">
              {data.openapi.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={`doc-switch-item ${
                    item.id === doc.id ? 'is-active' : ''
                  }`}
                  onClick={() =>
                    navigate({
                      docId: item.id,
                      operationId: item.operations[0]?.id ?? '',
                    })
                  }
                >
                  <span>{item.title}</span>
                  <em>{item.version}</em>
                </button>
              ))}
            </div>
            {canEdit && (
              <div className="asset-list-tools">
                <button
                  type="button"
                  className="btn btn-ghost btn-xs"
                  onClick={() => setDialog('doc-edit')}
                >
                  <Icon name="file" size={13} />
                  编辑文档
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-xs"
                  onClick={() => setConfirmDelete('doc')}
                >
                  <Icon name="x" size={13} />
                  删除文档
                </button>
              </div>
            )}
            <label className="search-field search-field-inline">
              <Icon name="search" size={14} />
              <input
                value={opSearch}
                onChange={(event) => setOpSearch(event.target.value)}
                placeholder="搜索 path / 摘要"
                aria-label="搜索接口"
              />
            </label>
            <div className="asset-list-scroll">
              {opGroups.length ? (
                opGroups.map(([tag, items]) => (
                  <div className="op-group" key={tag}>
                    <div className="op-group-title">
                      {tag || '未分组'}
                      <span>{items.length}</span>
                    </div>
                    {items.map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        className={`op-item ${
                          item.id === operation.id ? 'is-active' : ''
                        }`}
                        onClick={() =>
                          navigate({ docId: doc.id, operationId: item.id })
                        }
                      >
                        <div className="op-item-line">
                          <MethodTag method={item.method} />
                          <code>{item.path}</code>
                        </div>
                        <div className="op-item-summary">{item.summary}</div>
                      </button>
                    ))}
                  </div>
                ))
              ) : (
                <EmptyState
                  icon="search"
                  title="没有匹配的接口"
                  description="换一个 path 或摘要关键词再试。"
                />
              )}
            </div>
          </div>

          <div className="doc-pane">
            <div className="doc-scroll">
              <div className="doc-body">
                <div className="op-detail-head">
                  <div className="op-method-line">
                    <MethodTag method={operation.method} />
                    <code className="op-path-large">{operation.path}</code>
                    <CopyButton
                      text={`${operation.method} ${operation.path}`}
                      label="复制 path"
                    />
                    {canEdit && (
                      <button
                        type="button"
                        className="btn btn-ghost btn-xs"
                        onClick={() => setDialog('operation-edit')}
                      >
                        <Icon name="file" size={13} />
                        编辑接口
                      </button>
                    )}
                  </div>
                  <h1 className="op-title">{operation.summary}</h1>
                  <p className="op-desc">{operation.description}</p>
                  <div className="op-doc-meta">
                    <span>{doc.title}</span>
                    <span>{doc.version}</span>
                    <span>{doc.baseUrl}</span>
                    <span>更新于 {formatDateTime(doc.updatedAt)}</span>
                  </div>
                </div>

                <section className="doc-section">
                  <h2>
                    请求参数
                    <span className="section-count">{operation.params.length}</span>
                  </h2>
                  {operation.params.length ? (
                    <table className="mini-table">
                      <thead>
                        <tr>
                          <th>名称</th>
                          <th>位置</th>
                          <th>类型</th>
                          <th>必填</th>
                          <th>说明</th>
                        </tr>
                      </thead>
                      <tbody>
                        {operation.params.map((param) => (
                          <tr key={`${param.in}-${param.name}`}>
                            <td>
                              <code className="field-name">{param.name}</code>
                            </td>
                            <td>
                              <span className="type-pill">{param.in}</span>
                            </td>
                            <td>{param.type}</td>
                            <td>
                              {param.required ? (
                                <span className="required-yes">是</span>
                              ) : (
                                <span className="required-no">否</span>
                              )}
                            </td>
                            <td>{param.description}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <p className="muted-line">该接口没有 path / query / header 参数。</p>
                  )}
                </section>

                <section className="doc-section">
                  <h2>
                    请求体
                    <span className="section-count">
                      {operation.requestBody?.length ?? 0}
                    </span>
                  </h2>
                  <SchemaTable fields={operation.requestBody ?? []} />
                </section>

                <section className="doc-section">
                  <h2>
                    响应
                    <span className="section-count">{operation.responses.length}</span>
                  </h2>
                  <div className="response-list">
                    {operation.responses.map((response) => (
                      <div className="response-card" key={response.status}>
                        <div className="response-head">
                          <span
                            className={`status-code ${
                              response.status < 300
                                ? 'is-ok'
                                : response.status < 500
                                  ? 'is-warn'
                                  : 'is-error'
                            }`}
                          >
                            {response.status || '默认'}
                          </span>
                          <span>{response.description}</span>
                        </div>
                        <SchemaTable fields={response.fields} />
                      </div>
                    ))}
                  </div>
                </section>
              </div>
            </div>
          </div>

          <aside className="doc-rail">
            <section className="rail-section">
              <div className="rail-title">关联需求</div>
              {opRequirement ? (
                <button
                  type="button"
                  className="rail-requirement"
                  onClick={() =>
                    navigate({
                      module: 'assets',
                      assetTab: 'requirements',
                      requirementId: opRequirement.id,
                    })
                  }
                >
                  <span className="mono-id">{opRequirement.id}</span>
                  <strong>{opRequirement.title}</strong>
                  <span className="rail-requirement-version">
                    {opRequirement.version}
                  </span>
                </button>
              ) : (
                <p className="rail-empty">该接口尚未关联需求。</p>
              )}
            </section>

            <section className="rail-section">
              <div className="rail-title">
                关联用例
                <span className="count-pill">{opCases.length}</span>
              </div>
              {opCases.length ? (
                opCases.map((item) => (
                  <button
                    key={item.nodeid}
                    type="button"
                    className="rail-case"
                    onClick={() =>
                      navigate({ module: 'cases', caseNodeid: item.nodeid })
                    }
                  >
                    <RunStatusBadge status={item.lastStatus} />
                    <span className="rail-case-name">{item.name}</span>
                  </button>
                ))
              ) : (
                <p className="rail-empty">暂无用例覆盖该接口。</p>
              )}
            </section>

            <section className="rail-section">
              <div className="rail-title">契约信息</div>
              <dl className="meta-list">
                <div>
                  <dt>文档</dt>
                  <dd>{doc.title}</dd>
                </div>
                <div>
                  <dt>版本</dt>
                  <dd>{doc.version}</dd>
                </div>
                <div>
                  <dt>Base URL</dt>
                  <dd className="mono-strong">{doc.baseUrl}</dd>
                </div>
              </dl>
            </section>
          </aside>
        </div>
      ) : null}

      {renderDialogs()}
    </div>
  )
}
