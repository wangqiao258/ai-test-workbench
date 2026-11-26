import type {
  Navigate,
  Operation,
  Requirement,
  RunCase,
  TestCase,
} from '../../types'
import { formatDuration } from '../../utils/format'
import { EmptyState, Icon, MethodTag, RunStatusBadge } from '../ui'
import { FRAMEWORK_LABELS } from './constants'

interface CasesTableProps {
  cases: TestCase[]
  runFilter: string
  runCaseMap: Map<string, RunCase>
  selectedRunId?: string
  requirements: Requirement[]
  operations: Operation[]
  navigate: Navigate
  onResetFilters: () => void
}

export function CasesTable({
  cases,
  runFilter,
  runCaseMap,
  selectedRunId,
  requirements,
  operations,
  navigate,
  onResetFilters,
}: CasesTableProps) {
  return (
    <div className="table-scroll">
      {cases.length ? (
        <table className="data-table">
          <thead>
            <tr>
              <th style={{ width: '31%' }}>用例</th>
              <th style={{ width: '16%' }}>关联需求</th>
              <th style={{ width: '21%' }}>关联接口</th>
              <th style={{ width: '13%' }}>状态</th>
              <th style={{ width: '9%' }}>耗时</th>
              <th style={{ width: '10%' }} />
            </tr>
          </thead>
          <tbody>
            {cases.map((testCase) => {
              const requirement = requirements.find((item) =>
                testCase.requirementIds.includes(item.id),
              )
              const operation = operations.find((item) =>
                testCase.operationIds.includes(item.id),
              )
              const runCase =
                runFilter !== 'all'
                  ? runCaseMap.get(testCase.nodeid)
                  : undefined
              const rowStatus = runCase?.status ?? testCase.lastStatus
              const rowDuration = runCase?.durationMs ?? testCase.lastDurationMs
              return (
                <tr
                  key={testCase.nodeid}
                  className={`is-clickable ${testCase.archivedAt ? 'is-archived' : ''}`}
                  onClick={() => navigate({ caseNodeid: testCase.nodeid })}
                >
                  <td>
                    <div className="case-name">{testCase.name}</div>
                    <code className="case-nodeid">{testCase.nodeid}</code>
                    {testCase.framework && (
                      <span className="framework-chip">
                        {FRAMEWORK_LABELS[testCase.framework] ??
                          testCase.framework}
                      </span>
                    )}
                    {testCase.archivedAt && (
                      <span className="warn-chip">已归档</span>
                    )}
                  </td>
                  <td>
                    {requirement ? (
                      <span className="link-chip">{requirement.id}</span>
                    ) : (
                      <span className="warn-chip">未关联</span>
                    )}
                  </td>
                  <td>
                    {operation ? (
                      <span className="op-inline">
                        <MethodTag method={operation.method} />
                        <code>{operation.path}</code>
                      </span>
                    ) : (
                      <span className="warn-chip">未关联</span>
                    )}
                  </td>
                  <td>
                    <div className="status-stack">
                      <RunStatusBadge status={rowStatus} />
                      <span className="cell-sub">
                        {runCase ? selectedRunId : testCase.lastRunId}
                      </span>
                    </div>
                  </td>
                  <td className="num-cell">{formatDuration(rowDuration)}</td>
                  <td>
                    <button
                      type="button"
                      className="icon-btn table-action"
                      aria-label="查看用例详情"
                      onClick={(event) => {
                        event.stopPropagation()
                        navigate({ caseNodeid: testCase.nodeid })
                      }}
                    >
                      <Icon name="chevronRight" size={15} />
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      ) : (
        <EmptyState
          icon="search"
          title="没有符合条件的用例"
          description="调整关键词或筛选条件后再试。"
          action={
            <button type="button" className="btn" onClick={onResetFilters}>
              清除筛选
            </button>
          }
        />
      )}
    </div>
  )
}
