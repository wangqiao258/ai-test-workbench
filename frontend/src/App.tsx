import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type {
  AppData,
  DefectStatus,
  ModuleKey,
  NavState,
  ToastTone,
  Verdict,
} from './types'
import {
  api,
  API_MODE,
  REQUIRES_AUTH,
  type CreateProjectInput,
  type Session,
} from './services/api'
import {
  ConfirmDialog,
  Icon,
  SkeletonRows,
  Toast,
  type IconName,
} from './components/ui'
import { AssetsView } from './components/AssetsView'
import { CasesView } from './components/CasesView'
import { RunTrialView } from './components/RunTrialView'
import { DefectsView } from './components/DefectsView'
import { LoginView } from './components/LoginView'
import { ChangePasswordDialog } from './components/ChangePasswordDialog'
import { CreateProjectDialog } from './components/CreateProjectDialog'
import {
  ProjectSwitcher,
  type ProjectSummary,
} from './components/ProjectSwitcher'

const MODULES: Array<{
  key: ModuleKey
  label: string
  icon: IconName
  index: string
  caption: string
}> = [
  {
    key: 'assets',
    label: '需求与接口',
    icon: 'book',
    index: '01',
    caption: '阅读需求原文，核对 OpenAPI 契约',
  },
  {
    key: 'cases',
    label: '用例覆盖',
    icon: 'layers',
    index: '02',
    caption: '查看 pytest 用例与需求 / 接口的追溯关系',
  },
  {
    key: 'runs',
    label: '运行与审判',
    icon: 'play',
    index: '03',
    caption: '聚合运行结果与抓包证据，由人裁决 AI 发现',
  },
  {
    key: 'defects',
    label: '缺陷库',
    icon: 'bug',
    index: '04',
    caption: '只保留经过人工确认的缺陷与审判记录',
  },
]

const INITIAL_NAV: NavState = {
  projectId: 'shop-api',
  module: 'runs',
  assetTab: 'requirements',
  requirementId: 'REQ-ORDER-01',
  docId: 'DOC-ORDER',
  operationId: 'op-create-order',
  caseNodeid: '',
  runId: 'RUN-1124-0912',
  evidenceNodeid: 'tests/test_inventory.py::test_lock_inventory_concurrent',
  exchangeIndex: 1,
  findingId: 'FND-001',
  defectId: 'DEF-1007',
}

interface ToastState {
  id: number
  text: string
  tone: ToastTone
}

function projectNavPatch(data: AppData, projectId: string): Partial<NavState> {
  const requirements = data.requirements.filter(
    (item) => item.projectId === projectId,
  )
  const docs = data.openapi.filter((item) => item.projectId === projectId)
  const runs = data.runs.filter((item) => item.projectId === projectId)
  const run = runs[0]
  const fallbackCase =
    run?.cases.find(
      (item) => item.status === 'failed' || item.status === 'error',
    ) ?? run?.cases[0]
  const findings = data.findings.filter(
    (item) => item.projectId === projectId,
  )
  const finding =
    findings.find((item) => item.status === 'pending') ?? findings[0]
  const defect = data.defects.find((item) => item.projectId === projectId)
  return {
    projectId,
    requirementId: requirements[0]?.id ?? '',
    docId: docs[0]?.id ?? '',
    operationId: docs[0]?.operations[0]?.id ?? '',
    caseNodeid: '',
    runId: run?.id ?? '',
    evidenceNodeid: finding?.nodeid ?? fallbackCase?.nodeid ?? '',
    exchangeIndex: finding?.exchangeIndex ?? 0,
    findingId: finding?.id ?? '',
    defectId: defect?.id ?? '',
  }
}

function defaultNav(data: AppData): NavState {
  const project =
    data.projects.find((item) =>
      data.runs.some((run) => run.projectId === item.id),
    ) ?? data.projects[0]
  if (!project) return INITIAL_NAV
  return { ...INITIAL_NAV, ...projectNavPatch(data, project.id) }
}

