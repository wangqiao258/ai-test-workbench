import { useEffect, useState } from 'react'
import { api, type AgentRules } from '../services/api'
import { Icon } from './ui'

interface Props {
  projectId: string
  canEdit: boolean
}

export function ProjectAgentRulesSection({ projectId, canEdit }: Props) {
  const [text, setText] = useState('')
  const [isCustom, setIsCustom] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [resetArmed, setResetArmed] = useState(false)

  const apply = (data: AgentRules) => {
    setText(data.rules.join('\n'))
    setIsCustom(data.isCustom)
  }

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError('')
    api
      .fetchAgentRules(projectId)
      .then((data) => {
        if (alive) apply(data)
      })
      .catch((err) => {
        if (alive) {
          setError(err instanceof Error ? err.message : '读取 AI 规则失败')
        }
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [projectId])

  const lines = text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)

  const save = async () => {
    if (saving) return
    setSaving(true)
    setError('')
    setNotice('')
    try {
      const saved = await api.saveAgentRules(projectId, lines)
      apply(saved)
      setResetArmed(false)
      setNotice(`已保存 ${lines.length} 条规则，下一次 whoami 立即生效`)
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存 AI 规则失败')
    } finally {
      setSaving(false)
    }
  }

  const reset = async () => {
    if (saving) return
    if (!resetArmed) {
      setResetArmed(true)
      return
    }
    setSaving(true)
    setError('')
    setNotice('')
    try {
      const restored = await api.resetAgentRules(projectId)
      apply(restored)
      setResetArmed(false)
      setNotice('已恢复默认规则')
    } catch (err) {
      setError(err instanceof Error ? err.message : '恢复默认规则失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="token-section" aria-label="AI 接入规则">
      <div className="token-section-head">
        <div>
          <h4>AI 接入规则</h4>
          <p>
            通过 whoami 原样下发给 AI，每行一条；平台自身的校验仍然生效。
            留空表示不附加任何规则。
          </p>
        </div>
        <span className="token-count">{isCustom ? '已自定义' : '默认规则'}</span>
      </div>

      {loading ? (
        <p className="token-hint">正在读取 AI 规则…</p>
      ) : (
        <>
          <label className="form-field form-field-wide">
            <span>规则内容</span>
            <textarea
              className="textarea"
              rows={14}
              value={text}
              readOnly={!canEdit}
              spellCheck={false}
              onChange={(event) => setText(event.target.value)}
            />
          </label>
          {canEdit && (
            <div className="token-create">
              <button
                type="button"
                className="btn btn-primary btn-xs"
                onClick={() => void save()}
                disabled={saving}
              >
                <Icon name="check" size={13} />
                {saving ? '保存中…' : '保存规则'}
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-xs"
                onClick={() => void reset()}
                disabled={saving || !isCustom}
              >
                {resetArmed ? '确认恢复默认' : '恢复默认'}
              </button>
            </div>
          )}
          <p className="token-hint">
            共 {lines.length} 条。修改后保存，下一次 AI 调用 whoami 即拿到新规则。
          </p>
        </>
      )}

      {error && <p className="dialog-error">{error}</p>}
      {notice && <p className="token-hint">{notice}</p>}
    </section>
  )
}
