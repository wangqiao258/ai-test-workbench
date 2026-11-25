import { useEffect, useState } from 'react'
import type { Project, Run } from '../types'
import { formatDateTime } from '../utils/format'
import { Icon } from './ui'

export interface ProjectSummary {
  project: Project
  caseCount: number
  pending: number
  openDefects: number
  lastRun?: Run
}

interface Props {
  items: ProjectSummary[]
  activeId: string
  onSelect: (projectId: string) => void
  canCreate?: boolean
  onCreate?: () => void
  canManage?: boolean
  onManage?: () => void
}

export function ProjectSwitcher({
  items,
  activeId,
  onSelect,
  canCreate = false,
  onCreate,
  canManage = false,
  onManage,
}: Props) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')

  const active =
    items.find((item) => item.project.id === activeId)?.project ??
    items[0]?.project

  useEffect(() => {
    if (!open) {
      setQuery('')
      return
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open])

  if (!active) return null

  const keyword = query.trim().toLowerCase()
  const visible = items.filter((item) => {
    if (!keyword) return true
    return `${item.project.name} ${item.project.key} ${item.project.repo}`
      .toLowerCase()
      .includes(keyword)
  })

  return (
    <div className="project-switcher">
      <button
        type="button"
        className="project-btn"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="project-copy">
          <span className="project-name">{active.name}</span>
          <span className="project-key">{active.key}</span>
        </span>
        <Icon name="chevronDown" size={14} />
      </button>

      {open && (
        <>
          <div
            className="project-scrim"
            aria-hidden="true"
            onClick={() => setOpen(false)}
          />
          <div className="project-menu" role="dialog" aria-label="切换项目">
            <div className="project-menu-head">
              <span>切换项目</span>
              <span className="count-pill">{items.length}</span>
            </div>

            <label className="search-field project-search">
              <Icon name="search" size={14} />
              <input
                autoFocus
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索项目、KEY 或仓库"
                aria-label="搜索项目"
              />
            </label>

            <div className="project-list" role="listbox" aria-label="项目列表">
              {visible.length ? (
                visible.map((item) => {
                  const isActive = item.project.id === activeId
                  return (
                    <button
                      key={item.project.id}
                      type="button"
                      role="option"
                      aria-selected={isActive}
                      className={`project-option ${isActive ? 'is-active' : ''}`}
                      onClick={() => {
                        setOpen(false)
                        if (!isActive) onSelect(item.project.id)
                      }}
                    >
                      <span className="project-option-top">
                        <strong>{item.project.name}</strong>
                        <span className="project-option-key">
                          {item.project.key}
                        </span>
                        {isActive && <Icon name="check" size={13} />}
                      </span>
                      <span className="project-option-sub">
                        {item.project.repo} · {item.project.environment}
                      </span>
                      <span className="project-option-stats">
                        <span
                          className={item.pending ? 'project-pending' : ''}
                        >
                          {item.pending} 待审判
                        </span>
                        <span>{item.openDefects} 未关闭缺陷</span>
                        <span>{item.caseCount} 用例</span>
                        <span className="project-option-run">
                          {item.lastRun
                            ? `最近 ${formatDateTime(item.lastRun.startedAt)}`
                            : '暂无运行'}
                        </span>
                      </span>
                    </button>
                  )
                })
              ) : (
                <p className="project-empty">没有匹配的项目</p>
              )}
            </div>

            <div className="project-menu-foot">
              <span>项目之间的需求、运行与缺陷完全隔离</span>
              <div className="project-menu-actions">
                {canManage && onManage && (
                  <button
                    type="button"
                    className="btn btn-ghost btn-xs"
                    onClick={() => {
                      setOpen(false)
                      onManage()
                    }}
                  >
                    <Icon name="server" size={13} />
                    项目设置
                  </button>
                )}
                {canCreate && onCreate && (
                  <button
                    type="button"
                    className="btn btn-ghost btn-xs"
                    onClick={() => {
                      setOpen(false)
                      onCreate()
                    }}
                  >
                    <Icon name="plus" size={13} />
                    新建项目
                  </button>
                )}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
