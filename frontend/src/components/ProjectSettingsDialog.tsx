import { useEffect, useState } from 'react'
import type { Project } from '../types'
import type { UpdateProjectInput } from '../services/api'
import { ProjectTokensSection } from './ProjectTokensSection'
import { DialogShell } from './ui'

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
  const [baseUrl, setBaseUrl] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  useEffect(() => {
    if (!open) return
    setName(project.name)
    setBaseUrl(project.baseUrl)
    setError('')
    setBusy(false)
    setConfirmDelete(false)
  }, [open, project])

  const submit = async () => {
    if (busy) return
    if (!name.trim()) {
      setError('项目名称不能为空')
      return
    }
    setBusy(true)
    setError('')
    try {
      await onSubmit(project.id, { name: name.trim(), baseUrl: baseUrl.trim() })
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
    <DialogShell
      open={open}
      title="项目设置"
      description="维护项目资料，管理 AI 接入令牌；删除项目会一并移除其需求、接口、运行与缺陷。"
      icon="server"
      className="dialog-project dialog-settings"
      busy={busy}
      busyText="保存中…"
      error={error}
      submitText="保存修改"
      onCancel={onCancel}
      onSubmit={submit}
      footer={
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
      }
    >
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
      </div>

      <ProjectTokensSection projectId={project.id} />

      {confirmDelete && (
        <p className="dialog-note dialog-note-danger">
          再次点击「确认删除」将永久删除项目 {project.name}，该操作不可撤销。
        </p>
      )}
    </DialogShell>
  )
}
