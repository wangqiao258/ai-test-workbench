import { useMemo, useState } from 'react'
import type {
  AppData,
  Navigate,
  NavState,
  RunStatus,
  TestCase,
  ToastTone,
} from '../types'
import { api } from '../services/api'
import { percent } from '../utils/format'
import { ConfirmDialog } from './ui'
import { SpecEditorDialog } from './SpecEditorDialog'
import { StatCard } from './cases/StatCard'
import { CaseDrawer } from './cases/CaseDrawer'
import { CasesFilters } from './cases/CasesFilters'
import { CasesTable } from './cases/CasesTable'
import { FRAMEWORK_LABELS } from './cases/constants'

interface Props {
  data: AppData
  nav: NavState
  navigate: Navigate
  onToast: (text: string, tone?: ToastTone) => void
  onRefresh: () => Promise<void>
}

export function CasesView({ data, nav, navigate, onToast, onRefresh }: Props) {
  const [keyword, setKeyword] = useState('')
  const [requirementFilter, setRequirementFilter] = useState('all')
  const [operationFilter, setOperationFilter] = useState('all')
  const [frameworkFilter, setFrameworkFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState<'all' | RunStatus>('all')
  const [runFilter, setRunFilter] = useState('all')
  const [includeArchived, setIncludeArchived] = useState(false)
  const [specEditor, setSpecEditor] = useState<{ open: boolean; path: string }>({
    open: false,
    path: '',
  })
  const [archiveTarget, setArchiveTarget] = useState<TestCase | null>(null)

  const project = data.projects.find((item) => item.id === nav.projectId)
  const canEdit = project?.role === 'admin' || project?.role === 'tester'
  const activeCases = useMemo(
    () => data.cases.filter((item) => !item.archivedAt),
    [data.cases],
  )
  const archivedCount = data.cases.length - activeCases.length

  const frameworkOptions = useMemo(() => {
    const values = [
      ...new Set(activeCases.map((item) => item.framework).filter(Boolean)),
    ]
    return values
      .sort()
      .map((value) => ({ value, label: FRAMEWORK_LABELS[value] ?? value }))
  }, [activeCases])

  const allOperations = useMemo(
    () => data.openapi.flatMap((item) => item.operations),
    [data.openapi],
  )

  const requirementsCovered = data.requirements.filter((requirement) =>
    activeCases.some((testCase) =>
      testCase.requirementIds.includes(requirement.id),
    ),
  ).length
  const operationsCovered = allOperations.filter((operation) =>
    activeCases.some((testCase) => testCase.operationIds.includes(operation.id)),
  ).length
  const latestRun = data.runs[0]
  const executed = latestRun
    ? latestRun.stats.passed + latestRun.stats.failed + latestRun.stats.error
    : 0
  const passRate = executed ? latestRun.stats.passed / executed : 0
  const requirementCoverage = data.requirements.length
    ? requirementsCovered / data.requirements.length
    : 0
  const operationCoverage = allOperations.length
    ? operationsCovered / allOperations.length
    : 0
  const unlinkedOperationCases = activeCases.filter(
    (item) => item.operationIds.length === 0,
  ).length

  const selectedRun = data.runs.find((item) => item.id === runFilter)
  const runCaseMap = useMemo(
    () => new Map((selectedRun?.cases ?? []).map((item) => [item.nodeid, item])),
    [selectedRun],
  )

  const filtered = useMemo(() => {
    const pool = includeArchived ? data.cases : activeCases
    const lower = keyword.trim().toLowerCase()
    return pool.filter((testCase) => {
      if (runFilter !== 'all' && !runCaseMap.has(testCase.nodeid)) {
        return false
      }
      if (
        lower &&
        !`${testCase.nodeid} ${testCase.name} ${testCase.tags.join(' ')}`
          .toLowerCase()
          .includes(lower)
      ) {
        return false
      }
      if (
        requirementFilter !== 'all' &&
        !testCase.requirementIds.includes(requirementFilter)
      ) {
        return false
      }
      if (
        operationFilter !== 'all' &&
        !testCase.operationIds.includes(operationFilter)
      ) {
        return false
      }
      if (
        frameworkFilter !== 'all' &&
        testCase.framework !== frameworkFilter
      ) {
        return false
      }
      const caseStatus =
        runFilter !== 'all'
          ? runCaseMap.get(testCase.nodeid)?.status
          : testCase.lastStatus
      if (statusFilter !== 'all' && caseStatus !== statusFilter) {
        return false
      }
      return true
    })
  }, [
    activeCases,
    data.cases,
    frameworkFilter,
    includeArchived,
    keyword,
    operationFilter,
    requirementFilter,
    runCaseMap,
    runFilter,
    statusFilter,
  ])

  const selectedCase = nav.caseNodeid
    ? data.cases.find((item) => item.nodeid === nav.caseNodeid)
    : undefined

  const handleArchive = async () => {
    if (!archiveTarget) return
    try {
      await api.setCaseArchived(nav.projectId, archiveTarget.nodeid, true)
      setArchiveTarget(null)
      onToast('用例已归档，可随时恢复', 'success')
      await onRefresh()
    } catch (err) {
      onToast(err instanceof Error ? err.message : '归档失败', 'danger')
    }
  }

  const handleRestore = async (nodeid: string) => {
    try {
      await api.setCaseArchived(nav.projectId, nodeid, false)
      onToast('用例已恢复', 'success')
      await onRefresh()
    } catch (err) {
      onToast(err instanceof Error ? err.message : '恢复失败', 'danger')
    }
  }

  const handleSpecSaved = async (message: string) => {
    setSpecEditor({ open: false, path: '' })
    onToast(message, 'success')
    await onRefresh()
  }

  return (
    <div className="view">
      <header className="view-head">
        <div>
          <div className="view-kicker">COVERAGE / 02</div>
          <h1 className="view-title">用例覆盖</h1>
          <p className="view-desc">
            用例定义来自 Git 与项目规格文件；运行结果、需求与接口关联自动回填。
          </p>
        </div>
      </header>

      <div className="view-body cases-body">
        <div className="stat-grid">
          <StatCard
            label="用例总数"
            value={String(activeCases.length)}
            hint={
              archivedCount
                ? `${unlinkedOperationCases} 条未关联接口 · ${archivedCount} 条已归档`
                : `${unlinkedOperationCases} 条未关联接口`
            }
            icon="layers"
          />
          <StatCard
            label="需求覆盖"
            value={`${requirementsCovered} / ${data.requirements.length}`}
            hint={percent(requirementCoverage)}
            progress={requirementCoverage}
            icon="book"
          />
          <StatCard
            label="接口覆盖"
            value={`${operationsCovered} / ${allOperations.length}`}
            hint={`${allOperations.length - operationsCovered} 个 operation 未被覆盖`}
            progress={operationCoverage}
            icon="server"
          />
          <StatCard
            label="最近通过率"
            value={percent(passRate)}
            hint={
              latestRun
                ? `${latestRun.id} · ${latestRun.stats.passed} 通过 / ${executed} 执行`
                : '暂无运行记录'
            }
            progress={passRate}
            icon="shield"
          />
        </div>

        <div className="table-card">
          <CasesFilters
            keyword={keyword}
            onKeywordChange={setKeyword}
            runFilter={runFilter}
            onRunFilterChange={setRunFilter}
            requirementFilter={requirementFilter}
            onRequirementFilterChange={setRequirementFilter}
            operationFilter={operationFilter}
            onOperationFilterChange={setOperationFilter}
            frameworkFilter={frameworkFilter}
            onFrameworkFilterChange={setFrameworkFilter}
            statusFilter={statusFilter}
            onStatusFilterChange={setStatusFilter}
            includeArchived={includeArchived}
            onIncludeArchivedChange={setIncludeArchived}
            archivedCount={archivedCount}
            requirements={data.requirements}
            runs={data.runs}
            operations={allOperations}
            frameworkOptions={frameworkOptions}
            resultCount={filtered.length}
          />

          <CasesTable
            cases={filtered}
            runFilter={runFilter}
            runCaseMap={runCaseMap}
            selectedRunId={selectedRun?.id}
            requirements={data.requirements}
            operations={allOperations}
            navigate={navigate}
            onResetFilters={() => {
              setKeyword('')
              setRequirementFilter('all')
              setOperationFilter('all')
              setStatusFilter('all')
              setRunFilter('all')
            }}
          />
        </div>
      </div>

      {selectedCase && (
        <CaseDrawer
          testCase={selectedCase}
          data={data}
          navigate={navigate}
          canEdit={canEdit}
          onEditSpec={(path) => setSpecEditor({ open: true, path })}
          onArchive={(testCase) => setArchiveTarget(testCase)}
          onRestore={handleRestore}
        />
      )}

      <SpecEditorDialog
        open={specEditor.open}
        projectId={nav.projectId}
        path={specEditor.path}
        onCancel={() => setSpecEditor({ open: false, path: '' })}
        onSaved={handleSpecSaved}
      />

      <ConfirmDialog
        open={Boolean(archiveTarget)}
        title="归档用例"
        description={`归档「${archiveTarget?.name ?? ''}」后，默认不再执行；可随时恢复。`}
        confirmText="归档"
        onCancel={() => setArchiveTarget(null)}
        onConfirm={handleArchive}
      />
    </div>
  )
}
