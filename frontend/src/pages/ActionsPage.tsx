import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { useActionSummary, useActions, useProjects } from '@/api/queries'
import {
  ACTION_VIEWS,
  ACTION_VIEW_LABELS,
  isActionSort,
  type Action,
  type ActionSort,
  type ActionView,
  type SortOrder,
} from '@/api/types'
import { useAuth } from '@/auth/useAuth'
import { ActionStatusBadge } from '@/features/actions/ActionStatusBadge'
import { DeadlineCell } from '@/features/actions/DeadlineCell'
import { NewActionModal } from '@/features/actions/NewActionModal'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { cn } from '@/lib/cn'
import { Breadcrumb } from '@/ui/Breadcrumb'
import { Button } from '@/ui/Button'
import { DataTable, type Column } from '@/ui/DataTable'
import { EmptyState } from '@/ui/EmptyState'
import { ErrorState } from '@/ui/ErrorState'
import { SelectField, TextField } from '@/ui/Field'
import { IconActivity, IconPlus } from '@/ui/Icon'
import { PageHeader } from '@/ui/PageHeader'
import { Pagination } from '@/ui/Pagination'
import { ProgressBar } from '@/ui/ProgressBar'

const PAGE_SIZE = 25

/** Vues mises en avant sous forme d'onglets ; le reste passe par le select. */
const TAB_VIEWS: ActionView[] = ['all', 'open', 'overdue', 'today', 'due_soon', 'blocked', 'done']

function isActionView(value: string | null): value is ActionView {
  return value !== null && (ACTION_VIEWS as readonly string[]).includes(value)
}

