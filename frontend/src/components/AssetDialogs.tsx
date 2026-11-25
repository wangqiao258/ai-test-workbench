import { useEffect, useState, type ChangeEvent, type FormEvent, type ReactNode } from 'react'
import type { HttpMethod, OpenApiDoc, Operation, Requirement } from '../types'
import type {
  OpenApiImportInput,
  OperationInput,
  RequirementInput,
} from '../services/api'
import { Icon, type IconName } from './ui'

interface ShellProps {
  open: boolean
  title: string
  description: string
  icon?: IconName
  wide?: boolean
  busy?: boolean
  error?: string
  submitText: string
  canSubmit: boolean
  onCancel: () => void
  onSubmit: () => void
  children: ReactNode
}

function DialogShell({
  open,
  title,
  description,
  icon = 'plus',
  wide = false,
  busy = false,
  error = '',
  submitText,
  canSubmit,
  onCancel,
  onSubmit,
  children,
}: ShellProps) {
  if (!open) return null
  return (
    <div className="dialog-backdrop" onMouseDown={busy ? undefined : onCancel}>
      <form
        className={`dialog dialog-project ${wide ? 'dialog-wide' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onSubmit={(event: FormEvent<HTMLFormElement>) => {
          event.preventDefault()
          if (!busy && canSubmit) onSubmit()
        }}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="dialog-head">
          <span className="dialog-icon dialog-icon-primary">
            <Icon name={icon} size={18} />
          </span>
          <div>
            <h3>{title}</h3>
            <p>{description}</p>
          </div>
        </div>
        {children}
        {error && <p className="dialog-error">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onCancel} disabled={busy}>
            取消
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy || !canSubmit}>
            {busy ? '提交中…' : submitText}
          </button>
        </div>
      </form>
    </div>
  )
}

const splitTags = (value: string) =>
  value
    .split(/[,，、\s]+/)
    .map((item) => item.trim())
    .filter(Boolean)

interface RequirementDialogProps {
  open: boolean
  initial?: Requirement | null
  onCancel: () => void
  onSubmit: (input: RequirementInput) => Promise<void>
}

export function RequirementDialog({
  open,
  initial,
  onCancel,
  onSubmit,
}: RequirementDialogProps) {
  const editing = Boolean(initial)
  const [externalId, setExternalId] = useState('')
  const [title, setTitle] = useState('')
  const [version, setVersion] = useState('')
  const [owner, setOwner] = useState('')
  const [tags, setTags] = useState('')
  const [contentMd, setContentMd] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    setExternalId(initial?.id ?? '')
    setTitle(initial?.title ?? '')
    setVersion(initial?.version ?? '')
    setOwner(initial?.owner ?? '')
    setTags((initial?.tags ?? []).join(', '))
    setContentMd(initial?.contentMd ?? '')
    setError('')
    setBusy(false)
  }, [open, initial])

  const submit = async () => {
    if (busy) return
    const id = externalId.trim()
    if (!id) {
      setError('请填写需求编号')
      return
    }
    setBusy(true)
    setError('')
    try {
      await onSubmit({
        externalId: id,
        title: title.trim(),
        version: version.trim(),
        owner: owner.trim(),
        tags: splitTags(tags),
        contentMd,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存需求失败')
      setBusy(false)
    }
  }

  return (
    <DialogShell
      open={open}
      title={editing ? '编辑需求' : '导入需求文档'}
      description="需求以 Markdown 正文入库，与接口契约、pytest 用例建立追溯关系。"
      icon="file"
      wide
      busy={busy}
      error={error}
      submitText={editing ? '保存修改' : '导入需求'}
      canSubmit={Boolean(externalId.trim())}
      onCancel={onCancel}
      onSubmit={submit}
    >
      <div className="form-grid">
        <label className="form-field">
          <span>需求编号 *</span>
          <input
            value={externalId}
            disabled={editing}
            placeholder="REQ-ORDER-01"
            spellCheck={false}
            onChange={(event) => setExternalId(event.target.value)}
          />
          {editing && <em>编号是追溯主键，创建后不可修改</em>}
        </label>
        <label className="form-field">
          <span>标题</span>
          <input
            value={title}
            placeholder="订单创建与库存锁定"
            onChange={(event) => setTitle(event.target.value)}
          />
        </label>
        <label className="form-field">
          <span>版本</span>
          <input
            value={version}
            placeholder="v1.2"
            onChange={(event) => setVersion(event.target.value)}
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
        <label className="form-field form-field-wide">
          <span>标签</span>
          <input
            value={tags}
            placeholder="订单, 库存, 核心链路"
            onChange={(event) => setTags(event.target.value)}
          />
        </label>
        <label className="form-field form-field-wide">
          <span>需求正文（Markdown）</span>
          <textarea
            className="textarea"
            rows={13}
            value={contentMd}
            placeholder={'# 背景\n\n## 验收标准\n\n- ...'}
            spellCheck={false}
            onChange={(event) => setContentMd(event.target.value)}
          />
        </label>
      </div>
    </DialogShell>
  )
}

interface OpenApiImportDialogProps {
  open: boolean
  onCancel: () => void
  onSubmit: (input: OpenApiImportInput) => Promise<void>
}

export function OpenApiImportDialog({
  open,
  onCancel,
  onSubmit,
}: OpenApiImportDialogProps) {
  const [externalId, setExternalId] = useState('')
  const [title, setTitle] = useState('')
  const [version, setVersion] = useState('')
  const [content, setContent] = useState('')
  const [filename, setFilename] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    setExternalId('')
    setTitle('')
    setVersion('')
    setContent('')
    setFilename('')
    setError('')
    setBusy(false)
  }, [open])

  const pickFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return
    try {
      const text = await file.text()
      setContent(text)
      setFilename(file.name)
      if (!externalId) {
        setExternalId(file.name.replace(/\.(json|ya?ml)$/i, ''))
      }
      setError('')
    } catch {
      setError('读取文件失败')
    } finally {
      event.target.value = ''
    }
  }

  const submit = async () => {
    if (busy) return
    if (!externalId.trim()) {
      setError('请填写文档编号')
      return
    }
    if (!content.trim()) {
      setError('请粘贴 OpenAPI 文档或选择文件')
      return
    }
    setBusy(true)
    setError('')
    try {
      await onSubmit({
        externalId: externalId.trim(),
        content,
        title: title.trim(),
        version: version.trim(),
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : '导入 OpenAPI 失败')
      setBusy(false)
    }
  }

  return (
    <DialogShell
      open={open}
      title="导入 OpenAPI 文档"
      description="粘贴或选择 OpenAPI 3.x 文档，支持 JSON / YAML，以及 HEAD / OPTIONS / TRACE 等方法。同一编号再次导入会覆盖原契约。"
      icon="file"
      wide
      busy={busy}
      error={error}
      submitText="解析并导入"
      canSubmit={Boolean(externalId.trim() && content.trim())}
      onCancel={onCancel}
      onSubmit={submit}
    >
      <div className="form-grid">
        <label className="form-field">
          <span>文档编号 *</span>
          <input
            value={externalId}
            placeholder="DOC-ORDER"
            spellCheck={false}
            onChange={(event) => setExternalId(event.target.value)}
          />
        </label>
        <label className="form-field">
          <span>文档标题</span>
          <input
            value={title}
            placeholder="订单服务接口"
            onChange={(event) => setTitle(event.target.value)}
          />
        </label>
        <label className="form-field">
          <span>版本</span>
          <input
            value={version}
            placeholder="v1.4"
            onChange={(event) => setVersion(event.target.value)}
          />
        </label>
        <label className="form-field">
          <span>从文件读取</span>
          <span className="file-pick">
            <input
              type="file"
              accept=".json,.yaml,.yml,application/json,text/yaml"
              onChange={pickFile}
            />
            <em>{filename || '选择 .json / .yaml / .yml'}</em>
          </span>
        </label>
        <label className="form-field form-field-wide">
          <span>文档内容 *</span>
          <textarea
            className="textarea textarea-code"
            rows={14}
            value={content}
            placeholder={'openapi: 3.0.3\ninfo:\n  title: 订单服务\n  version: 1.4.0\npaths:\n  /orders:\n    head: ...'}
            spellCheck={false}
            onChange={(event) => setContent(event.target.value)}
          />
        </label>
      </div>
    </DialogShell>
  )
}

interface DocSettingsDialogProps {
  open: boolean
  initial: OpenApiDoc | null
  onCancel: () => void
  onSubmit: (input: { title?: string; version?: string; baseUrl?: string; description?: string }) => Promise<void>
}

export function DocSettingsDialog({
  open,
  initial,
  onCancel,
  onSubmit,
}: DocSettingsDialogProps) {
  const [title, setTitle] = useState('')
  const [version, setVersion] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [description, setDescription] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    setTitle(initial?.title ?? '')
    setVersion(initial?.version ?? '')
    setBaseUrl(initial?.baseUrl ?? '')
    setDescription(initial?.description ?? '')
    setError('')
    setBusy(false)
  }, [open, initial])

  const submit = async () => {
    if (busy) return
    if (!title.trim()) {
      setError('文档标题不能为空')
      return
    }
    setBusy(true)
    setError('')
    try {
      await onSubmit({
        title: title.trim(),
        version: version.trim(),
        baseUrl: baseUrl.trim(),
        description,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存文档失败')
      setBusy(false)
    }
  }

  return (
    <DialogShell
      open={open}
      title="编辑契约文档"
      description="只修改文档元信息，接口明细请在右侧接口详情里编辑。"
      icon="file"
      busy={busy}
      error={error}
      submitText="保存修改"
      canSubmit={Boolean(title.trim())}
      onCancel={onCancel}
      onSubmit={submit}
    >
      <div className="form-grid">
        <label className="form-field form-field-wide">
          <span>文档标题 *</span>
          <input value={title} onChange={(event) => setTitle(event.target.value)} />
        </label>
        <label className="form-field">
          <span>版本</span>
          <input value={version} onChange={(event) => setVersion(event.target.value)} />
        </label>
        <label className="form-field">
          <span>Base URL</span>
          <input
            value={baseUrl}
            placeholder="https://api.example.com"
            spellCheck={false}
            onChange={(event) => setBaseUrl(event.target.value)}
          />
        </label>
        <label className="form-field form-field-wide">
          <span>描述</span>
          <textarea
            className="textarea"
            rows={5}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
      </div>
    </DialogShell>
  )
}

const METHOD_OPTIONS: HttpMethod[] = [
  'GET',
  'POST',
  'PUT',
  'PATCH',
  'DELETE',
  'HEAD',
  'OPTIONS',
  'TRACE',
]

interface OperationDialogProps {
  open: boolean
  initial: Operation | null
  onCancel: () => void
  onSubmit: (input: OperationInput) => Promise<void>
}

export function OperationDialog({
  open,
  initial,
  onCancel,
  onSubmit,
}: OperationDialogProps) {
  const [method, setMethod] = useState<HttpMethod>('GET')
  const [path, setPath] = useState('')
  const [summary, setSummary] = useState('')
  const [tag, setTag] = useState('')
  const [description, setDescription] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    setMethod(initial?.method ?? 'GET')
    setPath(initial?.path ?? '')
    setSummary(initial?.summary ?? '')
    setTag(initial?.tag ?? '')
    setDescription(initial?.description ?? '')
    setError('')
    setBusy(false)
  }, [open, initial])

  const submit = async () => {
    if (busy) return
    if (!path.trim()) {
      setError('接口 path 不能为空')
      return
    }
    setBusy(true)
    setError('')
    try {
      await onSubmit({
        method,
        path: path.trim(),
        summary: summary.trim(),
        tag: tag.trim(),
        description,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存接口失败')
      setBusy(false)
    }
  }

  return (
    <DialogShell
      open={open}
      title="编辑接口"
      description="调整请求方法、路径与摘要；参数、请求体与响应的结构仍由 OpenAPI 导入维护。"
      icon="layers"
      busy={busy}
      error={error}
      submitText="保存修改"
      canSubmit={Boolean(path.trim())}
      onCancel={onCancel}
      onSubmit={submit}
    >
      <div className="form-grid">
        <label className="form-field">
          <span>请求方法</span>
          <select
            value={method}
            onChange={(event) => setMethod(event.target.value as HttpMethod)}
          >
            {METHOD_OPTIONS.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>
        <label className="form-field">
          <span>Path *</span>
          <input
            value={path}
            spellCheck={false}
            onChange={(event) => setPath(event.target.value)}
          />
        </label>
        <label className="form-field form-field-wide">
          <span>摘要</span>
          <input
            value={summary}
            onChange={(event) => setSummary(event.target.value)}
          />
        </label>
        <label className="form-field">
          <span>分组</span>
          <input value={tag} onChange={(event) => setTag(event.target.value)} />
        </label>
        <label className="form-field form-field-wide">
          <span>描述</span>
          <textarea
            className="textarea"
            rows={5}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
      </div>
    </DialogShell>
  )
}
