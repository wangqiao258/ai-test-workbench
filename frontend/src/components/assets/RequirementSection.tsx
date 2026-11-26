import type {
  Navigate,
  Operation,
  Requirement,
  TestCase,
} from '../../types'
import { formatDateTime } from '../../utils/format'
import { Icon, MethodTag, RunStatusBadge, Segmented } from '../ui'

interface RequirementSectionProps {
  requirements: Requirement[]
  requirement: Requirement
  rendered: string
  mode: 'render' | 'source'
  onModeChange: (mode: 'render' | 'source') => void
  canEdit: boolean
  linkedOperations: Operation[]
  linkedCases: TestCase[]
  navigate: Navigate
  onEdit: () => void
  onDelete: () => void
}

export function RequirementSection({
  requirements,
  requirement,
  rendered,
  mode,
  onModeChange,
  canEdit,
  linkedOperations,
  linkedCases,
  navigate,
  onEdit,
  onDelete,
}: RequirementSectionProps) {
  return (
    <div className="assets-body">
      <div className="asset-list">
        <div className="asset-list-head">
          <span>需求文档</span>
          <span className="count-pill">{requirements.length}</span>
        </div>
        <div className="asset-list-scroll">
          {requirements.map((item) => (
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
                  onClick={onEdit}
                >
                  <Icon name="file" size={13} />
                  编辑
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-xs"
                  onClick={onDelete}
                >
                  <Icon name="x" size={13} />
                  删除
                </button>
              </>
            )}
            <Segmented
              size="sm"
              value={mode}
              onChange={(value) => onModeChange(value)}
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
  )
}