export default function App() {
  const [data, setData] = useState<AppData | null>(null)
  const [nav, setNav] = useState<NavState>(INITIAL_NAV)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [resetOpen, setResetOpen] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [passwordOpen, setPasswordOpen] = useState(false)
  const [session, setSession] = useState<Session | null>(null)
  const [authChecking, setAuthChecking] = useState(REQUIRES_AUTH)
  const [loginLoading, setLoginLoading] = useState(false)
  const [loginError, setLoginError] = useState('')
  const toastTimer = useRef<number | null>(null)

  const notify = useCallback((text: string, tone: ToastTone = 'info') => {
    if (toastTimer.current) window.clearTimeout(toastTimer.current)
    setToast({ id: Date.now(), text, tone })
    toastTimer.current = window.setTimeout(() => setToast(null), 2800)
  }, [])

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        if (REQUIRES_AUTH) {
          if (!api.hasToken()) {
            if (alive) setAuthChecking(false)
            return
          }
          const current = await api.fetchSession()
          if (!alive) return
          setSession(current)
        }
        const result = await api.bootstrap()
        if (!alive) return
        setData(result)
        setNav(defaultNav(result))
      } catch {
        if (!alive) return
        if (REQUIRES_AUTH) {
          api.logout()
          setSession(null)
          setLoginError('无法连接后端或登录已失效，请重新登录')
        } else {
          notify('演示数据加载失败', 'danger')
        }
      } finally {
        if (alive) setAuthChecking(false)
      }
    }
    void load()
    return () => {
      alive = false
      if (toastTimer.current) window.clearTimeout(toastTimer.current)
    }
  }, [notify])

  useEffect(() => {
    const handler = () => {
      setSession(null)
      setData(null)
      setNav(INITIAL_NAV)
      setLoginError('登录已过期，请重新登录')
    }
    window.addEventListener('workbench:unauthorized', handler)
    return () => window.removeEventListener('workbench:unauthorized', handler)
  }, [])

  const handleLogin = useCallback(
    async (email: string, password: string) => {
      setLoginLoading(true)
      setLoginError('')
      try {
        const current = await api.login(email, password)
        setSession(current)
        const result = await api.bootstrap()
        setData(result)
        setNav(defaultNav(result))
      } catch (error) {
        setSession(null)
        setLoginError(error instanceof Error ? error.message : '登录失败')
      } finally {
        setLoginLoading(false)
      }
    },
    [],
  )

  const handleLogout = useCallback(() => {
    api.logout()
    setSession(null)
    setData(null)
    setNav(INITIAL_NAV)
    setLoginError('')
    notify('已退出登录', 'info')
  }, [notify])

  const navigate = useCallback((patch: Partial<NavState>) => {
    setNav((prev) => ({ ...prev, ...patch }))
  }, [])

  const projectData = useMemo<AppData | null>(() => {
    if (!data) return null
    if (
      data.projects.length > 0 &&
      !data.projects.some((item) => item.id === nav.projectId)
    ) {
      return null
    }
    const runs = data.runs.filter((item) => item.projectId === nav.projectId)
    const runIds = new Set(runs.map((item) => item.id))
    return {
      projects: data.projects,
      requirements: data.requirements.filter(
        (item) => item.projectId === nav.projectId,
      ),
      openapi: data.openapi.filter(
        (item) => item.projectId === nav.projectId,
      ),
      cases: data.cases.filter((item) => item.projectId === nav.projectId),
      runs,
      findings: data.findings.filter(
        (item) => item.projectId === nav.projectId,
      ),
      defects: data.defects.filter(
        (item) => item.projectId === nav.projectId,
      ),
      summaries: Object.fromEntries(
        Object.entries(data.summaries).filter(([runId]) => runIds.has(runId)),
      ),
    }
  }, [data, nav.projectId])

  const projectSummaries = useMemo<ProjectSummary[]>(() => {
    if (!data) return []
    return data.projects.map((project) => ({
      project,
      caseCount: data.cases.filter((item) => item.projectId === project.id)
        .length,
      pending: data.findings.filter(
        (item) => item.projectId === project.id && item.status === 'pending',
      ).length,
      openDefects: data.defects.filter(
        (item) => item.projectId === project.id && item.status !== 'closed',
      ).length,
      lastRun: data.runs.find((item) => item.projectId === project.id),
    }))
  }, [data])

  const canCreateProject =
    API_MODE === 'http' &&
    Boolean(session) &&
    (projectData?.projects.some((item) => item.role === 'admin') ?? false)

  const switchProject = useCallback(
    (projectId: string) => {
      if (!data) return
      setNav((prev) => ({ ...prev, ...projectNavPatch(data, projectId) }))
    },
    [data],
  )

  const handleChangePassword = useCallback(
    async (currentPassword: string, newPassword: string) => {
      await api.changePassword(currentPassword, newPassword)
      setPasswordOpen(false)
      api.logout()
      setSession(null)
      setData(null)
      setNav(INITIAL_NAV)
      setLoginError('密码已修改，请使用新密码重新登录')
    },
    [],
  )

  const handleCreateProject = useCallback(
    async (input: CreateProjectInput) => {
      const created = await api.createProject(input)
      const fresh = await api.bootstrap()
      setData(fresh)
      setNav({ ...INITIAL_NAV, ...projectNavPatch(fresh, created.id) })
      setCreateOpen(false)
      notify(`已创建项目 ${created.name}`, 'success')
    },
    [notify],
  )

  const handleJudge = useCallback(
    async (id: string, verdict: Verdict, note: string) => {
      const result = await api.judgeFinding(
        nav.projectId,
        id,
        verdict,
        note,
      )
      setData((prev) => {
        if (!prev) return prev
        return {
          ...prev,
          findings: prev.findings.map((item) =>
            item.id === result.finding.id ? result.finding : item,
          ),
          defects: result.defect
            ? [
                result.defect,
                ...prev.defects.filter(
                  (item) => item.id !== result.defect!.id,
                ),
              ]
            : prev.defects,
        }
      })
      if (result.defect) {
        setNav((prev) => ({ ...prev, defectId: result.defect!.id }))
        notify(`已生成或更新缺陷 ${result.defect.id}`, 'success')
      } else if (verdict === 'reject') {
        notify('已驳回该 AI 发现', 'info')
      } else {
        notify('已标记为误报', 'info')
      }
      return result
    },
    [nav.projectId, notify],
  )

  const handleRefresh = useCallback(async () => {
    const fresh = await api.bootstrap()
    setData(fresh)
    setNav((prev) => ({ ...prev, ...projectNavPatch(fresh, prev.projectId) }))
  }, [])

  const handleDefectStatus = useCallback(
    async (id: string, status: DefectStatus) => {
      try {
        const updated = await api.updateDefectStatus(
          nav.projectId,
          id,
          status,
        )
        setData((prev) =>
          prev
            ? {
                ...prev,
                defects: prev.defects.map((item) =>
                  item.id === updated.id ? updated : item,
                ),
              }
            : prev,
        )
        notify('缺陷状态已更新', 'success')
      } catch (error) {
        notify(
          error instanceof Error ? error.message : '缺陷状态更新失败',
          'danger',
        )
      }
    },
    [nav.projectId, notify],
  )

  const handleReset = useCallback(async () => {
    if (API_MODE === 'http') {
      notify('真实后端模式不支持重置演示数据', 'info')
      setResetOpen(false)
      return
    }
    const fresh = await api.resetDemoData()
    setData(fresh)
    setNav(defaultNav(fresh))
    setResetOpen(false)
    notify('演示数据已重置', 'success')
  }, [notify])

  if (REQUIRES_AUTH && authChecking) {
    return (
      <div className="login-page">
        <span className="login-hint">正在校验登录状态…</span>
      </div>
    )
  }

  if (REQUIRES_AUTH && !session) {
    return (
      <LoginView
        loading={loginLoading}
        error={loginError}
        onSubmit={handleLogin}
      />
    )
  }

  const pendingCount =
    projectData?.findings.filter((item) => item.status === 'pending').length ??
    0
  const defectCount = projectData?.defects.length ?? 0

  const activeMeta = MODULES.find((item) => item.key === nav.module) ?? MODULES[2]
  const activeProject =
    projectData?.projects.find((item) => item.id === nav.projectId) ??
    projectData?.projects[0]

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <div className="brand-copy">
            <span className="brand-title">AI 协同测试工作台</span>
            <span className="brand-sub">AI Test Workbench</span>
          </div>
        </div>

        {projectSummaries.length > 0 && (
          <ProjectSwitcher
            items={projectSummaries}
            activeId={nav.projectId}
            onSelect={switchProject}
            canCreate={canCreateProject}
            onCreate={() => setCreateOpen(true)}
          />
        )}

        <div className="topbar-route">
          <span className="route-kicker">
            {activeProject?.key ?? '—'} / {activeMeta.index} {activeMeta.label}
          </span>
          <span className="route-caption">{activeMeta.caption}</span>
        </div>

        <div className="topbar-actions">
          <span className={`mock-pill ${API_MODE === 'http' ? 'is-live' : ''}`}>
            <i />
            {API_MODE === 'http' ? 'LIVE API' : 'MOCK DATA'}
          </span>
          <span className="sync-state">
            <span className="sync-dot" />
            {activeProject
              ? `${activeProject.environment} · ${
                  API_MODE === 'http'
                    ? '真实后端已连接'
                    : 'pytest 与 HAR 已聚合'
                }`
              : 'pytest 结果与 HAR 已聚合'}
          </span>
          {session && (
            <>
              <span className="topbar-user" title={session.user.email}>
                {session.user.displayName || session.user.email}
              </span>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => setPasswordOpen(true)}
              >
                修改密码
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={handleLogout}
              >
                退出
              </button>
            </>
          )}
          {API_MODE === 'mock' && (
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => setResetOpen(true)}
            >
              <Icon name="refresh" size={14} />
              重置演示数据
            </button>
          )}
        </div>
      </header>

      <div className="app-body">
        <aside className="sidenav">
          <div className="nav-label">工作台</div>
          <nav className="nav-list">
            {MODULES.map((item) => {
              const badge =
                item.key === 'runs'
                  ? pendingCount
                  : item.key === 'defects'
                    ? defectCount
                    : 0
              return (
                <button
                  key={item.key}
                  type="button"
                  className={`nav-item ${nav.module === item.key ? 'is-active' : ''}`}
                  onClick={() => navigate({ module: item.key })}
                >
                  <span className="nav-index">{item.index}</span>
                  <span className="nav-text">{item.label}</span>
                  {badge > 0 && <span className="nav-badge">{badge}</span>}
                </button>
              )
            })}
          </nav>

          <div className="nav-spacer" />

          <div className="chain-card">
            <div className="chain-title">链路状态</div>
            <div className="chain-row">
              <span className="sync-dot" />
              <Icon name="server" size={14} />
              <span>pytest 执行器</span>
              <em>{API_MODE === 'http' ? '已接入' : 'MOCK'}</em>
            </div>
            <div className="chain-row">
              <span className="sync-dot" />
              <Icon name="file" size={14} />
              <span>AI 分析结果</span>
              <em>已落库</em>
            </div>
            <div className="chain-foot">外部写入 → 平台聚合 → 人工审判</div>
          </div>

          <div className="nav-version">
            v0.1 · {API_MODE === 'http' ? '联调模式' : '前端演示'}
          </div>
        </aside>

        <main className="content">
          {!projectData ? (
            <div className="boot-layout">
              <div className="boot-side">
                <span className="skeleton skeleton-line" style={{ width: '60%' }} />
                <span className="skeleton skeleton-line" style={{ width: '80%' }} />
                <span className="skeleton skeleton-line" style={{ width: '70%' }} />
              </div>
              <div className="boot-main">
                <SkeletonRows rows={5} />
                <SkeletonRows rows={3} />
              </div>
              <div className="boot-side">
                <span className="skeleton skeleton-line" style={{ width: '52%' }} />
                <span className="skeleton skeleton-line" style={{ width: '88%' }} />
                <span className="skeleton skeleton-line" style={{ width: '74%' }} />
              </div>
            </div>
          ) : (
            <div
              className="view-enter"
              key={`${nav.projectId}-${nav.module}`}
            >
              {nav.module === 'assets' && (
                <AssetsView data={projectData} nav={nav} navigate={navigate} />
              )}
              {nav.module === 'cases' && (
                <CasesView data={projectData} nav={nav} navigate={navigate} />
              )}
              {nav.module === 'runs' && (
                <RunTrialView
                  data={projectData}
                  nav={nav}
                  navigate={navigate}
                  onJudge={handleJudge}
                  onToast={notify}
                  onRefresh={handleRefresh}
                />
              )}
              {nav.module === 'defects' && (
                <DefectsView
                  data={projectData}
                  nav={nav}
                  navigate={navigate}
                  onStatusChange={handleDefectStatus}
                  onToast={notify}
                />
              )}
            </div>
          )}
        </main>
      </div>

      {toast && <Toast key={toast.id} text={toast.text} tone={toast.tone} />}

      {API_MODE === 'http' && (
        <>
          <CreateProjectDialog
            open={createOpen}
            onCancel={() => setCreateOpen(false)}
            onSubmit={handleCreateProject}
          />
          <ChangePasswordDialog
            open={passwordOpen}
            onCancel={() => setPasswordOpen(false)}
            onSubmit={handleChangePassword}
          />
        </>
      )}

      {API_MODE === 'mock' && (
        <ConfirmDialog
          open={resetOpen}
          title="重置演示数据？"
          description="将清除本地保存的 AI 发现、审判记录与缺陷状态，并恢复初始的 2 个项目、4 个运行批次与 6 条 AI 发现。"
          confirmText="确认重置"
          onCancel={() => setResetOpen(false)}
          onConfirm={handleReset}
        />
      )}
    </div>
  )
}
