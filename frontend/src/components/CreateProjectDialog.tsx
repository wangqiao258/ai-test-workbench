import { useEffect, useState } from 'react'
import type { CreateProjectInput } from '../services/api'
import { DialogShell } from './ui'

interface Props {
  open: boolean
  onCancel: () => void
  onSubmit: (input: CreateProjectInput) => Promise<void>
}

export function CreateProjectDialog({ open, onCancel, onSubmit }: Props) {
  const [name, setName] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open) return
    setName('')
    setBaseUrl('')
    setError('')
    setLoading(false)
  }, [open])

  const submit = async () => {
    if (loading) return

    const trimmedName = name.trim()
    if (!trimmedName) {
      setError('请填写项目名称')
      return
    }

    setLoading(true)
    setError('')
    try {
      await onSubmit({ name: trimmedName, baseUrl: baseUrl.trim() })
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建项目失败')
      setLoading(false)
    }
  }

  return (
    <DialogShell
      open={open}
      title="新建项目"
      description="创建后你将成为该项目的管理员，需求、运行与缺陷与其他项目完全隔离。"
      icon="plus"
      className="dialog-project"
      busy={loading}
      busyText="创建中…"
      error={error}
      submitText="创建项目"
      canSubmit={Boolean(name.trim())}
      onCancel={onCancel}
      onSubmit={submit}
    >
      <div className="form-grid">
        <label className="form-field form-field-wide">
          <span>项目名称 *</span>
          <input
            autoFocus
            value={name}
            placeholder="交易服务"
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
    </DialogShell>
  )
}
