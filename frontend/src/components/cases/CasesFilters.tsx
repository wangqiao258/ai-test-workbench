import type { Operation, Requirement, Run, RunStatus } from '../../types'
import { formatDateTime } from '../../utils/format'
import { Icon } from '../ui'
import { STATUS_OPTIONS } from './constants'

interface CasesFiltersProps {
  keyword: string
  onKeywordChange: (value: string) => void
  runFilter: string
  onRunFilterChange: (value: string) => void
  requirementFilter: string
  onRequirementFilterChange: (value: string) => void
  operationFilter: string
  onOperationFilterChange: (value: string) => void
  frameworkFilter: string
  onFrameworkFilterChange: (value: string) => void
  statusFilter: 'all' | RunStatus
  onStatusFilterChange: (value: 'all' | RunStatus) => void
  includeArchived: boolean
  onIncludeArchivedChange: (value: boolean) => void
  archivedCount: number
  requirements: Requirement[]
  runs: Run[]
  operations: Operation[]
  frameworkOptions: Array<{ value: string; label: string }>
  resultCount: number
}

export function CasesFilters({
  keyword,
  onKeywordChange,
  runFilter,
  onRunFilterChange,
  requirementFilter,
  onRequirementFilterChange,
  operationFilter,
  onOperationFilterChange,
  frameworkFilter,
  onFrameworkFilterChange,
  statusFilter,
  onStatusFilterChange,
  includeArchived,
  onIncludeArchivedChange,
  archivedCount,
  requirements,
  runs,
  operations,
  frameworkOptions,
  resultCount,
}: CasesFiltersProps) {
  return (
    <div className="table-toolbar">
      <label className="search-field">
        <Icon name="search" size={14} />
        <input
          value={keyword}
          onChange={(event) => onKeywordChange(event.target.value)}
          placeholder="搜索用例名、nodeid、标签"
          aria-label="搜索用例"
        />
      </label>
      <select
        className="select"
        value={runFilter}
        onChange={(event) => onRunFilterChange(event.target.value)}
        aria-label="按轮次筛选"
      >
        <option value="all">全部轮次</option>
        {runs.map((run) => (
          <option key={run.id} value={run.id}>
            {run.id} · {formatDateTime(run.startedAt)}
          </option>
        ))}
      </select>
      <select
        className="select"
        value={requirementFilter}
        onChange={(event) => onRequirementFilterChange(event.target.value)}
        aria-label="按需求筛选"
      >
        <option value="all">全部需求</option>
        {requirements.map((item) => (
          <option key={item.id} value={item.id}>
            {item.id} · {item.title}
          </option>
        ))}
      </select>
      <select
        className="select"
        value={operationFilter}
        onChange={(event) => onOperationFilterChange(event.target.value)}
        aria-label="按接口筛选"
      >
        <option value="all">全部接口</option>
        {operations.map((item) => (
          <option key={item.id} value={item.id}>
            {item.method} {item.path}
          </option>
        ))}
      </select>
      <select
        className="select"
        value={frameworkFilter}
        onChange={(event) => onFrameworkFilterChange(event.target.value)}
        aria-label="按框架筛选"
      >
        <option value="all">全部框架</option>
        {frameworkOptions.map((item) => (
          <option key={item.value} value={item.value}>
            {item.label}
          </option>
        ))}
      </select>
      <select
        className="select"
        value={statusFilter}
        onChange={(event) =>
          onStatusFilterChange(event.target.value as 'all' | RunStatus)
        }
        aria-label="按状态筛选"
      >
        {STATUS_OPTIONS.map((item) => (
          <option key={item.value} value={item.value}>
            {item.label}
          </option>
        ))}
      </select>
      {archivedCount > 0 && (
        <label className="check-field">
          <input
            type="checkbox"
            checked={includeArchived}
            onChange={(event) => onIncludeArchivedChange(event.target.checked)}
          />
          显示已归档
        </label>
      )}
      <div className="toolbar-spacer" />
      <span className="result-count">{resultCount} 条用例</span>
    </div>
  )
}
