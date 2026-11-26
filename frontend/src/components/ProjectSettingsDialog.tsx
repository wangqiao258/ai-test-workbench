import { useEffect, useState } from 'react'
import type { Project } from '../types'
import type { UpdateProjectInput } from '../services/api'
import { ProjectTokensSection } from './ProjectTokensSection'
import { ProjectSecretsSection } from './ProjectSecretsSection'
import { ProjectAgentRulesSection } from './ProjectAgentRulesSection'
import { DialogShell } from './ui'

interface Props {
  open: boolean
  project: Project
  onCancel: () => void
  onSubmit: (projectId: string, input: UpdateProjectInput) => Promise<void>
  onDelete: (projectId: string) => Promise<void>
}

type SettingsTab = 'basic' | 'rules' | 'tokens' | 'secrets' | 'danger'

const TABS: { id: SettingsTab; label: string }[] = [
  { id: 'basic', label: '基本资料' },
  { id: 'rules', label: 'AI 规则' },
  { id: 'tokens', label: '接入令牌' },
  { id: 'secrets', label: '测试凭据' },
  { id: 'danger', label: '危险操作' },
]

export function ProjectSettingsDialog({
  open,
  project,
  onCancel,
  onSubmit,
  onDelete,
}: Props) {
  const [tab, setTab] = useState<SettingsTab>('basic')
  const [name, setName] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [testRepoUrl, setTestRepoUrl] = useState('')
  const [testRepoRef, setTestRepoRef] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  useEffect(() => {
    if (!open) return
    setTab('basic')
    setName(project.name)
    setBaseUrl(project.baseUrl)
    setTestRepoUrl(project.testRepoUrl ?? '')
    setTestRepoRef(project.testRepoRef ?? '')
    setError('')
    setBusy(false)
    setConfirmDelete(false)
  }, [open, project])

  const switchTab = (next: SettingsTab) => {
    setTab(next)
    setError('')
    setConfirmDelete(false)
  }

  const submit = async () => {
    if (busy) return
    if (!name.trim()) {
      setError('项目名称不能为空')
      return
    }
    setBusy(true)
    setError('')
    try {
      await onSubmit(project.id, {
        name: name.trim(),
        baseUrl: baseUrl.trim(),
        testRepoUrl: testRepoUrl.trim(),
        testRepoRef: testRepoRef.trim(),
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存项目失败')
      setBusy(false)
    }
  }

  const remove = async () => {
    if (busy) return
    if (!confirmDelete) {
      setConfirmDelete(true)
      return
    }
    setBusy(true)
    setError('')
    try {
      await onDelete(project.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除项目失败')
      setBusy(false)
      setConfirmDelete(false)
    }
  }

  const footer =
    tab === 'basic' ? (
      <div className="dialog-actions">
        <button type="button" className="btn" onClick={onCancel} disabled={busy}>
          取消
        </button>
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? '保存中…' : '保存修改'}
        </button>
      </div>
    ) : tab === 'danger' ? (
      <div className="dialog-actions dialog-actions-split">
        <button
          type="button"
          className="btn btn-danger"
          onClick={remove}
          disabled={busy}
        >
          {confirmDelete ? '确认删除' : '删除项目'}
        </button>
        <div className="dialog-actions-group">
          <button type="button" className="btn" onClick={onCancel} disabled={busy}>
            关闭
          </button>
        </div>
      </div>
    ) : (
      <div className="dialog-actions">
        <button type="button" className="btn" onClick={onCancel} disabled={busy}>
          关闭
        </button>
      </div>
    )

  return (
    <DialogShell
      open={open}
      title="项目设置"
      description="维护项目资料与测试仓库，管理 AI 规则、接入令牌与测试凭据；删除项目会一并移除其需求、接口、运行与缺陷。"
      icon="server"
      className="dialog-project dialog-settings"
      busy={busy}
      busyText="保存中…"
      error={error}
      submitText="保存修改"
      canSubmit={tab === 'basic'}
      onCancel={onCancel}
      onSubmit={submit}
      footer={footer}
    >
      <div className="settings-tabs" role="tablist" aria-label="项目设置分区">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            className={`settings-tab ${tab === item.id ? 'is-active' : ''}`}
            onClick={() => switchTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="settings-panel">
        {tab === 'basic' && (
          <div className="form-grid">
            <label className="form-field form-field-wide">
              <span>项目名称 *</span>
              <input
                autoFocus
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <label className="form-field form-field-wide">
              <span>被测服务地址</span>
              <input
                value={baseUrl}
                placeholder="http://192.168.80.50:8080"
                spellCheck={false}
                onChange={(event) => setBaseUrl(event.target.value)}
              />
            </label>
            <label className="form-field form-field-wide">
              <span>测试仓库地址</span>
              <input
                value={testRepoUrl}
                placeholder="git@github.com:acme/qa.git"
                spellCheck={false}
                onChange={(event) => setTestRepoUrl(event.target.value)}
              />
            </label>
            <label className="form-field">
              <span>测试仓库分支</span>
              <input
                value={testRepoRef}
                placeholder="main"
                spellCheck={false}
                onChange={(event) => setTestRepoRef(event.target.value)}
              />
            </label>
            <p className="dialog-note form-field-wide">
              AI 生成用例后先 commit 并 push 到该仓库，再上报用例索引；平台只存索引与证据，
              不克隆仓库。whoami 会把仓库地址下发给接入方。
            </p>
          </div>
        )}

        {tab === 'rules' && (
          <ProjectAgentRulesSection
            projectId={project.id}
            canEdit={project.role === 'admin'}
          />
        )}

        {tab === 'tokens' && <ProjectTokensSection projectId={project.id} />}

        {tab === 'secrets' && (
          <ProjectSecretsSection
            projectId={project.id}
            canEdit={project.role === 'admin'}
          />
        )}

        {tab === 'danger' && (
          <>
            <p className="dialog-note">
              删除项目会一并移除其需求、接口、用例、运行、证据与缺陷，且不可恢复。
            </p>
            {confirmDelete && (
              <p className="dialog-note dialog-note-danger">
                再次点击「确认删除」将永久删除项目 {project.name}，该操作不可撤销。
              </p>
            )}
          </>
        )}
      </div>
    </DialogShell>
  )
}
