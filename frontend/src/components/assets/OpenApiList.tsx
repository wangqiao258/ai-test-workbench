import type { Navigate, OpenApiDoc, Operation } from '../../types'
import { EmptyState, Icon, MethodTag } from '../ui'

interface OpenApiListProps {
  docs: OpenApiDoc[]
  doc: OpenApiDoc
  operation: Operation
  canEdit: boolean
  opSearch: string
  onSearchChange: (value: string) => void
  opGroups: Array<[string, Operation[]]>
  navigate: Navigate
  onEditDoc: () => void
  onDeleteDoc: () => void
}

export function OpenApiList({
  docs,
  doc,
  operation,
  canEdit,
  opSearch,
  onSearchChange,
  opGroups,
  navigate,
  onEditDoc,
  onDeleteDoc,
}: OpenApiListProps) {
  return (
    <div className="asset-list">
      <div className="asset-list-head">
        <span>接口契约</span>
        <span className="count-pill">{doc.operations.length}</span>
      </div>
      <div className="doc-switch">
        {docs.map((item) => (
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
            onClick={onEditDoc}
          >
            <Icon name="file" size={13} />
            编辑文档
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-xs"
            onClick={onDeleteDoc}
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
          onChange={(event) => onSearchChange(event.target.value)}
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
  )
}
