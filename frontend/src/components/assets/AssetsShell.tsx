import type { ReactNode } from 'react'
import type { AssetTab, Navigate } from '../../types'
import { EmptyState, Icon, Segmented } from '../ui'

interface AssetsHeaderProps {
  assetTab: AssetTab
  canEdit: boolean
  requirementCount: number
  operationCount: number
  docId: string
  operationId: string
  navigate: Navigate
  onOpenRequirement: () => void
  onOpenOpenApi: () => void
}

export function AssetsHeader({
  assetTab,
  canEdit,
  requirementCount,
  operationCount,
  docId,
  operationId,
  navigate,
  onOpenRequirement,
  onOpenOpenApi,
}: AssetsHeaderProps) {
  return (
    <header className="view-head">
      <div>
        <div className="view-kicker">ASSET LIBRARY / 01</div>
        <h1 className="view-title">需求与接口</h1>
        <p className="view-desc">
          需求以 Markdown 入库，接口按 OpenAPI 结构化展示；两者与 pytest
          用例、运行结果建立追溯关系，作为 AI 判断契约偏差的依据。
        </p>
      </div>
      <div className="view-head-actions">
        {canEdit && assetTab === 'requirements' && (
          <button type="button" className="btn" onClick={onOpenRequirement}>
            <Icon name="file" size={14} />
            导入需求
          </button>
        )}
        {canEdit && assetTab === 'openapi' && (
          <button type="button" className="btn" onClick={onOpenOpenApi}>
            <Icon name="file" size={14} />
            导入 OpenAPI
          </button>
        )}
        <Segmented
          value={assetTab}
          onChange={(value) =>
            navigate({
              assetTab: value,
              ...(value === 'openapi' ? { docId, operationId } : {}),
            })
          }
          options={[
            {
              value: 'requirements',
              label: '需求文档',
              count: requirementCount,
            },
            { value: 'openapi', label: '接口契约', count: operationCount },
          ]}
        />
      </div>
    </header>
  )
}

interface AssetsEmptyViewProps {
  title: string
  description: string
  action?: ReactNode
  assetTab: AssetTab
  canEdit: boolean
  hasRequirements: boolean
  hasDocs: boolean
  requirementCount: number
  operationCount: number
  navigate: Navigate
  onOpenRequirement: () => void
  onOpenOpenApi: () => void
  dialogs: ReactNode
}

export function AssetsEmptyView({
  title,
  description,
  action,
  assetTab,
  canEdit,
  hasRequirements,
  hasDocs,
  requirementCount,
  operationCount,
  navigate,
  onOpenRequirement,
  onOpenOpenApi,
  dialogs,
}: AssetsEmptyViewProps) {
  return (
    <div className="view">
      <header className="view-head">
        <div>
          <div className="view-kicker">ASSET LIBRARY / 01</div>
          <h1 className="view-title">需求与接口</h1>
          <p className="view-desc">
            需求以 Markdown 入库，接口按 OpenAPI 结构化展示；两者与 pytest
            用例、运行结果建立追溯关系，作为 AI 判断契约偏差的依据。
          </p>
        </div>
        {(canEdit || hasRequirements || hasDocs) && (
          <div className="view-head-actions">
            {canEdit && (
              <>
                <button type="button" className="btn" onClick={onOpenRequirement}>
                  <Icon name="file" size={14} />
                  导入需求
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={onOpenOpenApi}
                >
                  <Icon name="plus" size={14} />
                  导入 OpenAPI
                </button>
              </>
            )}
            {(hasRequirements || hasDocs) && (
              <Segmented
                value={assetTab}
                onChange={(value) => navigate({ assetTab: value })}
                options={[
                  {
                    value: 'requirements',
                    label: '需求文档',
                    count: requirementCount,
                  },
                  {
                    value: 'openapi',
                    label: '接口契约',
                    count: operationCount,
                  },
                ]}
              />
            )}
          </div>
        )}
      </header>
      <div className="view-body">
        <EmptyState
          icon="book"
          title={title}
          description={description}
          action={action}
        />
      </div>
      {dialogs}
    </div>
  )
}
