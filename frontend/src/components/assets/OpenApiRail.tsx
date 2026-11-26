import type {
  Navigate,
  OpenApiDoc,
  Requirement,
  TestCase,
} from '../../types'
import { RunStatusBadge } from '../ui'

interface OpenApiRailProps {
  doc: OpenApiDoc
  requirement?: Requirement
  cases: TestCase[]
  navigate: Navigate
}

export function OpenApiRail({
  doc,
  requirement,
  cases,
  navigate,
}: OpenApiRailProps) {
  return (
    <aside className="doc-rail">
      <section className="rail-section">
        <div className="rail-title">关联需求</div>
        {requirement ? (
          <button
            type="button"
            className="rail-requirement"
            onClick={() =>
              navigate({
                module: 'assets',
                assetTab: 'requirements',
                requirementId: requirement.id,
              })
            }
          >
            <span className="mono-id">{requirement.id}</span>
            <strong>{requirement.title}</strong>
            <span className="rail-requirement-version">
              {requirement.version}
            </span>
          </button>
        ) : (
          <p className="rail-empty">该接口尚未关联需求。</p>
        )}
      </section>

      <section className="rail-section">
        <div className="rail-title">
          关联用例
          <span className="count-pill">{cases.length}</span>
        </div>
        {cases.length ? (
          cases.map((item) => (
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
            <dt>契约服务器地址</dt>
            <dd className="mono-strong">{doc.baseUrl}</dd>
          </div>
        </dl>
      </section>
    </aside>
  )
}
