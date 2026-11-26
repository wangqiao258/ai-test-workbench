import type { OpenApiDoc, Operation } from '../../types'
import { formatDateTime } from '../../utils/format'
import { CopyButton, Icon, MethodTag } from '../ui'
import { SchemaTable } from './SchemaTable'

interface OperationDetailProps {
  doc: OpenApiDoc
  operation: Operation
  canEdit: boolean
  onEditOperation: () => void
}

export function OperationDetail({
  doc,
  operation,
  canEdit,
  onEditOperation,
}: OperationDetailProps) {
  return (
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
                  onClick={onEditOperation}
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
  )
}
