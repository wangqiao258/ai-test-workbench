import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { APP_VERSION } from 'virtual:app-version'
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
  type CreateProjectInput,
  type ProjectBundle,
  type Session,
  type UpdateProjectInput,
} from './services/api'
import { Icon, SkeletonRows, Toast, type IconName } from './components/ui'
import { AssetsView } from './components/AssetsView'
import { CasesView } from './components/CasesView'
import { InboxView } from './components/InboxView'
import { RunTrialView } from './components/RunTrialView'
import { DefectsView } from './components/DefectsView'
import { LoginView } from './components/LoginView'
import { ChangePasswordDialog } from './components/ChangePasswordDialog'
import { CreateProjectDialog } from './components/CreateProjectDialog'
import { ProjectSettingsDialog } from './components/ProjectSettingsDialog'
import {
  ProjectSwitcher,
  type ProjectSummary,
} from './components/ProjectSwitcher'

const MODULES: Array<{
  key: ModuleKey
  label: string
  index: string
  icon: IconName
}> = [
  {
    key: 'assets',
    label: '需求与接口',
    index: '01',
    icon: 'book',
  },
  {
    key: 'cases',
    label: '用例覆盖',
    index: '02',
    icon: 'layers',
  },
  {
    key: 'inbox',
    label: '待审判',
    index: '03',
    icon: 'shield',
  },
  {
    key: 'runs',
    label: '运行证据',
    index: '04',
    icon: 'play',
  },
  {
    key: 'defects',
    label: '缺陷库',
    index: '05',
    icon: 'bug',
  },
]

const INITIAL_NAV: NavState = {
  projectId: '',
  module: 'runs',
  assetTab: 'requirements',
  requirementId: '',
  docId: '',
  operationId: '',
  caseNodeid: '',
  runId: '',
  evidenceNodeid: '',
  exchangeIndex: 0,
  findingId: '',
  defectId: '',
}

const NAV_COLLAPSED_KEY = 'ai-test-workbench:nav-collapsed'

function readNavCollapsed(): boolean {
  try {
    return localStorage.getItem(NAV_COLLAPSED_KEY) === '1'
  } catch {
    return false
  }
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
  const findings = data.findings.filter(
    (item) => item.projectId === projectId,
  )
  const finding =
    findings.find((item) => item.status === 'pending') ?? findings[0]
  const findingRun = finding
    ? runs.find((run) => run.id === finding.runId)
    : undefined
  const run = findingRun ?? runs[0]
  const fallbackCase =
    run?.cases.find(
      (item) => item.status === 'failed' || item.status === 'error',
    ) ?? run?.cases[0]
  const focusFinding =
    finding && run && finding.runId === run.id ? finding : undefined
  const defect = data.defects.find((item) => item.projectId === projectId)
  return {
    projectId,
    requirementId: requirements[0]?.id ?? '',
    docId: docs[0]?.id ?? '',
    operationId: docs[0]?.operations[0]?.id ?? '',
    caseNodeid: '',
    runId: run?.id ?? '',
    evidenceNodeid: focusFinding
      ? focusFinding.nodeid
      : fallbackCase?.nodeid ?? '',
    exchangeIndex: focusFinding ? focusFinding.exchangeIndex ?? 0 : 0,
    findingId: focusFinding?.id ?? '',
    defectId: defect?.id ?? '',
  }
}

function defaultNav(data: AppData): NavState {
  const project =
    data.projects.find((item) =>
      data.runs.some((run) => run.projectId === item.id),
    ) ?? data.projects[0]
  if (!project) return INITIAL_NAV
  const hasPending = data.findings.some(
    (item) => item.projectId === project.id && item.status === 'pending',
  )
  return {
    ...INITIAL_NAV,
    module: hasPending ? 'inbox' : 'runs',
    ...projectNavPatch(data, project.id),
  }
}

function replaceProjectItems<T extends { projectId: string }>(
  items: T[],
  projectId: string,
  fresh: T[],
): T[] {
  return [...items.filter((item) => item.projectId !== projectId), ...fresh]
}

function mergeProjectBundle(prev: AppData, bundle: ProjectBundle): AppData {
  const projectId = bundle.project.id
  return {
    projects: prev.projects.some((item) => item.id === projectId)
      ? prev.projects.map((item) =>
          item.id === projectId ? bundle.project : item,
        )
      : [...prev.projects, bundle.project],
    requirements: replaceProjectItems(
      prev.requirements,
      projectId,
      bundle.requirements,
    ),
    openapi: replaceProjectItems(prev.openapi, projectId, bundle.openapi),
    cases: replaceProjectItems(prev.cases, projectId, bundle.cases),
    runs: replaceProjectItems(prev.runs, projectId, bundle.runs),
    findings: replaceProjectItems(prev.findings, projectId, bundle.findings),
    defects: replaceProjectItems(prev.defects, projectId, bundle.defects),
    summaries: { ...prev.summaries, ...bundle.summaries },
  }
}

