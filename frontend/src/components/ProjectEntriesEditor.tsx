import type { ProjectEntry } from '../types'

const MAX_ENTRIES = 20

interface Props {
  entries: ProjectEntry[]
  onChange: (entries: ProjectEntry[]) => void
}

export function emptyEntry(): ProjectEntry {
  return { name: '', url: '', note: '' }
}

export function validateEntries(
  entries: ProjectEntry[],
): { entries: ProjectEntry[]; error: string } {
  const cleaned = entries
    .map((entry) => ({
      name: entry.name.trim(),
      url: entry.url.trim().replace(/\/+$/, ''),
      note: entry.note.trim(),
    }))
    .filter((entry) => entry.name || entry.url || entry.note)

  const seen = new Set<string>()
  for (const entry of cleaned) {
    if (!entry.name || !entry.url) {
      return { entries: [], error: '入口名称和地址需要同时填写' }
    }
    if (!/^https?:\/\//i.test(entry.url)) {
      return {
        entries: [],
        error: `入口地址需以 http:// 或 https:// 开头：${entry.url}`,
      }
    }
    if (seen.has(entry.url)) {
      return { entries: [], error: `入口地址重复：${entry.url}` }
    }
    seen.add(entry.url)
  }
  return { entries: cleaned, error: '' }
}

export function ProjectEntriesEditor({ entries, onChange }: Props) {
  const update = (index: number, patch: Partial<ProjectEntry>) => {
    onChange(entries.map((entry, i) => (i === index ? { ...entry, ...patch } : entry)))
  }

  const add = () => {
    if (entries.length >= MAX_ENTRIES) return
    onChange([...entries, emptyEntry()])
  }

  const remove = (index: number) => {
    onChange(entries.filter((_, i) => i !== index))
  }

  return (
    <div className="form-field form-field-wide">
      <span>测试入口</span>
      <div className="entry-list">
        {entries.map((entry, index) => (
          <div className="entry-row" key={index}>
            <input
              aria-label="入口名称"
              placeholder="名称，如小程序"
              value={entry.name}
              onChange={(event) => update(index, { name: event.target.value })}
            />
            <input
              aria-label="入口地址"
              placeholder="https://..."
              value={entry.url}
              spellCheck={false}
              onChange={(event) => update(index, { url: event.target.value })}
            />
            <input
              aria-label="入口备注"
              placeholder="备注，如登录方式"
              value={entry.note}
              onChange={(event) => update(index, { note: event.target.value })}
            />
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => remove(index)}
            >
              删除
            </button>
          </div>
        ))}
      </div>
      <div className="entry-actions">
        <button
          type="button"
          className="btn"
          onClick={add}
          disabled={entries.length >= MAX_ENTRIES}
        >
          添加入口
        </button>
        <em>名称和地址必填；页面或接口地址均可，由 AI 探测</em>
      </div>
    </div>
  )
}
