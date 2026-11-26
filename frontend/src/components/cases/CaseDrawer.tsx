import type { AppData, Navigate, TestCase } from '../../types'
import { formatDateTime, formatDuration } from '../../utils/format'
import { Icon, MethodTag, RunStatusBadge } from '../ui'

export interface CaseDrawerProps {
  testCase: TestCase
  data: AppData
  navigate: Navigate
  canEdit: boolean
  onEditSpec: (path: string) => void
  onArchive: (testCase: TestCase) => void
  onRestore: (nodeid: string) => void
}

export function CaseDrawer({
  testCase,
  data,
  navigate,
  canEdit,
  onEditSpec,
  onArchive,
  onRestore,
}: CaseDrawerProps) {
  const requirements = data.requirements.filter((item) =>
    testCase.requirementIds.includes(item.id),
  )
  const operations = data.openapi
    .flatMap((item) => item.operations)
    .filter((item) => testCase.operationIds.includes(item.id))
  const run = data.runs.find((item) => item.id === testCase.lastRunId)
  const runCase = run?.cases.find((item) => item.nodeid === testCase.nodeid)

  return (
    <>
      <div
        className="drawer-scrim"
        onClick={() => navigate({ caseNodeid: '' })}
        aria-hidden="true"
      />
      <aside className="detail-drawer" aria-label="用例详情">
        <div className="drawer-head">
          <div className="drawer-heading">
            <span className="eyebrow">PYTEST CASE</span>
            <div className="drawer-title-row">
              <RunStatusBadge status={testCase.lastStatus} />
              <h2>{testCase.name}</h2>
              {testCase.archivedAt && <span className="warn-chip">已归档</span>}
            </div>
          </div>
          <button
            type="button"
            className="icon-btn"
            aria-label="关闭用例详情"
            onClick={() => navigate({ caseNodeid: '' })}
          >
            <Icon name="x" size={16} />
          </button>
        </div>

        <div className="drawer-body">
          <div className="drawer-code-block">
            <span className="drawer-label">nodeid</span>
            <code>{testCase.nodeid}</code>
          </div>

          <dl className="meta-list meta-list-wide">
            <div>
              <dt>文件</dt>
              <dd className="mono-strong">{testCase.specPath ?? testCase.file}</dd>
            </div>
            <div>
              <dt>最近运行</dt>
              <dd>
                {testCase.lastRunId} · {formatDuration(testCase.lastDurationMs)}
              </dd>
            </div>
            <div>
              <dt>标签</dt>
              <dd>
                <span className="tag-row">
                  {testCase.tags.map((tag) => (
                    <span className="tag" key={tag}>
                      {tag}
                    </span>
                  ))}
                </span>
              </dd>
            </div>
          </dl>

          <section className="drawer-section">
            <div className="rail-title">
              关联需求
              <span className="count-pill">{requirements.length}</span>
            </div>
            {requirements.length ? (
              requirements.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  className="rail-requirement rail-requirement-inline"
                  onClick={() =>
                    navigate({
                      module: 'assets',
                      assetTab: 'requirements',
                      requirementId: item.id,
                      caseNodeid: '',
                    })
                  }
                >
                  <span className="mono-id">{item.id}</span>
                  <strong>{item.title}</strong>
                  <span className="rail-requirement-version">{item.version}</span>
                </button>
              ))
            ) : (
              <div className="inline-warning">
                <Icon name="alert" size={14} />
                该用例尚未关联需求，AI 很难判断偏差。
              </div>
            )}
          </section>

          <section className="drawer-section">
            <div className="rail-title">
              关联接口
              <span className="count-pill">{operations.length}</span>
            </div>
            {operations.length ? (
              operations.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  className="rail-link"
                  onClick={() =>
                    navigate({
                      module: 'assets',
                      assetTab: 'openapi',
                      docId: item.docId,
                      operationId: item.id,
                      caseNodeid: '',
                    })
                  }
                >
                  <MethodTag method={item.method} />
                  <code>{item.path}</code>
                  <Icon name="arrowRight" size={13} />
                </button>
              ))
            ) : (
              <div className="inline-warning">
                <Icon name="alert" size={14} />
                该用例尚未关联 OpenAPI operation。
              </div>
            )}
          </section>

          {run && runCase && (
            <section className="drawer-section">
              <div className="rail-title">本次运行证据</div>
              <div className="drawer-run-card">
                <div className="drawer-run-head">
                  <span className="mono-id">{run.id}</span>
                  <RunStatusBadge status={runCase.status} />
                </div>
                <div className="drawer-run-meta">
                  {formatDateTime(run.startedAt)} · {run.environment}
                </div>
                <div className="drawer-run-stats">
                  <span>{runCase.exchangeCount} 条 HAR 交换</span>
                  <span>{formatDuration(runCase.durationMs)}</span>
                </div>
              </div>
            </section>
          )}
        </div>

        <div className="drawer-foot">
          <div className="drawer-actions">
            {canEdit && testCase.specPath && (
              <button
                type="button"
                className="btn"
                onClick={() => onEditSpec(testCase.specPath!)}
              >
                <Icon name="file" size={14} />
                编辑规格
              </button>
            )}
            {canEdit &&
              (testCase.archivedAt ? (
                <button
                  type="button"
                  className="btn"
                  onClick={() => onRestore(testCase.nodeid)}
                >
                  恢复用例
                </button>
              ) : (
                <button
                  type="button"
                  className="btn btn-danger"
                  onClick={() => onArchive(testCase)}
                >
                  归档用例
                </button>
              ))}
          </div>
          <button
            type="button"
            className="btn btn-block"
            onClick={() =>
              navigate({
                module: 'runs',
                runId: testCase.lastRunId,
                evidenceNodeid: testCase.nodeid,
                exchangeIndex: 0,
                caseNodeid: '',
              })
            }
          >
            <Icon name="play" size={14} />
            在运行证据中查看
          </button>
        </div>
      </aside>
    </>
  )
}