export default function App() {
  const [data, setData] = useState<AppData | null>(null)
  const [nav, setNav] = useState<NavState>(INITIAL_NAV)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [passwordOpen, setPasswordOpen] = useState(false)
  const [session, setSession] = useState<Session | null>(null)
  const [navCollapsed, setNavCollapsed] = useState(readNavCollapsed)
  const [authChecking, setAuthChecking] = useState(true)
  const [loginLoading, setLoginLoading] = useState(false)
  const [loginError, setLoginError] = useState('')
  const toastTimer = useRef<number | null>(null)
  const lastRefreshKey = useRef('')
  const refreshSeq = useRef(0)

  const notify = useCallback((text: string, tone: ToastTone = 'info') => {
    if (toastTimer.current) window.clearTimeout(toastTimer.current)
    setToast({ id: Date.now(), text, tone })
    toastTimer.current = window.setTimeout(() => setToast(null), 2800)
  }, [])

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        if (!api.hasToken()) {
          if (alive) setAuthChecking(false)
          return
        }
        const current = await api.fetchSession()
        if (!alive) return
        setSession(current)
        const result = await api.bootstrap()
        if (!alive) return
        const nextNav = defaultNav(result)
        lastRefreshKey.current = `${nextNav.projectId}:${nextNav.module}`
        setData(result)
        setNav(nextNav)
      } catch {
        if (!alive) return
        api.logout()
        setSession(null)
        setLoginError('无法连接后端或登录已失效，请重新登录')
      } finally {
        if (alive) setAuthChecking(false)
      }
    }
    void load()
    return () => {
      alive = false
      if (toastTimer.current) window.clearTimeout(toastTimer.current)
    }
  }, [])

  useEffect(() => {
    const handler = () => {
      setSession(null)
      setData(null)
      setNav(INITIAL_NAV)
      lastRefreshKey.current = ''
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
        const nextNav = defaultNav(result)
        lastRefreshKey.current = `${nextNav.projectId}:${nextNav.module}`
        setData(result)
        setNav(nextNav)
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
    lastRefreshKey.current = ''
    setLoginError('')
    notify('已退出登录', 'info')
  }, [notify])

  const navigate = useCallback((patch: Partial<NavState>) => {
    setNav((prev) => ({ ...prev, ...patch }))
  }, [])

  const toggleNavCollapsed = useCallback(() => {
    setNavCollapsed((value) => {
      const next = !value
      try {
        localStorage.setItem(NAV_COLLAPSED_KEY, next ? '1' : '0')
      } catch {
        // 存储不可用时只保留本次会话状态。
      }
      return next
    })
  }, [])

  const refreshProjectData = useCallback(async (projectId: string) => {
    const seq = refreshSeq.current + 1
    refreshSeq.current = seq
    try {
      const bundle = await api.refreshProject(projectId)
      if (refreshSeq.current !== seq) return
      setData((prev) => (prev ? mergeProjectBundle(prev, bundle) : prev))
    } catch {
      // 后台刷新失败时保留现有数据，不打断当前页面。
    }
  }, [])

  useEffect(() => {
    if (!nav.projectId) return
    const key = `${nav.projectId}:${nav.module}`
    if (lastRefreshKey.current === key) return
    const timer = window.setTimeout(() => {
      lastRefreshKey.current = key
      void refreshProjectData(nav.projectId)
    }, 250)
    return () => window.clearTimeout(timer)
  }, [nav.module, nav.projectId, refreshProjectData])

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
      caseCount: data.cases.filter(
        (item) => item.projectId === project.id && !item.archivedAt,
      ).length,
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
      lastRefreshKey.current = ''
      setLoginError('密码已修改，请使用新密码重新登录')
    },
    [],
  )

  const handleCreateProject = useCallback(
    async (input: CreateProjectInput) => {
      const created = await api.createProject(input)
      const fresh = await api.bootstrap()
      const nextNav = { ...INITIAL_NAV, ...projectNavPatch(fresh, created.id) }
      lastRefreshKey.current = `${nextNav.projectId}:${nextNav.module}`
      setData(fresh)
      setNav(nextNav)
      setCreateOpen(false)
      notify(`已创建项目 ${created.name}`, 'success')
    },
    [notify],
  )

  const handleAssetRefresh = useCallback(async (patch?: Partial<NavState>) => {
    const fresh = await api.bootstrap()
    setData(fresh)
    setNav((prev) => ({
      ...prev,
      ...projectNavPatch(fresh, prev.projectId),
      ...patch,
    }))
  }, [])

  const handleUpdateProject = useCallback(
    async (projectId: string, input: UpdateProjectInput) => {
      await api.updateProject(projectId, input)
      const fresh = await api.bootstrap()
      setData(fresh)
      setSettingsOpen(false)
      notify('项目资料已更新', 'success')
    },
    [notify],
  )

  const handleDeleteProject = useCallback(
    async (projectId: string) => {
      await api.deleteProject(projectId)
      const fresh = await api.bootstrap()
      const nextNav = defaultNav(fresh)
      lastRefreshKey.current = `${nextNav.projectId}:${nextNav.module}`
      setData(fresh)
      setNav(nextNav)
      setSettingsOpen(false)
      notify('项目已删除', 'info')
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

  if (authChecking) {
    return (
      <div className="login-page">
        <span className="login-hint">正在校验登录状态…</span>
      </div>
    )
  }

  if (!session) {
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
  const canEditAssets =
    activeProject?.role === 'admin' || activeProject?.role === 'tester'
  const canManageProject = activeProject?.role === 'admin'

  return (
    <div className={`app ${navCollapsed ? 'is-nav-collapsed' : ''}`}>
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
            canManage={canManageProject}
            onManage={() => setSettingsOpen(true)}
          />
        )}

        <div className="topbar-route">
          <span className="route-kicker">
            {activeProject?.name ?? '—'} / {activeMeta.index} {activeMeta.label}
          </span>
        </div>

        <div className="topbar-actions">
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
        </div>
      </header>

      <div className="app-body">
        <aside className={`sidenav ${navCollapsed ? 'is-collapsed' : ''}`}>
          <div className="nav-head">
            {!navCollapsed && <span className="nav-label">工作台</span>}
            <button
              type="button"
              className="nav-collapse"
              aria-label={navCollapsed ? '展开工作台导航' : '收起工作台导航'}
              title={navCollapsed ? '展开工作台导航' : '收起工作台导航'}
              onClick={toggleNavCollapsed}
            >
              <Icon name="panelLeft" size={15} />
            </button>
          </div>
          <nav className="nav-list">
            {MODULES.map((item) => {
              const badge =
                item.key === 'inbox'
                  ? pendingCount
                  : item.key === 'defects'
                    ? defectCount
                    : 0
              return (
                <button
                  key={item.key}
                  type="button"
                  className={`nav-item ${nav.module === item.key ? 'is-active' : ''}`}
                  aria-label={item.label}
                  title={navCollapsed ? item.label : undefined}
                  onClick={() => navigate({ module: item.key })}
                >
                  {navCollapsed ? (
                    <span className="nav-icon">
                      <Icon name={item.icon} size={17} />
                    </span>
                  ) : (
                    <>
                      <span className="nav-index">{item.index}</span>
                      <span className="nav-text">{item.label}</span>
                    </>
                  )}
                  {badge > 0 && <span className="nav-badge">{badge}</span>}
                </button>
              )
            })}
          </nav>

          <div className="nav-spacer" />

          <div className="nav-version">v{APP_VERSION}</div>
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
                <AssetsView
                  data={projectData}
                  nav={nav}
                  navigate={navigate}
                  canEdit={canEditAssets}
                  onRefresh={handleAssetRefresh}
                  onToast={notify}
                />
              )}
              {nav.module === 'cases' && (
                <CasesView
                  data={projectData}
                  nav={nav}
                  navigate={navigate}
                  onToast={notify}
                  onRefresh={handleRefresh}
                />
              )}
              {nav.module === 'inbox' && (
                <InboxView data={projectData} navigate={navigate} />
              )}
              {nav.module === 'runs' && (
                <RunTrialView
                  data={projectData}
                  nav={nav}
                  navigate={navigate}
                  onJudge={handleJudge}
                  onToast={notify}
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

      <>
        <CreateProjectDialog
          open={createOpen}
          onCancel={() => setCreateOpen(false)}
          onSubmit={handleCreateProject}
        />
        {activeProject && (
          <ProjectSettingsDialog
            open={settingsOpen}
            project={activeProject}
            onCancel={() => setSettingsOpen(false)}
            onSubmit={handleUpdateProject}
            onDelete={handleDeleteProject}
          />
        )}
        <ChangePasswordDialog
          open={passwordOpen}
          onCancel={() => setPasswordOpen(false)}
          onSubmit={handleChangePassword}
        />
      </>
    </div>
  )
}