export function ActionsPage() {
  const { canWrite } = useAuth()
  const [params, setParams] = useSearchParams()
  const [modalOpen, setModalOpen] = useState(false)
  const [offset, setOffset] = useState(0)

  const view: ActionView = isActionView(params.get('vue')) ? (params.get('vue') as ActionView) : 'all'
  const search = params.get('search') ?? ''
  const projectId = params.get('projet') ?? ''
  const debouncedSearch = useDebouncedValue(search, 300)

  // Le tri vit dans l'URL, comme les filtres : un « regarde les retards de
  // P01 » se transmet alors par simple copie du lien.
  const sort: ActionSort | null = isActionSort(params.get('tri')) ? (params.get('tri') as ActionSort) : null
  const sortOrder: SortOrder = params.get('sens') === 'desc' ? 'desc' : 'asc'

  const summaryQuery = useActionSummary()
  const projectsQuery = useProjects({ is_active: true, limit: 200 })
  const actionsQuery = useActions({
    view,
    search: debouncedSearch.trim() || null,
    project_id: projectId || null,
    sort,
    order: sortOrder,
    limit: PAGE_SIZE,
    offset,
  })

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
    setOffset(0)
  }

  /**
   * Cycle d'un en-tête : croissant → décroissant → tri par défaut.
   *
   * Le retour au tri par urgence fait partie du cycle : sans lui, on ne peut
   * plus revenir à l'ordre initial une fois une colonne cliquée.
   */
  const toggleSort = (key: string) => {
    if (!isActionSort(key)) return
    const next = new URLSearchParams(params)
    if (sort !== key) {
      next.set('tri', key)
      next.delete('sens')
    } else if (sortOrder === 'asc') {
      next.set('tri', key)
      next.set('sens', 'desc')
    } else {
      next.delete('tri')
      next.delete('sens')
    }
    setParams(next, { replace: true })
    // La page change de contenu : rester en page 6 afficherait un fragment
    // arbitraire du nouveau classement.
    setOffset(0)
  }

  const columns: Column<Action>[] = [
    {
      key: 'numero',
      header: 'N°',
      render: (action) => <span className="whitespace-nowrap font-semibold text-fg">{action.numero}</span>,
      className: 'w-32',
      sortKey: 'numero',
    },
    {
      key: 'project',
      header: 'Projet',
      render: (action) => (
        // Le nom complet en infobulle : la colonne doit rester étroite, mais
        // « P23 » seul ne dit pas de quel chantier il s'agit.
        <span className="whitespace-nowrap text-fg-muted" title={action.project_name ?? undefined}>
          {action.project_code ?? '—'}
        </span>
      ),
      className: 'w-20',
      hideOnMobile: true,
      sortKey: 'project',
    },
    {
      key: 'description',
      header: 'Description',
      render: (action) => (
        <div className="min-w-[200px]">
          <p className="line-clamp-2 text-fg">{action.description}</p>
          {action.commentaire ? (
            <p className="mt-0.5 line-clamp-1 text-[12px] text-fg-subtle">{action.commentaire}</p>
          ) : null}
        </div>
      ),
    },
    {
      key: 'responsables',
      header: 'Responsables',
      render: (action) => (
        <span className="text-fg-muted">
          {action.responsables.length > 0
            ? action.responsables.map((responsable) => responsable.display_name).join(', ')
            : '—'}
        </span>
      ),
      className: 'w-44',
      hideOnMobile: true,
    },
    {
      key: 'progress',
      header: 'Avancement',
      render: (action) => <ProgressBar value={action.progress} className="min-w-[110px]" />,
      className: 'w-44',
      hideOnMobile: true,
      sortKey: 'progress',
    },
    {
      key: 'deadline',
      header: 'Échéance',
      render: (action) => <DeadlineCell deadline={action.deadline} status={action.status} />,
      className: 'w-28',
      sortKey: 'deadline',
    },
    {
      key: 'status',
      header: 'Statut',
      render: (action) => <ActionStatusBadge status={action.status} />,
      className: 'w-32',
      sortKey: 'status',
    },
  ]

  const counts = summaryQuery.data?.counts

  return (
    <>
      <Breadcrumb items={[{ label: "Vue d'ensemble", to: '/tableau-de-bord' }, { label: 'Actions' }]} />
      <PageHeader
        title="Actions"
        description="Les vues métier sont celles utilisées par les relances et les rapports : un email et cet écran comptent toujours les mêmes actions."
        actions={
          canWrite ? (
            <Button size="sm" variant="primary" onClick={() => setModalOpen(true)}>
              <IconPlus size={14} />
              Nouvelle action
            </Button>
          ) : null
        }
      />

      {/* Onglets de vues */}
      <div className="mb-4 flex gap-1 overflow-x-auto border-b border-line pb-px">
        {TAB_VIEWS.map((tab) => {
          const active = view === tab
          const count = counts?.[tab]
          return (
            <button
              key={tab}
              type="button"
              onClick={() => setParam('vue', tab === 'all' ? '' : tab)}
              className={cn(
                'flex shrink-0 cursor-pointer items-center gap-2 border-b-2 bg-transparent px-3 py-2 text-[13px] font-medium transition-colors',
                active
                  ? 'border-b-accent text-fg'
                  : 'border-b-transparent text-fg-muted hover:text-fg',
              )}
            >
              {ACTION_VIEW_LABELS[tab]}
              {count !== undefined ? (
                <span
                  className={cn(
                    'rounded-full px-1.5 py-px text-[11px] font-semibold tabular-nums',
                    active ? 'bg-accent-subtle text-accent' : 'bg-inset text-fg-subtle',
                  )}
                >
                  {count}
                </span>
              ) : null}
            </button>
          )
        })}
      </div>

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <TextField
          className="min-w-[240px] flex-1"
          label="Rechercher"
          placeholder="Numéro, description ou commentaire…"
          value={search}
          onChange={(event) => setParam('search', event.target.value)}
        />
        <SelectField
          className="w-64"
          label="Projet"
          value={projectId}
          onChange={(event) => setParam('projet', event.target.value)}
          options={[
            { value: '', label: 'Tous les projets' },
            ...(projectsQuery.data?.items ?? []).map((project) => ({
              value: project.id,
              label: `${project.code} — ${project.name}`,
            })),
          ]}
        />
        <SelectField
          className="w-52"
          label="Vue"
          value={view}
          onChange={(event) => setParam('vue', event.target.value === 'all' ? '' : event.target.value)}
          options={ACTION_VIEWS.map((item) => ({ value: item, label: ACTION_VIEW_LABELS[item] }))}
        />
      </div>

      {actionsQuery.isError ? (
        <ErrorState error={actionsQuery.error} onRetry={() => void actionsQuery.refetch()} />
      ) : (
        <>
          <DataTable
            columns={columns}
            rows={actionsQuery.data?.items ?? []}
            rowKey={(action) => action.id}
            loading={actionsQuery.isLoading}
            sort={sort}
            sortOrder={sortOrder}
            onSort={toggleSort}
            empty={
              <EmptyState
                icon={<IconActivity size={44} strokeWidth={1.5} />}
                title="Aucune action trouvée"
                message={
                  search || projectId || view !== 'all'
                    ? 'Aucune action ne correspond à ces filtres.'
                    : "Aucune action n'est enregistrée pour le moment."
                }
                action={
                  canWrite && !search && view === 'all' ? (
                    <Button size="sm" variant="primary" onClick={() => setModalOpen(true)}>
                      <IconPlus size={14} />
                      Nouvelle action
                    </Button>
                  ) : undefined
                }
              />
            }
          />
          <Pagination
            total={actionsQuery.data?.total ?? 0}
            limit={PAGE_SIZE}
            offset={offset}
            onOffsetChange={setOffset}
          />
        </>
      )}

      <NewActionModal open={modalOpen} onClose={() => setModalOpen(false)} />
    </>
  )
}
