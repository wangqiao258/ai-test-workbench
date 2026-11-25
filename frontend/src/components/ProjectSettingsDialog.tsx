import { useEffect, useState, type FormEvent } from 'react'
import type { Project } from '../types'
import type { UpdateProjectInput } from '../services/api'
import { Icon } from './ui'

interface Props {
  open: boolean
  project: Project
  onCancel: () => void
  onSubmit: (projectId: string, input: UpdateProjectInput) => Promise<void>
  onDelete: (projectId: string) => Promise<void>
}

export function ProjectSettingsDialog({
  open,
  project,
  onCancel,
  onSubmit,
  onDelete,
}: Props) {
  const [name, setName] = useState('')
  const [repo, setRepo] = useState('')
  const [environment, setEnvironment] = useState('')
  const [owner, setOwner] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  useEffect(() => {
    if (!open) return
    setName(project.name)
    setRepo(project.repo)
    setEnvironment(project.environment)
    setOwner(project.owner)
    setError('')
    setBusy(false)
    setConfirmDelete(false)
  }, [open, project])

  if (!open) return null

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
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
        repo: repo.trim(),
        environment: environment.trim(),
        owner: owner.trim(),
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

  return (
    <div className="dialog-backdrop" onMouseDown={busy ? undefined : onCancel}>
      <form
        className="dialog dialog-project"
        role="dialog"
        aria-modal="true"
        aria-label="项目设置"
        onSubmit={submit}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="dialog-head">
          <span className="dialog-icon dialog-icon-primary">
            <Icon name="server" size={18} />
          </span>
          <div>
            <h3>项目设置</h3>
            <p>
              项目 KEY <code className="mono-id">{project.key}</code>{' '}
              创建后不可修改；删除项目会一并移除其需求、接口、运行与缺陷。
            </p>
          </div>
        </div>

        <div className="form-grid">
          <label className="form-field">
            <span>项目名称 *</span>
            <input
              autoFocus
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label className="form-field">
            <span>仓库</span>
            <input
              value={repo}
              placeholder="shop/shop-api"
              onChange={(event) => setRepo(event.target.value)}
            />
          </label>
          <label className="form-field">
            <span>环境</span>
            <input
              value={environment}
              placeholder="staging-cn-east"
              onChange={(event) => setEnvironment(event.target.value)}
            />
          </label>
          <label className="form-field">
            <span>负责人</span>
            <input
              value={owner}
              placeholder="交易产品组"
              onChange={(event) => setOwner(event.target.value)}
            />
          </label>
        </div>

        {confirmDelete && (
          <p className="dialog-note dialog-note-danger">
            再次点击「确认删除」将永久删除项目 {project.name}，该操作不可撤销。
          </p>
        )}

        {error && <p className="dialog-error">{error}</p>}

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
              取消
            </button>
            <button type="submit" className="btn btn-primary" disabled={busy}>
              {busy ? '保存中…' : '保存修改'}
            </button>
          </div>
        </div>
      </form>
    </div>
  )
}
