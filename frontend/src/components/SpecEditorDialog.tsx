import { useEffect, useState } from 'react'
import { api, type SpecContent } from '../services/api'
import { DialogShell } from './ui'

interface Props {
  open: boolean
  projectId: string
  path: string
  onCancel: () => void
  onSaved: (message: string) => void
}

export function SpecEditorDialog({
  open,
  projectId,
  path,
  onCancel,
  onSaved,
}: Props) {
  const [content, setContent] = useState('')
  const [sha256, setSha256] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)

  useEffect(() => {
    if (!open) return
    let alive = true
    setContent('')
    setSha256('')
    setError('')
    setSaving(false)
    setConfirmDelete(false)
    if (!path) {
      setError('该用例没有可编辑的规格文件')
      return
    }
    setLoading(true)
    api
      .fetchSpecContent(projectId, path)
      .then((result: SpecContent) => {
        if (!alive) return
        setContent(result.content)
        setSha256(result.sha256)
      })
      .catch((err: unknown) => {
        if (!alive) return
        setError(err instanceof Error ? err.message : '读取规格失败')
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [open, projectId, path])

  const submit = async () => {
    if (saving || !path) return
    setSaving(true)
    setError('')
    try {
      const result = await api.saveSpecContent(projectId, {
        path,
        content,
        expectedSha256: sha256 || undefined,
      })
      setSha256(result.sha256)
      onSaved(`规格已保存：${result.path}（${result.caseCount} 条用例）`)
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存规格失败')
      setSaving(false)
    }
  }

  const remove = async () => {
    if (saving || !path) return
    if (!confirmDelete) {
      setConfirmDelete(true)
      return
    }
    setSaving(true)
    setError('')
    try {
      const result = await api.deleteSpec(projectId, path)
      onSaved(
        result.archivedCaseCount
          ? `规格已删除，${result.archivedCaseCount} 条用例已归档`
          : '规格已删除',
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除规格失败')
      setSaving(false)
      setConfirmDelete(false)
    }
  }

  return (
    <DialogShell
      open={open}
      title="编辑规格"
      description={
        path
          ? `${path} · 用例名称、标签和关联需求都来自这份 YAML`
          : '没有找到该用例对应的 YAML 文件'
      }
      icon="file"
      wide
      className="dialog-project dialog-spec"
      busy={saving}
      busyText="保存中…"
      error={error}
      submitText="保存规格"
      canSubmit={Boolean(path && content.trim())}
      onCancel={onCancel}
      onSubmit={submit}
      footer={
        <div className="dialog-actions dialog-actions-split">
          <button
            type="button"
            className="btn btn-danger"
            onClick={remove}
            disabled={saving || loading || !path}
          >
            {confirmDelete ? '确认删除' : '删除文件'}
          </button>
          <div className="dialog-actions-group">
            <button type="button" className="btn" onClick={onCancel} disabled={saving}>
              取消
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={saving || loading || !path || !content.trim()}
            >
              {saving ? '保存中…' : '保存规格'}
            </button>
          </div>
        </div>
      }
    >
      {confirmDelete && (
        <p className="dialog-note dialog-note-danger">
          再次点击「确认删除」将删除该 YAML 文件，并把其中的用例归档。
        </p>
      )}
      {loading ? (
        <p className="dialog-note">正在读取规格…</p>
      ) : (
        <label className="form-field form-field-wide">
          <span>YAML 内容</span>
          <textarea
            className="textarea spec-editor"
            rows={20}
            value={content}
            spellCheck={false}
            onChange={(event) => setContent(event.target.value)}
          />
        </label>
      )}
    </DialogShell>
  )
}
